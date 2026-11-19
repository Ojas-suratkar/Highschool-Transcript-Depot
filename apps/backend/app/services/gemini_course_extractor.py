"""
Raw Gemini course extractor.

Clean 4-table pipeline responsibility:

- Read transcript PDF using Gemini.
- Extract raw Gemini course rows only.
- Return normalized course rows ready to save into gemini_course_details.
- Do NOT compare with Document AI.
- Do NOT write validation tables.
- Do NOT create missing/extra suggestions.

Important:
- This extractor must preserve EVERY visible transcript course row.
- Repeated visual rows are legitimate and must not be deduplicated.
- Course ID, course title, grade, and credits must come from the same visual row.
- Optional focused Course ID verifier evidence is attached to raw_payload for reconciliation.
- Optional verifier scans run in parallel after the main extraction for better batch speed.
"""

from __future__ import annotations

import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import google.auth
from google import genai
from google.genai import types
from google.oauth2 import service_account


# Known-good Vertex AI Gemini models. If GEMINI_MODEL is unset or points to a
# non-existent model (e.g. a stale "gemini-3.5-flash"), fall back to a valid one.
_VALID_GEMINI_MODELS = {
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
}


def _resolve_gemini_model() -> str:
    model_name = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    if model_name not in _VALID_GEMINI_MODELS:
        print(f"[GEMINI] GEMINI_MODEL='{model_name}' is not a known model; using gemini-2.5-flash")
        model_name = "gemini-2.5-flash"
    return model_name


def _make_gemini_client() -> genai.Client:
    """Create a Gemini client that works both locally and on Cloud Run.

    Priority:
    1. GEMINI_API_KEY / GOOGLE_API_KEY (explicit Gemini Developer API key).
    2. DOCAI_SA_KEY_B64 env var (base64 SA key with Vertex AI predict perms).
    3. Application Default Credentials (local gcloud / workload identity).
    4. Bundled cloudsql/service-account.json (last resort).
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return genai.Client(api_key=api_key)

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "doc-ai-transcript")
    location = os.getenv("GEMINI_LOCATION", "us-central1")

    sa_key_b64 = os.getenv("DOCAI_SA_KEY_B64")
    if sa_key_b64:
        try:
            sa_info = json.loads(base64.b64decode(sa_key_b64).decode())
            creds = service_account.Credentials.from_service_account_info(
                sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            project = sa_info.get("project_id", project)
            print(f"[GEMINI] Using SA from env var: {creds.service_account_email}")
            return genai.Client(vertexai=True, project=project, location=location, credentials=creds)
        except Exception as exc:  # noqa: BLE001
            print(f"[GEMINI] SA env var failed: {exc}")

    try:
        _, adc_project = google.auth.default()
        project = adc_project or project
        print(f"[GEMINI] Using ADC for project: {project}")
        return genai.Client(vertexai=True, project=project, location=location)
    except Exception as exc:  # noqa: BLE001
        print(f"[GEMINI] ADC failed: {exc}")

    sa_key_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "cloudsql", "service-account.json")
    )
    if os.path.exists(sa_key_path):
        try:
            creds = service_account.Credentials.from_service_account_file(
                sa_key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            project = creds.project_id or project
            print(f"[GEMINI] Using bundled SA key file: {creds.service_account_email}")
            return genai.Client(vertexai=True, project=project, location=location, credentials=creds)
        except Exception as exc:  # noqa: BLE001
            print(f"[GEMINI] Bundled SA key file failed: {exc}")

    raise RuntimeError("All Gemini auth methods failed.")


GEMINI_COURSE_EXTRACTION_PROMPT = """
You are extracting raw high school transcript course rows from a transcript PDF.

Use ONLY the transcript PDF. Do not use outside knowledge.
Return ONLY valid JSON. No markdown. No explanation.

Main task:
Extract EVERY real visible course row from the transcript page(s).

Important layout idea:
This transcript is made of repeated visual course blocks. A block can contain 1 course row or many course rows. The block height is NOT fixed.

Block-first extraction:
A. First detect every visible course block.
B. Then extract course rows inside each detected block.
C. Do not extract rows directly from the whole page without assigning them to a block.
D. Do not mix rows between blocks.

How to identify a block:
E. A course block usually starts near a repeated table/header area such as:
   - "Crs ID | Course Title | Mark | Cred Att/Cmp"
   - "Crs-ID | Course Title | Mark | Att/Cmp"
   - "Grade 12 Fall 2024-2025"
   - "Yr: 2024 Month: 1 Grade: 11"
F. A block may include a school name line directly above or below the table header.
G. A block ends immediately before the next course block header in the same visual column/area, a credit/GPA summary row, page footer/legend/notes, or the end of the visible course table area.
H. Never assume a fixed block height. Count the actual visible course rows inside the block.

Visual order rules:
I. Return detected_blocks in transcript visual reading order.
J. For pages with multiple vertical columns of blocks, read the leftmost column top-to-bottom, then the next column top-to-bottom, then the next column top-to-bottom.
K. Inside each block, return course rows top-to-bottom exactly as printed.
L. row_index is the global visual course-row number across the full transcript.
M. block_index identifies which detected block the course came from.
N. row_in_block starts at 1 inside each block.
O. Do not sort alphabetically, by course ID, by grade, by year, or by month. Preserve transcript order.

Continued-column context rules for 3-column transcripts:
P. Some Mayfair/LBUSD-style transcripts use three vertical columns. A term/course block can start in one column and continue at the top of the next column.
Q. If a course block continues into the next column before a new Grade/Yr/Month header is printed, keep the SAME previous block context for all continued rows.
R. Do not assign continued rows to an older or nearby header just because that header is physically above them in the next column.
S. Example: rows continued from "Grade 9 Spring 2021-2022" must keep grade_level=9, academic_year="2021-2022", year=2021, month=6 until a new visible section header appears.
T. If a course row appears before the first header in a column, look to the preceding visual column/block to determine whether it is a continuation.
U. Never reset grade_level/year/month at a column boundary unless a new visible section header is printed for that block.

Core extraction rules:
1. Extract each visible course row exactly once.
2. Do NOT deduplicate repeated courses.
   - If the same course appears twice in different terms, sections, months, years, or rows, output it twice.
   - If two rows have the same course ID, course title, grade, and credits, still output both rows when both are visible.
3. Return rows in the same visual order as the transcript:
   - top-to-bottom within each transcript block
   - left-to-right only when rows are visually in separate columns on the same horizontal band
4. Course ID, course title, grade, attempted credits, and completed credits must come from the SAME horizontal visual row.
5. Do not borrow a course ID, grade, or credit value from a nearby row.
6. If a course row is partially unclear, still output the row with null for unclear fields and extraction_confidence below 0.8.

Rows to ignore:
7. Ignore summary/header/non-course rows such as:
   - Crs-ID
   - Course Title
   - Mark
   - Att/Cmp
   - Credit Att:
   - Cmp:
   - TGPA:
   - GPA summaries
   - test sections
   - event sections
   - course tags legend rows
   - attendance/comment rows
   - parent/guardian/address/comment/footer rows

Course ID and tiny tag rules:
8. Preserve the exact visible Crs-ID text as course_id_raw.
9. Look immediately to the LEFT of the numeric course ID on the SAME visual row.
   Many transcripts show a tiny standalone prefix/tag column before the course number.
10. If a visible row tag is present, return it in visible_course_tag and include it in course_id_raw.
10a. A course row may have NO visible prefix/tag. That is valid and common.
10b. If the space immediately to the left of the course number is blank, do NOT add N, P, H, HP, +, or *.
10c. For numeric-only rows, set visible_course_tag=null, course_prefix=null, has_plus_marker=false, has_star_marker=false, and return course_id_raw as the number only, such as "8130", "3635", or "3707".
10d. The left-side tag check is only a verification step to see whether a tag exists; it is not a requirement that every row must have a tag.
11. Do not ignore small row tags like N, P, HP, H, +, or * when they appear immediately before the number.
12. Do not infer row tags from the course name, legend, school name, course number, or nearby rows.
13. If a marker is only in the legend, such as "* = Non Academic", do not add it to a course row unless it is visibly attached to that exact row.
14. Set has_plus_marker=true only if "+" is visible in that course row's ID.
15. Set has_star_marker=true only if "*" is visible in that course row's ID.
16. Keep markers/prefixes separate and exact:
   - "N 3707" means visible_course_tag="N", course_prefix="N", course_number="3707", course_id_raw="N 3707".
   - "P 2280" means visible_course_tag="P", course_prefix="P", course_number="2280", course_id_raw="P 2280".
   - "p 7510" means visible_course_tag="p", course_prefix="p", course_number="7510", course_id_raw="p 7510".
   - "HP 2999" means visible_course_tag="HP", course_prefix="HP", course_number="2999", course_id_raw="HP 2999".
   - "H 2318" means visible_course_tag="H", course_prefix="H", course_number="2318", course_id_raw="H 2318".
   - "* 8130" means visible_course_tag="*", has_star_marker=true, course_prefix=null, course_number="8130", course_id_raw="* 8130".
   - "+ p 3431" means visible_course_tag="+ p", has_plus_marker=true, course_prefix="p", course_number="3431", course_id_raw="+ p 3431".
   - "8130" means visible_course_tag=null, course_prefix=null, course_number="8130", course_id_raw="8130".
17. Community college course IDs may include letters and dashes, such as "CC006" or "CC001". Preserve the full Crs-ID exactly as printed.
18. Before finalizing each row, re-read the Course ID cell from the SAME horizontal line and verify every digit. Do not copy a course ID from a nearby row in the same block.
19. If a digit is unclear, return the unclear digit as null/low confidence instead of substituting a nearby course number.
20. Preserve visible star/non-academic markers attached to Mayfair rows, such as "* 8110", "* 8115", "* 8125", or "* 8444".

Mayfair community-college context rule:
21. If a Mayfair transcript block contains a community-college or alternate-school mini-section, such as "Cerritos Community College", the course row still inherits the visible grade/term/year context from the surrounding Mayfair grade block unless the mini-section prints a different context.
22. Example: a row under "Grade 11 Summer/Intersession 2023-2024" and "Cerritos Community College" must still return grade_level=11, term_name="Summer/Intersession", academic_year="2023-2024", year=2023, month=7.
23. Example: a row under "Grade 12 Fall 2024-2025" and "Cerritos Community College" must still return grade_level=12, term_name="Fall", academic_year="2024-2025", year=2024, month=1.

Multi-school transcript rules:
18. A transcript may include rows from multiple schools in the same PDF.
19. For EACH course row, set school_name to the school name printed in that row's own section header, not the top-level transcript header.
20. If a row belongs to a community college or alternate school section, preserve that section's school_name.
21. Do not apply one school's rules to another school's section.

Course title / subject name rules:
22. Extract course_name exactly as visually printed in the Course Title/Course Name/Subject column, including abbreviations.
23. The subject name must be written in the same word order as the transcript.
24. Do NOT reorder words.
25. Do NOT move trailing or leading fragments from nearby columns or nearby rows into the title.
26. If a title wraps across two visual lines, join the wrapped pieces in natural reading order only when the second line is visibly a continuation of the same course row.
27. A wrapped continuation line usually has no new course ID, no new grade, and no new credit value.
28. Never combine the title from one row with the grade/credits from another row.
29. Correct examples:
   - "Intgrtd Math I"
   - "Bio Lvng Erth"
   - "AP Govt/Pol Sys"
   - "Advanced Kinesiology PE 10"
   - "Big History Project World History"
   - "AP Computer Science Principles (PLTW)"
   - "CSU Expository Reading and Writing"
   - "Anatomy (H)"
   - "MUS 104B-History A"

Grade and credit rules:
27. Extract the mark/grade exactly as shown from the Mark column on the SAME horizontal row.
   Examples: "A", "A-", "B+", "C+", "D+", "D", "P", "CR", "NC", "NM".
28. Do not default unclear grades to "A". If the printed grade could be B or C, return the visible grade only if clear; otherwise return null with extraction_confidence below 0.8.
28a. If OCR/Gemini reads a grade as "DR", treat it as a bad OCR read of "D" only. "DR" is not a valid grade. Do not convert "DR" to "CR".
28b. "CR" is valid only when the Mark/Grade cell visibly says "CR".
29. After extracting a block, scan the Mark column once more row-by-row and verify the grade for each course row before returning JSON.
30. Extract both credit columns from the same visual row:
   - credit_attempted from the attempted/Att column
   - credit_completed from the completed/Cmp column
29. If the transcript shows one visible credit value and it clearly applies to both attempted and completed, use that value for both.
30. If credit is missing or unclear, return null. Do not guess.
31. Do not confuse term credit summary rows with course rows.

Term, grade-year, year, and month rules:
32. Extract the section/header context for each course row.
   Examples:
   - "Grade 12 Fall 2024-2025"
   - "Grade 10 Spring 2022-2023"
   - "Grade 11 Summer/Intersession 2023-2024"
   - "Yr: 2024 Month: 1 Grade: 11"
33. From the visible section/header context, derive:
   - grade_level: number only, like 7, 8, 9, 10, 11, or 12
   - term_name: "Fall", "Spring", "Summer", "Summer/Intersession", "SEM1", "SEM2", "S_SCH", or null
   - academic_year: "2024-2025" if visible or derivable from the header
   - year: the transcript year for that course row
34. For Fall/Spring/Summer academic-year headers, year must ALWAYS be the START year of the academic school-year range:
   - Fall 2022-2023 -> academic_year="2022-2023", year=2022, month=1
   - Spring 2022-2023 -> academic_year="2022-2023", year=2022, month=6
   - Summer 2023-2024 -> academic_year="2023-2024", year=2023, month=7
35. If the row/header directly shows a single year and no academic-year range is visible or derivable, use that single year.

School-specific month rules:
36. Mayfair High School rows ONLY:
   - Fall -> month=1
   - Spring -> month=6
   - Summer / Summer School / Summer Intersession / Intersession / Summer/Intersession -> month=7
37. Do NOT apply Mayfair Fall/Spring/Summer month inference to any non-Mayfair school.
38. LBUSD / Millikan / Sato / Jordan style rows:
   - Use the exact visible "Month: N" value from the section header.
   - Do NOT infer month from Fall/Spring/Summer words.
   - If "Month: N" is missing, return month=null.
39. St. Anthony / Saint Anthony rows:
   - month must be null.
   - Do not infer month.
40. Other schools:
   - If an actual visible month number or month name is printed for that row/section, extract it.
   - If no month is visibly printed, return month=null.
41. Do not lower extraction_confidence only because month is null when the transcript format does not show month.

Duplicate row protection:
42. Before finalizing, scan the transcript again section by section.
43. Count all real visible course rows.
44. Make sure every visible row has one object in courses.
45. Especially check repeated courses such as PE, Advanced Kinesiology, repeated Math/English rows, repeated Fall/Spring rows, or courses with the same ID/name/grade/credits.
46. Do not remove a repeated row simply because it looks identical to another row.

Course ID alignment protection:
47. For every row, verify that course_id_raw belongs to the same visual line as course_name.
48. If a course title is "Big History Project World History", do not use a nearby "3707" unless 3707 is on the same row.
49. Use the exact ID from that visual row, such as "P 2280", when that is what the transcript shows.

Confidence rules:
50. Add extraction_confidence from 0.0 to 1.0 for each row:
   - 1.0 means the row is clearly visible and all important fields are clear.
   - 0.8 means the row is visible but one field is slightly uncertain.
   - below 0.8 means the row needs manual review.
51. Missing optional month should not lower confidence when the transcript format does not show month.
52. Missing optional course_id should not lower confidence only when that transcript format does not show course IDs.

Return JSON in exactly this shape:

{
  "total_course_count": 0,
  "detected_blocks": [
    {
      "block_index": 1,
      "page_number": 1,
      "visual_column": 1,
      "block_header": "Grade 12 Fall 2024-2025",
      "school_name": "Mayfair High School",
      "grade_level": 12,
      "term_name": "Fall",
      "academic_year": "2024-2025",
      "year": 2024,
      "month": 1,
      "course_row_count": 0
    }
  ],
  "section_course_counts": [
    {
      "section_name": "Grade 12 Fall 2024-2025",
      "course_count": 0
    }
  ],
  "courses": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "Grade 12 Fall 2024-2025",
      "grade_level": 12,
      "term_name": "Fall",
      "academic_year": "2024-2025",
      "year": 2024,
      "month": 1,
      "school_name": "Mayfair High School",

      "course_id_raw": "+ p 3630",
      "visible_course_tag": "+ p",
      "has_plus_marker": true,
      "has_star_marker": false,
      "course_prefix": "p",
      "course_number": "3630",

      "course_name": "AP English 12",
      "grade": "B",
      "credit_attempted": 5.0,
      "credit_completed": 5.0,
      "extraction_confidence": 1.0
    }
  ]
}

Before returning JSON, count the number of course objects in courses and set total_course_count to that exact number.
"""


ST_ANTHONY_COURSE_EXTRACTION_PROMPT = """
You are extracting raw course rows from a St. Anthony / Saint Anthony High School transcript PDF.

Use ONLY the transcript PDF. Do not use outside knowledge.
Return ONLY valid JSON. No markdown. No explanation.

This is a St. Anthony format transcript. It is different from Mayfair/LBUSD.

Block-first extraction:
1. First detect each school-year block, such as:
   - 24-25 St. Anthony High School
   - 23-24 St. Anthony High School
   - 22-23 St. Anthony High School
   - 21-22 St. Anthony High School
2. A block starts at the school-year header and includes the subject rows under that header.
3. A block ends before the next school-year header or before footer/summary/comment sections.
4. Do not assume a fixed block height.
5. Return blocks and rows in transcript visual order: top-to-bottom by school-year block, then top-to-bottom by subject row inside the block.

St. Anthony layout rules:
1. The transcript has school-year sections such as:
   - 24-25 St. Anthony High School
   - 23-24 St. Anthony High School
   - 22-23 St. Anthony High School
   - 21-22 St. Anthony High School
2. The course/subject names are listed in the left subject column.
3. Grades and credits are in semester columns: SEM 1, SEM 2, and sometimes S_SCH.
4. Treat each visible semester grade+credit cell as its own course row.
   - If a subject has SEM 1 grade/credit and SEM 2 grade/credit, output TWO separate rows.
   - If S_SCH has a grade/credit, output one row for S_SCH.
   - Do not collapse SEM 1 and SEM 2 into one row.
5. Ignore blank/empty semester cells.
6. Ignore parent/guardian, address, comments, GPA summaries, and non-course footer sections.

Non-St. Anthony school blocks:
7. This transcript may include blocks from schools other than St. Anthony, such as "BYU Independent Study HS".
8. Extract course rows from those blocks using the same visible SEM column rules.
9. Set school_name to the exact school name shown in that block's header.
10. The academic_year and grade_level for those rows should match the year block they appear in.
11. term_name for those rows follows the same SEM1/SEM2/S_SCH logic.

Subject/course name rules:
12. course_name must be exactly the visible subject name as printed in the subject column.
13. Preserve abbreviations and punctuation.
14. Do not reorder words.
15. Do not combine subject text from neighboring rows.
16. If a subject name wraps, join only the wrapped continuation text that visually belongs to the same subject row.

St. Anthony field rules:
17. St. Anthony does not show normal course IDs in this table:
   - course_id_raw must be null
   - visible_course_tag must be null
   - has_plus_marker must be false
   - has_star_marker must be false
   - course_prefix must be null
   - course_number must be null
13. course_name must be exactly the visible subject name as printed.
14. grade must be the visible letter grade in SEM 1, SEM 2, or S_SCH.
15. credit_attempted and credit_completed must be the visible credit value next to that grade in the same cell.
   Example: "A 5.00" -> grade="A", credit_attempted=5.0, credit_completed=5.0.
16. If credit is missing or not visible, return null. Do not default to 5.0.
17. month must be null. Do not infer month for St. Anthony or BYU rows.
18. Missing course_id_raw and missing month are expected for this format and should not lower extraction_confidence.
19. Only lower extraction_confidence when course name, grade, credit, school-year section, or semester column is unclear.

Semester rules:
20. term_name for each row must be exactly one of:
   - "SEM1" for the SEM 1 column
   - "SEM2" for the SEM 2 column
   - "S_SCH" for the S_SCH/summer school column

Year and grade-level rules:
21. year and academic_year come from the school-year section header:
   - 24-25 -> year=2024, academic_year="2024-2025"
   - 23-24 -> year=2023, academic_year="2023-2024"
   - 22-23 -> year=2022, academic_year="2022-2023"
   - 21-22 -> year=2021, academic_year="2021-2022"
22. grade_level should be inferred from the high-school sequence:
   - 21-22 -> grade_level=9
   - 22-23 -> grade_level=10
   - 23-24 -> grade_level=11
   - 24-25 -> grade_level=12
23. If the transcript visibly shows a different grade/year sequence, use the visible context.

Return JSON in exactly this shape:

{
  "total_course_count": 0,
  "detected_blocks": [
    {
      "block_index": 1,
      "page_number": 1,
      "visual_column": 1,
      "block_header": "24-25 St. Anthony High School",
      "school_name": "St. Anthony High School",
      "grade_level": 12,
      "term_name": null,
      "academic_year": "2024-2025",
      "year": 2024,
      "month": null,
      "course_row_count": 0
    }
  ],
  "section_course_counts": [
    {
      "section_name": "24-25 St. Anthony High School",
      "course_count": 0
    }
  ],
  "courses": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "24-25 St. Anthony High School",
      "grade_level": 12,
      "term_name": "SEM1",
      "academic_year": "2024-2025",
      "year": 2024,
      "month": null,
      "school_name": "St. Anthony High School",

      "course_id_raw": null,
      "visible_course_tag": null,
      "has_plus_marker": false,
      "has_star_marker": false,
      "course_prefix": null,
      "course_number": null,

      "course_name": "Anatomy and Physiology",
      "grade": "A",
      "credit_attempted": 5.0,
      "credit_completed": 5.0,
      "extraction_confidence": 1.0
    }
  ]
}

Before returning JSON, count the number of course objects in courses and set total_course_count to that exact number.
"""


LBUSD_COURSE_EXTRACTION_PROMPT = """
You are extracting raw high school transcript course rows from an LBUSD / Cabrillo / Millikan / Sato / Jordan / Wilson / McBride / Avalon style transcript PDF.

Use ONLY the transcript PDF. Do not use outside knowledge.
Return ONLY valid JSON. No markdown. No explanation.

Critical layout rule:
LBUSD-style transcripts are made of repeated course blocks. A block can contain 1 row or many rows. The block height is NOT fixed.

Block-first extraction:
1. First detect every visible course block.
2. Then extract course rows inside each detected block only.
3. Do not mix course rows between blocks.
4. Do not extract rows globally without assigning them to a block.

How to identify an LBUSD block:
5. A block usually has:
   - a repeated table header like "Crs ID | Course Title | Mark | Cred Att/Cmp"
   - a school name line such as "Cabrillo High School", "Millikan High School", "Sato Academy", "Jordan High School", "Wilson High School", "McBride High School", or "Avalon High School"
   - a context line like "Yr: 2024  Month: 1  Grade: 11"
6. The order of these lines may vary slightly, but they belong to the same block when visually grouped.
7. The block starts at that grouped header/context area.
8. The block ends immediately before the next grouped header/context area in the same visual column/area, or before a credit/GPA summary/footer.
9. Never assume a fixed height. Count only the visible course rows actually inside the block.

Visual order rules:
10. Return detected_blocks in the exact visual reading order of the transcript.
11. On pages with three vertical columns of blocks, read left column top-to-bottom, then middle column top-to-bottom, then right column top-to-bottom.
12. Inside each block, read rows top-to-bottom.
13. row_index is the global transcript course-row number.
14. block_index identifies the detected block.
15. row_in_block starts at 1 inside each block.
16. Do not sort by course ID, name, grade, year, or month. Preserve transcript order.

Continued-column context rules:
16a. LBUSD-style transcripts can have three vertical columns. A course block can start in one column and continue at the top of the next column.
16b. If rows continue into the next column before a new visible Yr/Month/Grade header is printed, keep the SAME previous Yr/Month/Grade context.
16c. Do not reset the row to an older or physically-nearby header at the top of the next column.
16d. Example: rows continued from "Yr: 2021 Month: 6 Grade: 10" must keep visible Yr=2021, month=6, grade_level=10, and saved academic-year start year=2020 if the academic-year derivation requires it.
16e. A column boundary alone is not a new term. Only a new visible Yr/Month/Grade header starts a new term context.

LBUSD-style layout rules:
17. Section headers look like:
   "Yr: 2021  Month: 1  Grade: 09"
   followed by a school name line, such as "Millikan High School".
2. Extract these values exactly as shown in each section header:
   - year from "Yr: YYYY"
   - month from "Month: M"
   - grade_level from "Grade: GG" and strip leading zeros
   - school_name from the school line immediately below the Yr/Month/Grade header
3. month always comes from the explicit "Month: N" value in the section header.
4. Do NOT infer month from Fall/Spring/Summer in this format.
5. If Month is visible, use it directly.
6. If Month is not visible, return month=null.

Term and academic year:
7. Derive term_name from the visible month number:
   - Month 1 -> term_name="Fall"
   - Month 6 -> term_name="Spring"
   - Month 7 -> term_name="Summer"
   - Any other month -> term_name=null
8. Store year as the START year of the academic school-year range, not the Spring/Summer ending calendar year.
9. Derive academic_year from the visible Yr + Month context, then set year to the academic_year start:
   - visible Yr: 2021, Month: 1/Fall   -> academic_year="2021-2022", year=2021, month=1
   - visible Yr: 2022, Month: 6/Spring -> academic_year="2021-2022", year=2021, month=6
   - visible Yr: 2022, Month: 1/Fall   -> academic_year="2022-2023", year=2022, month=1
   - visible Yr: 2023, Month: 6/Spring -> academic_year="2022-2023", year=2022, month=6
   - visible Yr: 2023, Month: 1/Fall   -> academic_year="2023-2024", year=2023, month=1
   - visible Yr: 2024, Month: 6/Spring -> academic_year="2023-2024", year=2023, month=6
   - visible Yr: 2024, Month: 1/Fall   -> academic_year="2024-2025", year=2024, month=1
   - visible Yr: 2025, Month: 6/Spring -> academic_year="2024-2025", year=2024, month=6
10. If term_name is null and no academic-year range is visible or derivable, use the visible year as the start:
   academic_year="YYYY-(YYYY+1)"

Multi-school transcript rules:
10. This transcript may include sections from multiple schools.
11. Include all real course rows from every visible section.
12. Set school_name per row from that row's own section header school line.
13. Do not use the top-level transcript header as school_name unless that is the section school line.

Course ID rules:
14. Course IDs may have a visible prefix/tag column immediately to the left of the course number, but many valid course IDs are numbers only.
15. Preserve the exact visible Course ID as course_id_raw. If the row shows only a number, return only that number.
16. When a prefix/tag is visibly printed on the same row, valid prefix tags include P, p, N, n, H, h, HP, hp, +, *, + p, + P, + H, + HP, + N.
17. Do a dedicated left-edge tag sweep before returning JSON: for every numeric course ID, look immediately left on the same row for tiny tags. Do not drop a visible tag because it is small or close to the table border.
17a. If the space immediately left of the course number is blank, visible_course_tag must be null and course_id_raw must stay numeric-only.
17b. Do not add P/N/H/HP/+/* just because the transcript legend defines them; the marker must be printed on that exact row.
18. Examples:
   - "P 1082" -> course_id_raw="P 1082", course_prefix="P", course_number="1082"
   - "N 3775" -> course_id_raw="N 3775", course_prefix="N", course_number="3775"
   - "N 3635" -> course_id_raw="N 3635", course_prefix="N", course_number="3635"
   - "N 3707" -> course_id_raw="N 3707", course_prefix="N", course_number="3707"
   - "H 2318" -> course_id_raw="H 2318", course_prefix="H", course_number="2318"
   - "HP 2999" -> course_id_raw="HP 2999", course_prefix="HP", course_number="2999"
   - "1391" -> course_id_raw="1391", visible_course_tag=null, course_prefix=null, course_number="1391"
   - "3635" with blank tag area -> course_id_raw="3635", visible_course_tag=null, course_prefix=null, course_number="3635"
   - "3707" with blank tag area -> course_id_raw="3707", visible_course_tag=null, course_prefix=null, course_number="3707"
   - "* 8130" -> course_id_raw="* 8130", visible_course_tag="*", has_star_marker=true, course_number="8130"
19. Do not infer a prefix from the legend row at the bottom.
20. Only add a prefix/tag when it is visibly printed on that exact course row.
21. If a row title is "Team Soccer JV/JV Boys" and the Course ID cell shows "N 3635", return "N 3635", not "3635".
22. If a row title is "Advanced Kinesiology PE 10" and the Course ID cell shows "N 3707", return "N 3707", not "3707".

Credit rules:
20. Credits are usually shown as "5.00 / 5.00":
   - left value is credit_attempted
   - right value is credit_completed
21. Some rows may show "0.00 / 0.00". Preserve 0.0; do not treat it as missing.
22. If credit is missing or unclear, return null.

Rows to ignore:
23. Ignore GPA summary rows containing "Cred Att:", "Cred Cmp:", or "GPA:".
24. Ignore "Continued on next column..." footer lines.
25. Ignore bottom legends such as P = CSU/UC, N = Non-Academic, H = Honors.
26. Ignore GPA SUMMARY and NOTES sections.
27. Ignore column header rows such as Crs ID, Course Title, Mark, Cred Att/Cmp.
28. Ignore transcript banner lines such as "LBUSD Transcript (Work in Progress - Not Included)".

Course field rules:
29. Extract the course title exactly as visually printed in the Course Title column.
30. Preserve the transcript's word order and abbreviations.
31. If a title wraps across two visual lines, join only the continuation text that visually belongs to the same course row.
32. A continuation line usually has no new course ID, no new grade, and no new credit value.
33. Do not reorder course names.
34. Do not move fragments from another column or row into the title.
34a. If the final standalone token of the title is actually the Mark/Grade value, keep it out of course_name and put it in grade.
    Example: "E Sprt Vid Game B" must become course_name="E Sprt Vid Game", grade="B".
    Example: "E Sprt AdvVGame B" must become course_name="E Sprt AdvVGame", grade="B" only if B is the visible mark for that same row.
35. Correct examples:
   - "AP Computer Science Principles (PLTW)"
   - "CSU Expository Reading and Writing"
   - "English 3-4 Accelerated"
   - "Introduction to Design 1,2 (PLTW)"
   - "Human Body Systems (PLTW)"
   - "AP Spanish Language and Culture"
   - "Big History Project World History"
36. Extract the mark/grade exactly as shown from the Mark column on the SAME visual row.
   Examples: "A", "B", "C", "D", "F", "P", "CR", "NC", "NM".
37. Do not default the mark to "A". LBUSD rows often contain B or C marks; read the printed letter carefully.
38. Before returning JSON, do a second Mark-column sweep inside each block and verify every grade against the same row's course ID/title/credits.
39. If the mark cell is unclear, return grade=null and extraction_confidence below 0.8 instead of guessing A.
40. Known risky examples to avoid: Modern World History Accelerated can be C or B; Physics of the Universe can be B; do not change them to A unless A is visibly printed on that same row.
41. If OCR/Gemini reads a grade as "DR", treat it as a bad OCR read of "D" only. "DR" is not a valid grade. Do not convert "DR" to "CR".
42. "CR" is valid only when the Mark/Grade cell visibly says "CR".

Duplicate row protection:
33. The same course may appear in adjacent column blocks for different year/month sections.
34. Output every occurrence as a separate row.

Confidence rules:
35. Add extraction_confidence from 0.0 to 1.0:
   - 1.0 means row clearly visible and fields are unambiguous.
   - 0.8 means row visible but one field slightly uncertain.
   - below 0.8 means manual review may be needed.

Return JSON in exactly this shape:

{
  "total_course_count": 0,
  "detected_blocks": [
    {
      "block_index": 1,
      "page_number": 1,
      "visual_column": 1,
      "block_header": "Millikan High School Yr: 2021 Month: 1 Grade: 09",
      "school_name": "Millikan High School",
      "grade_level": 9,
      "term_name": "Fall",
      "academic_year": "2021-2022",
      "year": 2021,
      "month": 1,
      "course_row_count": 0
    }
  ],
  "section_course_counts": [
    {
      "section_name": "Millikan High School Yr: 2021 Month: 1 Grade: 09",
      "course_count": 0
    }
  ],
  "courses": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "Millikan High School Yr: 2021 Month: 1 Grade: 09",
      "grade_level": 9,
      "term_name": "Fall",
      "academic_year": "2021-2022",
      "year": 2021,
      "month": 1,
      "school_name": "Millikan High School",

      "course_id_raw": "P 1082",
      "visible_course_tag": "P",
      "has_plus_marker": false,
      "has_star_marker": false,
      "course_prefix": "P",
      "course_number": "1082",

      "course_name": "Art 1-2: Foundations",
      "grade": "B",
      "credit_attempted": 5.0,
      "credit_completed": 5.0,
      "extraction_confidence": 1.0
    }
  ]
}

Before returning JSON, count the number of course objects in courses and set total_course_count to that exact number.
"""


MAYFAIR_COURSE_EXTRACTION_PROMPT = """
You are extracting course rows from a MAYFAIR HIGH SCHOOL transcript PDF.
This transcript is confirmed to be Mayfair High School. Apply the Mayfair rules
below to EVERY row.

Layout:
A. Mayfair transcripts are laid out in up to three vertical columns.
B. Read column 1 fully top-to-bottom, then column 2, then column 3.
C. Each column is divided into term blocks. A term block starts with a section
   header line and contains the course rows printed under it until the next
   header.
D. Section headers look like one of:
   - "Grade 9 Fall 2021-2022"
   - "Grade 10 Spring 2022-2023"
   - "Grade 11 Summer 2023-2024"  (also "Summer School", "Intersession",
     "Summer/Intersession")
   The header gives the grade level, the term (Fall/Spring/Summer), and the
   academic-year range.

The single most important rule — term context for EVERY row:
1. Every course row belongs to the term block whose header appears above it in
   the same column. Assign that header's context to the row.
2. For EACH course row you MUST fill, never null:
   - grade_level: the grade number from the header (9, 10, 11, 12)
   - term_name: "Fall", "Spring", "Summer", "Summer School", "Intersession", or
     "Summer/Intersession" exactly as the header shows
   - academic_year: the full range from the header, e.g. "2021-2022"
   - year: the START year of that range (2021-2022 -> 2021, 2022-2023 -> 2022)
   - month: derived from the term — Fall -> 1, Spring -> 6,
     Summer / Summer School / Intersession / Summer/Intersession -> 7
   - school_name: "Mayfair High School"
3. A term block can begin at the bottom of one column and continue at the top of
   the next column. Rows that continue keep the SAME grade_level / term_name /
   academic_year / year / month until a NEW visible header is printed. Never
   reset the term context at a column boundary that has no header.
4. If a row appears before the first header in a column, it is a continuation of
   the last block from the previous column — inherit that block's context.
5. If a Mayfair block contains a community-college or alternate-school
   mini-section (e.g. "Cerritos Community College"), the row STILL inherits the
   surrounding Mayfair grade/term/year context unless the mini-section prints its
   own different header. Keep school_name as the section's school when a
   different school line is printed, otherwise "Mayfair High School".

Course rows:
6. One object in "courses" per visible course row. Include repeated courses (PE,
   repeated Math/English, the same course in Fall and Spring) as separate rows.
   Never drop a row because it looks identical to another.
7. course_id_raw is the exact ID on that visual row, e.g. "p 7510", "* p 8501",
   "+ p 4140", "6875", "+ CC001". Preserve the exact case (Mayfair prints a
   lower-case "p"). Set course_prefix and course_number from it.
8. visible_course_tag / has_plus_marker / has_star_marker come only from the
   markers printed on that same row.
9. course_name, grade, credit_attempted, credit_completed come from that same
   visual row.
10. Preserve transcript visual order. Do not sort.

Confidence:
11. extraction_confidence 0.0-1.0 per row. Do NOT lower confidence because a
    field was inherited from the section header — inherited grade/term/year/month
    are expected and correct for Mayfair.

Return JSON in exactly this shape:

{
  "total_course_count": 0,
  "detected_blocks": [
    {
      "block_index": 1,
      "page_number": 1,
      "visual_column": 1,
      "block_header": "Grade 9 Fall 2021-2022",
      "school_name": "Mayfair High School",
      "grade_level": 9,
      "term_name": "Fall",
      "academic_year": "2021-2022",
      "year": 2021,
      "month": 1,
      "course_row_count": 0
    }
  ],
  "section_course_counts": [
    { "section_name": "Grade 9 Fall 2021-2022", "course_count": 0 }
  ],
  "courses": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "Grade 9 Fall 2021-2022",
      "grade_level": 9,
      "term_name": "Fall",
      "academic_year": "2021-2022",
      "year": 2021,
      "month": 1,
      "school_name": "Mayfair High School",

      "course_id_raw": "p 7510",
      "visible_course_tag": "p",
      "has_plus_marker": false,
      "has_star_marker": false,
      "course_prefix": "p",
      "course_number": "7510",

      "course_name": "Intgrtd Math I",
      "grade": "B-",
      "credit_attempted": 5.0,
      "credit_completed": 5.0,
      "extraction_confidence": 1.0
    }
  ]
}

Before returning JSON, count the number of course objects in courses and set
total_course_count to that exact number.
"""


GEMINI_COURSE_TAG_SCAN_PROMPT = """
You are doing a small second pass on a high school transcript PDF.

Use ONLY the transcript PDF.
Return ONLY valid JSON. No markdown. No explanation.

Task:
Scan ONLY the tiny course-ID prefix/tag area immediately to the LEFT of each numeric course ID.
This pass is only for visible row tags/prefixes, not for full course extraction.

Important rules:
1. Return rows in the same visual order as the transcript course rows.
2. Use the same block order as the transcript:
   - left column top-to-bottom, then next column top-to-bottom, then next column
   - inside each block, top-to-bottom
2. Do not extract summary rows, headers, legends, GPA rows, comments, attendance rows, test rows, or footer rows.
3. For each real course row with a course number, return:
   - row_index in visual order
   - section_name if visible
   - course_number numeric part only
   - course_name short title if visible, only to help alignment
   - visible_course_tag if a tiny standalone tag is visible immediately left of the number
   - course_id_raw rebuilt from visible tag + number when a tag exists
4. Valid visible_course_tag values are only:
   - "N", "P", "p", "H", "h", "HP", "hp", "+", "*"
   - "+ p", "+ P", "+ H", "+ HP", "+ N"
   - "* p", "* P", "* H", "* HP", "* N"
5. If no tag is visible immediately left of that course number, visible_course_tag must be null and course_id_raw should be the number only or null; do not invent a tag.
6. Numeric-only Course IDs are valid. A blank tag area means the row is numeric-only, not missing a tag.
7. Do not infer tags from the course title, legend, school name, course number, or nearby rows.
7. Do not add "*" just because the transcript legend says "* = Non Academic".
8. Only add "*" when the star is visible on that exact row.
9. This pass is especially for tiny markers like:
   - "* 8130"
   - "N 3707"
   - "+ p 3431"
   - "HP 2999"
   - "H 2318"
   - "P 1082"

Return JSON in exactly this shape:

{
  "tag_rows": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "Grade 9 Fall 2021-2022",
      "course_number": "8130",
      "course_name": "PE 9-12(Spring)",
      "visible_course_tag": "*",
      "course_id_raw": "* 8130",
      "tag_confidence": 1.0
    }
  ]
}
"""


GEMINI_COURSE_ID_SCAN_PROMPT = """
You are doing a focused Course ID verification pass on a high school transcript PDF.

Use ONLY the transcript PDF.
Return ONLY valid JSON. No markdown. No explanation.

Task:
Scan ONLY real visible course rows and extract the Course ID / Crs ID value from the same horizontal visual row.
Pay special attention to tiny left-side tags/prefixes such as N, P, H, HP, +, and *; they are part of the Course ID when visible.

This pass is not full course extraction.
This pass is evidence-only for Course ID accuracy. It must not create, remove, reorder, or rewrite course rows.
The backend stores your Course ID as verifier evidence and reconciliation decides whether to use it.

Critical Course ID rules:
1. The Course ID must come from the Crs ID / Course ID cell on the SAME horizontal visual row as:
   - course_name
   - grade / mark
   - credit_attempted / credit_completed
2. Do NOT borrow a Course ID or prefix from the row above, row below, another column, another block, another month block, or another repeated course.
3. If the Course ID cell is unclear, return course_id_raw=null and course_id_confidence below 0.8.
4. Do not guess unclear Course IDs.
5. Do not use GPA, summary, credit, comment, footer, legend, or header rows as course IDs.

Prefix/tag rules:
6. Preserve the exact visible Course ID text as course_id_raw.
7. Look immediately to the LEFT of the numeric course ID on the SAME visual row.
8. If a visible row tag/prefix is present, include it exactly in course_id_raw.
8a. If no tag/prefix is visible immediately to the left, return the numeric-only Course ID. Do not add a prefix.
8b. Numeric-only Course IDs are valid and should remain numeric-only when the tag area is blank.
9. Do not infer prefixes/tags from the course name, legend, school name, course number, or nearby rows.
10. Do not add "*" or "+" only because a transcript legend mentions it.
11. Only add "*" or "+" when it is visibly attached to that exact row.
12. Examples:
    - visible "P 2986" -> course_id_raw="P 2986", course_prefix="P", course_number="2986"
    - visible "N 3707" -> course_id_raw="N 3707", course_prefix="N", course_number="3707"
    - visible "HP 2236" -> course_id_raw="HP 2236", course_prefix="HP", course_number="2236"
    - visible "H 2318" -> course_id_raw="H 2318", course_prefix="H", course_number="2318"
    - visible "IN 3707" -> course_id_raw="IN 3707" only if IN is actually visible on that exact row
    - visible "AP 3852" -> course_id_raw="AP 3852" only if AP is actually visible as the Course ID/prefix on that exact row
    - visible "3707" with no prefix -> course_id_raw="3707", course_prefix=null, course_number="3707"
13. AP and IN are not automatically invalid. Preserve them only when visibly printed in the Course ID cell/prefix area for that exact row.
14. If the main extraction might show only "3635" but the row visibly shows "N 3635", return course_id_raw="N 3635".
15. If the main extraction might show only "3707" but the row visibly shows "N 3707", return course_id_raw="N 3707".
16. If the row visibly shows "* 8110", "* 8115", "* 8125", or "* 8444", include the star in course_id_raw.
17. Re-read every Course ID digit. Do not substitute a nearby row's number when one digit is unclear.

Block and order rules:
14. Use the same transcript visual order:
   - left column top-to-bottom, then next column top-to-bottom, then next column
   - inside each block, top-to-bottom
15. A block can contain 1 row or many rows. Do not assume fixed block height.
16. row_index is the global visual course row number.
17. block_index identifies the detected course block when visible/known.
18. row_in_block starts at 1 inside each block when visible/known.

Context rules:
19. Include enough context to let the backend match the Course ID row safely:
   - row_index
   - block_index
   - row_in_block
   - section_name
   - year
   - month
   - grade_level
   - course_id_raw
   - visible_course_tag
   - course_prefix
   - course_number
   - course_name
   - grade
   - credit_attempted
   - credit_completed
20. For LBUSD-style rows, month must come from the visible "Month: N" block header.
21. For Mayfair rows, month can follow the Mayfair term rule.
21a. For Mayfair/LBUSD continued-column rows, keep the previous visible term context until a new section header is printed. Do not reset year/month/grade at a column boundary.
22. For St. Anthony rows, course_id_raw should be null and month should be null.

Return JSON in exactly this shape:
{
  "course_id_rows": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "McBride High School Yr: 2022 Month: 6 Grade: 09",
      "year": 2022,
      "month": 6,
      "grade_level": 9,
      "course_id_raw": "P 2986",
      "visible_course_tag": "P",
      "has_plus_marker": false,
      "has_star_marker": false,
      "course_prefix": "P",
      "course_number": "2986",
      "course_name": "Algebra 1",
      "grade": "C",
      "credit_attempted": 5.0,
      "credit_completed": 5.0,
      "course_id_confidence": 1.0
    }
  ]
}
"""


GEMINI_GRADE_SCAN_PROMPT = """
You are doing a focused grade verification pass on a high school transcript PDF.

Use ONLY the transcript PDF.
Return ONLY valid JSON. No markdown. No explanation.

Task:
Scan ONLY real visible course rows and extract the Mark/Grade value from the same horizontal row.
Pay special attention to A/B/C marks; do not default unclear marks to A.

This pass is not full course extraction.
This pass is evidence-only for grade accuracy. It must not create, remove, reorder, or rewrite course rows.
The backend stores your grade as verifier evidence and reconciliation decides whether to use it.

Critical grade rules:
1. The grade must come from the Mark/Grade cell on the SAME horizontal visual row as:
   - course_id_raw
   - course_name
   - credit_attempted / credit_completed
2. Do NOT borrow a grade from the row above, row below, another column, another block, another month block, or another repeated course.
3. If the grade cell is unclear, return grade=null and grade_confidence below 0.8.
4. Do not guess unclear grades.
5. Do not use GPA, summary, credit, comment, or footer rows as course grades.
6. Extract the grade exactly as printed.
   Examples: "A", "A-", "B+", "C", "D", "F", "P", "CR", "NC", "NM".
6a. If OCR/Gemini reads a grade as "DR", treat it as a bad OCR read of "D" only. "DR" is not a valid grade. Do not convert "DR" to "CR".
6b. "CR" is valid only when the Mark/Grade cell visibly says "CR".
7. If the cell is B or C, return B or C. Do not normalize or upgrade it to A.
8. If the mark cell is unclear, return grade=null and grade_confidence below 0.8.
9. Before returning JSON, scan the Mark column again top-to-bottom inside each block and verify every grade against its same-row course title and credits.

Block and order rules:
7. Use the same transcript visual order:
   - left column top-to-bottom, then next column top-to-bottom, then next column
   - inside each block, top-to-bottom
8. A block can contain 1 row or many rows. Do not assume fixed block height.
9. row_index is the global visual course row number.
10. block_index identifies the detected course block when visible/known.
11. row_in_block starts at 1 inside each block when visible/known.

Context rules:
12. Include enough context to let the backend match the grade row safely:
   - row_index
   - block_index
   - row_in_block
   - section_name
   - year
   - month
   - grade_level
   - course_id_raw
   - course_number
   - course_name
   - credit_attempted
   - credit_completed
13. For LBUSD-style rows, month must come from the visible "Month: N" block header.
14. For Mayfair rows, month can follow the Mayfair term rule.
14a. For Mayfair/LBUSD continued-column rows, keep the previous visible term context until a new section header is printed. Do not reset year/month/grade at a column boundary.
15. For St. Anthony rows, month must be null and SEM1/SEM2/S_SCH cells are separate rows.

Return JSON in exactly this shape:
{
  "grade_rows": [
    {
      "row_index": 1,
      "block_index": 1,
      "row_in_block": 1,
      "section_name": "Cabrillo High School Yr: 2022 Month: 7 Grade: 10",
      "year": 2022,
      "month": 7,
      "grade_level": 10,
      "course_id_raw": "P 2986APEX",
      "course_number": "2986",
      "course_name": "Algebra 1 APEX",
      "grade": "C",
      "credit_attempted": 5.0,
      "credit_completed": 5.0,
      "grade_confidence": 1.0
    }
  ]
}
"""

def _safe_json_loads(text: str) -> dict[str, Any]:
    if not text:
        raise json.JSONDecodeError("Empty Gemini response", text, 0)

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # LLM JSON defects (trailing commas, missing braces, unquoted keys) are
    # DETERMINISTIC at temperature 0 — the same input reproduces the same defect
    # forever, so without repair a given document/student stays unparseable no
    # matter how many times we retry. json_repair handles the whole defect class.
    try:
        from json_repair import repair_json

        parsed = json.loads(repair_json(cleaned))
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # noqa: BLE001 — fall through to the substring attempt
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start != -1 and end != -1 and end > start:
        parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", cleaned[start : end + 1]))
        if isinstance(parsed, dict):
            return parsed

    raise json.JSONDecodeError("Could not parse Gemini JSON", cleaned, 0)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _clean_text(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value).strip()
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = re.sub(r"\s+", " ", text)

    return text or None


def _clean_course_id_text(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value).strip()

    text = text.replace("＊", "*")
    text = text.replace("﹡", "*")
    text = text.replace("⁎", "*")
    text = text.replace("∗", "*")
    text = text.replace("✱", "*")
    text = text.replace("✲", "*")
    text = text.replace("＋", "+")
    text = text.replace("﹢", "+")
    text = text.replace("–", "-")
    text = text.replace("—", "-")

    text = re.sub(r"\s+", " ", text).strip()

    # Normalize spacing around visible course-id markers without inventing markers.
    text = re.sub(r"^\+\s*", "+ ", text)
    text = re.sub(r"^\*\s*", "* ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text or None



def _clean_visible_course_tag(value: Any) -> str | None:
    text = _clean_course_id_text(value)

    if not text:
        return None

    # Keep only tags that are plausible standalone row-prefix markers.
    # Do not accept course-title words here.
    text = text.strip()
    text = re.sub(r"\s+", " ", text)

    # Some model outputs may include labels like "tag: N".
    text = re.sub(r"^(visible[_ ]*)?course[_ ]*tag\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^leading[_ ]*tag\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip()

    if not text:
        return None

    allowed_full_tags = {
        "+",
        "*",
        "P",
        "p",
        "H",
        "h",
        "HP",
        "hp",
        "Hp",
        "N",
        "n",
        "+ P",
        "+ p",
        "+ H",
        "+ h",
        "+ HP",
        "+ hp",
        "+ N",
        "+ n",
        "* P",
        "* p",
        "* H",
        "* h",
        "* HP",
        "* hp",
        "* N",
        "* n",
    }

    if text in allowed_full_tags:
        return text

    # Accept a clean combination of +/* plus one short letter prefix.
    if re.fullmatch(r"[+*]?\s*(?:P|p|H|h|HP|hp|N|n)", text):
        return text

    return None


def _row_visible_course_tag(row: dict[str, Any]) -> str | None:
    return _clean_visible_course_tag(
        _first_non_empty(
            row.get("visible_course_tag"),
            row.get("leading_tag"),
            row.get("course_tag"),
            row.get("prefix_tag"),
            row.get("left_tag"),
            row.get("row_tag"),
            row.get("tag"),
            row.get("course_id_prefix_tag"),
        )
    )


def _coerce_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        match = re.search(r"-?\d+", str(value))
        return int(match.group(0)) if match else None


def _coerce_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        text = str(value).strip()

        if "," in text and "." not in text:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

        return float(text)
    except Exception:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group(0)) if match else None


def _coerce_confidence(value: Any) -> float | None:
    confidence = _coerce_float(value)

    if confidence is None:
        return None

    if confidence < 0:
        return 0.0

    if confidence > 1:
        return 1.0

    return confidence


def _bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value in (None, ""):
        return False

    text = str(value).strip().lower()

    if text in {"true", "1", "yes", "y"}:
        return True

    if text in {"false", "0", "no", "n"}:
        return False

    return "*" in text or "+" in text


def _month_to_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value if 1 <= value <= 12 else None

    text = str(value).strip()

    numeric_match = re.search(r"\b(1[0-2]|0?[1-9])\b", text)
    if numeric_match:
        return int(numeric_match.group(1))

    month_map = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sept": 9,
        "sep": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    lower = text.lower()

    for label, number in month_map.items():
        if re.search(rf"\b{re.escape(label)}\b", lower):
            return number

    return None


def _extract_grade_level_from_text(value: Any) -> int | None:
    text = str(value or "")
    match = re.search(r"\bgrade\s*(6|7|8|9|10|11|12)\b", text, flags=re.IGNORECASE)

    if match:
        return int(match.group(1))

    return None


def _extract_term_name_from_text(value: Any) -> str | None:
    text = str(value or "")

    for term in ("Fall", "Spring", "Summer", "Winter"):
        if re.search(rf"\b{term}\b", text, flags=re.IGNORECASE):
            return term

    return None


def _extract_academic_year_from_text(value: Any) -> str | None:
    text = str(value or "")
    match = re.search(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b", text)

    if match:
        return f"{match.group(1)}-{match.group(2)}"

    return None


def _academic_year_start_year(value: Any) -> int | None:
    """
    Return the start year from an academic-year range.

    Shared Mayfair/LBUSD rule:
    - 2021-2022 -> 2021
    - 2022-2023 -> 2022
    - 2023-2024 -> 2023

    This intentionally does not use the Spring/Summer ending calendar year.
    """
    text = str(value or "")
    match = re.search(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b", text)

    if not match:
        return None

    return int(match.group(1))


def _year_to_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    text = str(value).strip()

    try:
        parsed = int(text)
        if 1900 <= parsed <= 2100:
            return parsed
    except Exception:
        pass

    match = re.search(r"\b(20\d{2})\b", text)
    if match:
        return int(match.group(1))

    return None


def _derive_year(
    *,
    explicit_year: Any,
    academic_year: str | None,
    term_name: str | None,
    section_name: str | None,
) -> int | None:
    """
    Derive the stored transcript year.

    Shared Mayfair/LBUSD rule:
    if an academic-year range is visible or derivable, store the START year
    for every term, including Spring and Summer.

    Examples:
      Fall 2021-2022   -> year=2021, month=1
      Spring 2021-2022 -> year=2021, month=6
      Summer 2021-2022 -> year=2021, month=7

    If no academic-year range exists, keep the explicit single year.
    """
    academic_year = academic_year or _extract_academic_year_from_text(section_name)
    start_year = _academic_year_start_year(academic_year)

    if start_year is not None:
        return start_year

    direct_year = _year_to_int(explicit_year)

    if direct_year is not None:
        return direct_year

    if not academic_year:
        return None

    return _year_to_int(academic_year)


def _derive_lbusd_academic_year_from_visible_year_month(
    *,
    visible_year: Any,
    month: Any,
) -> str | None:
    """
    LBUSD-style headers often show a calendar Yr plus Month.

    For saved rows, crs_year should be the academic-year START year.
    Month 1 is treated as Fall/start-year.
    Month 6 and Month 7 are treated as Spring/Summer of the academic year
    that started in the previous calendar year.

    This helper is intentionally used only when no academic_year range was
    already provided by Gemini/section text.
    """
    year = _year_to_int(visible_year)
    month_number = _month_to_int(month)

    if year is None or month_number is None:
        return None

    if month_number in {6, 7}:
        start_year = year - 1
    else:
        start_year = year

    if start_year < 1900:
        return None

    return f"{start_year}-{start_year + 1}"


def _parse_course_id_parts(course_id_raw: Any) -> dict[str, Any]:
    raw = _clean_course_id_text(course_id_raw) or ""

    has_plus_marker = "+" in raw
    has_star_marker = "*" in raw

    prefix_match = re.search(r"\b([A-Za-z]+)\b", raw)
    number_match = re.search(r"(\d+)", raw)

    return {
        "course_id_raw": raw or None,
        "has_plus_marker": has_plus_marker,
        "has_star_marker": has_star_marker,
        "course_prefix": prefix_match.group(1) if prefix_match else None,
        "course_number": number_match.group(1) if number_match else None,
    }


def _rebuild_course_id_raw_from_parts(
    *,
    has_plus_marker: bool,
    has_star_marker: bool,
    course_prefix: str | None,
    course_number: str | None,
) -> str | None:
    if not course_number:
        return None

    parts: list[str] = []

    if has_plus_marker:
        parts.append("+")

    if has_star_marker:
        parts.append("*")

    if course_prefix:
        parts.append(str(course_prefix).strip())

    parts.append(str(course_number).strip())

    return " ".join(part for part in parts if part)


def _normalize_course_name(value: Any) -> str:
    text = str(value or "").upper()
    text = text.replace("Η", "H")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = re.sub(r"[^A-Z0-9 ()/&+-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text



def _is_mayfair_text(value: Any) -> bool:
    text = _normalize_course_name(value)
    return "MAYFAIR" in text


def _infer_mayfair_month_from_term(
    *,
    term_name: Any = None,
    section_name: Any = None,
) -> int | None:
    text = " ".join(
        str(value or "")
        for value in [term_name, section_name]
        if value not in (None, "")
    )
    normalized = _normalize_course_name(text)

    if re.search(r"\bFALL\b", normalized):
        return 1

    if re.search(r"\bSPRING\b", normalized):
        return 6

    if (
        re.search(r"\bSUMMER\b", normalized)
        or re.search(r"\bINTERSESSION\b", normalized)
        or re.search(r"\bSUMMER INTERSESSION\b", normalized)
    ):
        return 7

    return None


def _repair_common_course_name_order(value: Any) -> str | None:
    course_name = _clean_text(value)

    if not course_name:
        return None

    # Conservative exact repairs for known visual-order mistakes.
    # These only run when the whole normalized title matches the broken pattern.
    normalized = _normalize_course_name(course_name)

    exact_repairs = {
        "1 2 (PLTW) INTRODUCTION TO DESIGN": "Introduction to Design 1,2 (PLTW)",
        "PLTW) HUMAN BODY SYSTEMS (": "Human Body Systems (PLTW)",
        "AND CULTURE AP SPANISH LANGUAGE": "AP Spanish Language and Culture",
        "AND CULTURE AP SPANISH LITERATURE": "AP Spanish Literature and Culture",
        "HISTORY BIG HISTORY PROJECT WORLD": "Big History Project World History",
        "ENGINEERING (PLTW) HONORS PRINCIPLES OF": "Honors Principles of Engineering (PLTW)",
        "BIOMECHANICS AND HEALTH ADVANCED KINESIOLOGY": "Advanced Kinesiology, Biomechanics and Health",
        "AND COMPOSITION AP ENGLISH LANGUAGE": "AP English Language and Composition",
        "COMPOSITION AP ENGLISH LITERATURE AND": "AP English Literature and Composition",
        "INTEGRATED MANUFACTURING (PLTW) HONORS COMPUTER": "Honors Computer Integrated Manufacturing (PLTW)",
        "POLITICS UNITED STATES AP GOVERNMENT AND": "AP Government and Politics United States",
        "PLTW) HONORS ENGINEERING DESIGN DEVELOPMENT (": "Honors Engineering Design & Development (PLTW)",
    }

    return exact_repairs.get(normalized, course_name)


def _split_known_trailing_grade_from_course_name(
    course_name: Any,
    current_grade: Any,
) -> tuple[str | None, str | None, bool]:
    """
    Repair a narrow class of OCR/Gemini row-merge mistakes where the Mark
    column was appended to the course title.

    This is intentionally conservative so normal titles are not changed. It is
    mainly for LBUSD sports/elective rows like:
      E Sprt Vid Game B -> course_name=E Sprt Vid Game, grade=B
      E Sprt AdvVGame B -> course_name=E Sprt AdvVGame, grade=B

    It does not remove normal subject suffixes like "A,B".
    """
    cleaned_name = _clean_text(course_name)
    cleaned_grade = _clean_grade_text(current_grade)

    if not cleaned_name:
        return None, cleaned_grade, False

    match = re.match(
        r"^(?P<base>.+?)\s+(?P<trailing>A[+-]?|B[+-]?|C[+-]?|D[+-]?|F|P|CR|NC|NM)$",
        cleaned_name,
        flags=re.IGNORECASE,
    )

    if not match:
        return cleaned_name, cleaned_grade, False

    base_name = _clean_text(match.group("base"))
    trailing_grade = _clean_grade_text(match.group("trailing"))

    if not base_name or not trailing_grade:
        return cleaned_name, cleaned_grade, False

    normalized_base = _normalize_course_name(base_name)

    # Keep this narrow. Do not strip grades from broad course names like
    # "MUS 104B-History A" or St. Anthony "Theology III A,B".
    known_merged_title_patterns = [
        r"\bE\s+SPRT\b",
        r"\bSPRT\b",
        r"\bSPORT\b",
        r"\bVID\s+GAME\b",
        r"\bADVV?GAME\b",
        r"\bADV\s*V\s*GAME\b",
    ]

    if not any(re.search(pattern, normalized_base) for pattern in known_merged_title_patterns):
        return cleaned_name, cleaned_grade, False

    # If the grade field is missing/invalid, use the trailing mark. If the
    # grade field is already valid, preserve it and only clean the title.
    final_grade = cleaned_grade or trailing_grade
    return base_name, final_grade, True


def _apply_mayfair_month_inference(
    raw_json: dict[str, Any],
    normalized_courses: list[dict[str, Any]],
) -> None:
    # Mayfair-only backend guard. This prevents changing LBUSD/Millikan/Sato/Jordan,
    # St. Anthony, or unknown-school month behavior.
    raw_school_values = [
        raw_json.get("school_name"),
        raw_json.get("transcript_school_name"),
        raw_json.get("high_school_name"),
        raw_json.get("transcript_format"),
        raw_json.get("detected_school"),
    ]

    is_mayfair = any(_is_mayfair_text(value) for value in raw_school_values)

    if not is_mayfair:
        is_mayfair = any(
            _is_mayfair_text(course.get("school_name"))
            or _is_mayfair_text(course.get("section_name"))
            for course in normalized_courses
        )

    if not is_mayfair:
        return

    for course in normalized_courses:
        if course.get("month") is not None:
            continue

        inferred_month = _infer_mayfair_month_from_term(
            term_name=course.get("term_name"),
            section_name=course.get("section_name"),
        )

        if inferred_month is not None:
            course["month"] = inferred_month

            raw_row = course.get("raw_gemini_row")
            if isinstance(raw_row, dict):
                raw_row["backend_mayfair_month_inferred"] = inferred_month



def _is_st_anthony_text(value: Any) -> bool:
    text = _normalize_course_name(value)
    return "ST ANTHONY" in text or "SAINT ANTHONY" in text


def _is_st_anthony_source(
    *,
    pdf_path: str | None = None,
    gcs_uri: str | None = None,
    transcript_format: str | None = None,
) -> bool:
    source_text = " ".join(
        str(value or "")
        for value in [pdf_path, gcs_uri, transcript_format]
        if value not in (None, "")
    )
    return _is_st_anthony_text(source_text)


def _is_lbusd_text(value: Any) -> bool:
    text = _normalize_course_name(value)

    lbusd_markers = [
        "LBUSD",
        "LONG BEACH UNIFIED",
        "CABRILLO",
        "MILLIKAN",
        "SATO ACADEMY",
        "SATO",
        "JORDAN HIGH",
        "JORDAN",
        "MCBRIDE",
        "WILSON",
        "AVALON",
        "LAKEWOOD",
        "CAMS",
        "YR MONTH GRADE",
        "MONTH GRADE",
    ]

    return any(marker in text for marker in lbusd_markers)


def _is_lbusd_source(
    *,
    pdf_path: str | None = None,
    gcs_uri: str | None = None,
    transcript_format: str | None = None,
) -> bool:
    source_text = " ".join(
        str(value or "")
        for value in [pdf_path, gcs_uri, transcript_format]
        if value not in (None, "")
    )
    return _is_lbusd_text(source_text)


def _is_mayfair_source(
    *,
    pdf_path: str | None = None,
    gcs_uri: str | None = None,
    transcript_format: str | None = None,
) -> bool:
    source_text = " ".join(
        str(value or "")
        for value in [pdf_path, gcs_uri, transcript_format]
        if value not in (None, "")
    )
    return _is_mayfair_text(source_text)


def _select_extraction_prompt(
    *,
    pdf_path: str | None = None,
    gcs_uri: str | None = None,
    transcript_format: str | None = None,
) -> tuple[str, str, bool, bool]:
    is_st_anthony = _is_st_anthony_source(
        pdf_path=pdf_path,
        gcs_uri=gcs_uri,
        transcript_format=transcript_format,
    )

    if is_st_anthony:
        return (
            ST_ANTHONY_COURSE_EXTRACTION_PROMPT,
            "st_anthony",
            True,
            False,
        )

    is_lbusd = _is_lbusd_source(
        pdf_path=pdf_path,
        gcs_uri=gcs_uri,
        transcript_format=transcript_format,
    )

    if is_lbusd:
        return (
            LBUSD_COURSE_EXTRACTION_PROMPT,
            "lbusd",
            False,
            True,
        )

    is_mayfair = _is_mayfair_source(
        pdf_path=pdf_path,
        gcs_uri=gcs_uri,
        transcript_format=transcript_format,
    )

    if is_mayfair:
        # Dedicated Mayfair prompt: the generic multi-school prompt leaves
        # grade/term/year/month null on Mayfair's 3-column layout, sending every
        # row to Needs Review. A focused prompt that states the school and forces
        # per-row term context from the section headers fixes that. Not flagged
        # st_anthony/lbusd, so the existing Mayfair month/year post-processing
        # still applies.
        return (
            MAYFAIR_COURSE_EXTRACTION_PROMPT,
            "mayfair",
            False,
            False,
        )

    return (
        GEMINI_COURSE_EXTRACTION_PROMPT,
        "general",
        False,
        False,
    )


def _tag_scan_enabled() -> bool:
    # Default OFF. The focused course-ID verifier is safer and evidence-only.
    # Enable only if you specifically need the older tiny-tag scan for non-LBUSD files.
    value = os.getenv("GEMINI_ENABLE_TAG_SCAN", "0").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _tag_scan_max_rows() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_TAG_SCAN_MAX_ROWS", "90")))
    except Exception:
        return 90



def _course_id_scan_enabled() -> bool:
    # Evidence-only verifier. It does not overwrite the main Gemini extraction.
    # Reconciliation decides whether to keep Doc AI, use Gemini, or send Needs Review.
    value = os.getenv("GEMINI_ENABLE_COURSE_ID_SCAN", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _course_id_scan_max_rows() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_COURSE_ID_SCAN_MAX_ROWS", "100")))
    except Exception:
        return 100


def _course_id_scan_min_apply_score() -> float:
    try:
        return max(1.0, float(os.getenv("GEMINI_COURSE_ID_SCAN_MIN_APPLY_SCORE", "5.0")))
    except Exception:
        return 5.0


def _course_id_scan_min_confidence() -> float:
    try:
        return max(0.0, min(float(os.getenv("GEMINI_COURSE_ID_SCAN_MIN_CONFIDENCE", "0.85")), 1.0))
    except Exception:
        return 0.85


def _grade_scan_enabled() -> bool:
    # Evidence-only verifier is safe to run by default because it does not
    # overwrite Gemini main extraction grades. Set GEMINI_ENABLE_GRADE_SCAN=0
    # to disable the extra Gemini verifier call.
    value = os.getenv("GEMINI_ENABLE_GRADE_SCAN", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _grade_scan_max_rows() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_GRADE_SCAN_MAX_ROWS", "100")))
    except Exception:
        return 100


def _grade_scan_min_apply_score() -> float:
    try:
        return max(1.0, float(os.getenv("GEMINI_GRADE_SCAN_MIN_APPLY_SCORE", "5.0")))
    except Exception:
        return 5.0


def _grade_scan_min_confidence() -> float:
    try:
        return max(0.0, min(float(os.getenv("GEMINI_GRADE_SCAN_MIN_CONFIDENCE", "0.90")), 1.0))
    except Exception:
        return 0.90


def _grade_scan_overwrite_main_grade_enabled() -> bool:
    # Keep OFF. The grade scan is verifier evidence only unless the separate
    # safe-apply rule below proves the verifier row identity is very strong.
    # Reconciliation still remains the final judge for risky conflicts.
    value = os.getenv("GEMINI_GRADE_SCAN_OVERWRITE_MAIN_GRADE", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _grade_scan_safe_apply_to_main_enabled() -> bool:
    # Default ON for high-confidence, high-match-score verifier corrections.
    # This fixes LBUSD rows where the main pass reads B/C as A while the focused
    # Mark-column pass proves the same visual row.
    value = os.getenv("GEMINI_GRADE_SCAN_SAFE_APPLY_TO_MAIN", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _grade_scan_safe_apply_min_score() -> float:
    try:
        return max(1.0, float(os.getenv("GEMINI_GRADE_SCAN_SAFE_APPLY_MIN_SCORE", "9.0")))
    except Exception:
        return 9.0


def _grade_scan_safe_apply_min_confidence() -> float:
    try:
        return max(0.0, min(float(os.getenv("GEMINI_GRADE_SCAN_SAFE_APPLY_MIN_CONFIDENCE", "0.95")), 1.0))
    except Exception:
        return 0.95



def _optional_scan_worker_count() -> int:
    try:
        return max(1, min(3, int(os.getenv("GEMINI_OPTIONAL_SCAN_WORKERS", "3"))))
    except Exception:
        return 3


def _optional_scans_parallel_enabled() -> bool:
    value = os.getenv("GEMINI_OPTIONAL_SCANS_PARALLEL", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _generate_json_with_new_client(
    *,
    model_name: str,
    pdf_part: Any,
    prompt: str,
) -> tuple[dict[str, Any], str]:
    # Use one client per worker so optional verifier calls can safely run in
    # parallel without sharing the same genai.Client across threads.
    worker_client = _make_gemini_client()
    return _generate_json_with_gemini(
        worker_client,
        model_name=model_name,
        pdf_part=pdf_part,
        prompt=prompt,
    )


def _should_run_tag_scan(
    courses: list[dict[str, Any]],
    *,
    is_st_anthony: bool,
    is_lbusd: bool = False,
) -> bool:
    # Never run the older tag scan on LBUSD-style transcripts. It can add bad
    # +/* markers. The course-ID verifier is safer because it is evidence-only.
    if is_st_anthony or is_lbusd or not _tag_scan_enabled() or not courses:
        return False

    if len(courses) > _tag_scan_max_rows():
        return False

    return any(course.get("course_number") for course in courses)


def _tag_scan_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("tag_rows", "rows", "course_tags", "course_id_tags"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for container_key in ("data", "result", "extraction"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue

        for key in ("tag_rows", "rows", "course_tags", "course_id_tags"):
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _normalize_tag_scan_row(row: dict[str, Any]) -> dict[str, Any] | None:
    visible_course_tag = _clean_visible_course_tag(
        _first_non_empty(
            row.get("visible_course_tag"),
            row.get("leading_tag"),
            row.get("course_tag"),
            row.get("prefix_tag"),
            row.get("left_tag"),
            row.get("row_tag"),
            row.get("tag"),
        )
    )

    course_number = _clean_text(
        _first_non_empty(
            row.get("course_number"),
            row.get("number"),
            row.get("crs_number"),
            row.get("course_id"),
            row.get("crs_id"),
        )
    )

    if course_number:
        number_match = re.search(r"\d+", course_number)
        course_number = number_match.group(0) if number_match else None

    if not course_number:
        return None

    course_id_raw = _clean_course_id_text(row.get("course_id_raw"))
    tag_parts = _parse_course_id_parts(visible_course_tag)
    id_parts = _parse_course_id_parts(course_id_raw)

    has_plus_marker = tag_parts["has_plus_marker"] or id_parts["has_plus_marker"]
    has_star_marker = tag_parts["has_star_marker"] or id_parts["has_star_marker"]
    course_prefix = tag_parts["course_prefix"] or id_parts["course_prefix"]

    if not course_id_raw and visible_course_tag:
        course_id_raw = _rebuild_course_id_raw_from_parts(
            has_plus_marker=has_plus_marker,
            has_star_marker=has_star_marker,
            course_prefix=course_prefix,
            course_number=course_number,
        )

    return {
        "row_index": _coerce_int(row.get("row_index")),
        "section_name": _clean_text(row.get("section_name")),
        "course_number": course_number,
        "course_name": _clean_text(
            _first_non_empty(
                row.get("course_name"),
                row.get("course_title"),
                row.get("name"),
                row.get("title"),
            )
        ),
        "visible_course_tag": visible_course_tag,
        "course_id_raw": course_id_raw,
        "has_plus_marker": has_plus_marker,
        "has_star_marker": has_star_marker,
        "course_prefix": course_prefix,
        "tag_confidence": _coerce_confidence(
            _first_non_empty(
                row.get("tag_confidence"),
                row.get("confidence"),
                row.get("extraction_confidence"),
            )
        ),
        "raw_tag_row": row,
    }


def _name_overlap_score(left: Any, right: Any) -> float:
    left_tokens = set(_normalize_course_name(left).split())
    right_tokens = set(_normalize_course_name(right).split())

    if not left_tokens or not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)


def _course_tag_merge_score(
    course: dict[str, Any],
    tag_row: dict[str, Any],
) -> float:
    if str(course.get("course_number") or "") != str(tag_row.get("course_number") or ""):
        return -1.0

    score = 1.0

    course_row_index = _coerce_int(course.get("row_index"))
    tag_row_index = _coerce_int(tag_row.get("row_index"))

    if course_row_index is not None and tag_row_index is not None:
        distance = abs(course_row_index - tag_row_index)
        if distance == 0:
            score += 3.0
        elif distance == 1:
            score += 1.0
        else:
            score -= min(distance, 5) * 0.35

    if course.get("section_name") and tag_row.get("section_name"):
        if _normalize_course_name(course.get("section_name")) == _normalize_course_name(tag_row.get("section_name")):
            score += 1.0

    score += _name_overlap_score(course.get("course_name"), tag_row.get("course_name"))
    return score


def _apply_tag_scan_results(
    courses: list[dict[str, Any]],
    tag_scan_json: dict[str, Any],
) -> tuple[int, list[str]]:
    warnings: list[str] = []
    raw_tag_rows = _tag_scan_rows(tag_scan_json)
    tag_rows: list[dict[str, Any]] = []

    for raw_row in raw_tag_rows:
        normalized = _normalize_tag_scan_row(raw_row)
        if normalized:
            tag_rows.append(normalized)

    if not tag_rows:
        return 0, warnings

    used_course_indexes: set[int] = set()
    candidate_pairs: list[tuple[float, int, int]] = []

    for tag_index, tag_row in enumerate(tag_rows):
        if not tag_row.get("visible_course_tag") and not tag_row.get("course_id_raw"):
            continue

        for course_index, course in enumerate(courses):
            score = _course_tag_merge_score(course, tag_row)
            if score >= 1.0:
                candidate_pairs.append((score, tag_index, course_index))

    candidate_pairs.sort(reverse=True, key=lambda item: item[0])

    applied_count = 0

    for _score, tag_index, course_index in candidate_pairs:
        if course_index in used_course_indexes:
            continue

        tag_row = tag_rows[tag_index]
        course = courses[course_index]

        visible_course_tag = tag_row.get("visible_course_tag")
        tag_course_id_raw = tag_row.get("course_id_raw")

        if not visible_course_tag and not tag_course_id_raw:
            continue

        existing_parts = _parse_course_id_parts(course.get("course_id_raw"))
        tag_parts = _parse_course_id_parts(tag_course_id_raw or visible_course_tag)

        final_has_plus_marker = (
            bool(course.get("has_plus_marker"))
            or existing_parts["has_plus_marker"]
            or bool(tag_row.get("has_plus_marker"))
            or tag_parts["has_plus_marker"]
        )
        final_has_star_marker = (
            bool(course.get("has_star_marker"))
            or existing_parts["has_star_marker"]
            or bool(tag_row.get("has_star_marker"))
            or tag_parts["has_star_marker"]
        )
        final_course_prefix = (
            tag_row.get("course_prefix")
            or tag_parts["course_prefix"]
            or course.get("course_prefix")
            or existing_parts["course_prefix"]
        )
        final_course_number = (
            course.get("course_number")
            or existing_parts["course_number"]
            or tag_row.get("course_number")
            or tag_parts["course_number"]
        )

        rebuilt_course_id_raw = _rebuild_course_id_raw_from_parts(
            has_plus_marker=bool(final_has_plus_marker),
            has_star_marker=bool(final_has_star_marker),
            course_prefix=final_course_prefix,
            course_number=final_course_number,
        )

        if not rebuilt_course_id_raw:
            continue

        before = course.get("course_id_raw")

        course["visible_course_tag"] = visible_course_tag or course.get("visible_course_tag")
        course["course_id_raw"] = rebuilt_course_id_raw
        course["has_plus_marker"] = bool(final_has_plus_marker)
        course["has_star_marker"] = bool(final_has_star_marker)
        course["course_prefix"] = final_course_prefix
        course["course_number"] = final_course_number

        raw_gemini_row = course.get("raw_gemini_row")
        if isinstance(raw_gemini_row, dict):
            raw_gemini_row["backend_tag_scan_applied"] = True
            raw_gemini_row["backend_tag_scan_before_course_id_raw"] = before
            raw_gemini_row["backend_tag_scan_course_id_raw"] = rebuilt_course_id_raw
            raw_gemini_row["backend_tag_scan_visible_course_tag"] = visible_course_tag
            raw_gemini_row["backend_tag_scan_row"] = tag_row.get("raw_tag_row")

        used_course_indexes.add(course_index)
        applied_count += 1

    return applied_count, warnings



def _should_run_course_id_scan(
    courses: list[dict[str, Any]],
    *,
    is_st_anthony: bool,
) -> bool:
    if is_st_anthony or not _course_id_scan_enabled() or not courses:
        return False

    if len(courses) > _course_id_scan_max_rows():
        return False

    return True


def _course_id_scan_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("course_id_rows", "rows", "course_ids", "course_id_data"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for container_key in ("data", "result", "extraction"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue

        for key in ("course_id_rows", "rows", "course_ids", "course_id_data"):
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _normalize_course_id_scan_row(row: dict[str, Any]) -> dict[str, Any] | None:
    visible_course_tag = _row_visible_course_tag(row)

    has_plus_marker = _bool_from_value(row.get("has_plus_marker"))
    has_star_marker = _bool_from_value(row.get("has_star_marker"))

    course_prefix = _clean_text(
        _first_non_empty(
            row.get("course_prefix"),
            row.get("prefix"),
        )
    )

    course_number = _clean_text(
        _first_non_empty(
            row.get("course_number"),
            row.get("number"),
            row.get("crs_number"),
        )
    )

    course_id_raw = _clean_course_id_text(
        _first_non_empty(
            row.get("course_id_raw"),
            row.get("crs_id_raw"),
            row.get("course_id"),
            row.get("crs_id"),
            row.get("local_course_id"),
        )
    )

    visible_tag_parts = _parse_course_id_parts(visible_course_tag)
    id_parts = _parse_course_id_parts(course_id_raw)

    final_has_plus_marker = (
        has_plus_marker
        or id_parts["has_plus_marker"]
        or visible_tag_parts["has_plus_marker"]
    )
    final_has_star_marker = (
        has_star_marker
        or id_parts["has_star_marker"]
        or visible_tag_parts["has_star_marker"]
    )
    final_course_prefix = (
        course_prefix
        or id_parts["course_prefix"]
        or visible_tag_parts["course_prefix"]
    )
    final_course_number = (
        course_number
        or id_parts["course_number"]
        or visible_tag_parts["course_number"]
    )

    if final_course_number:
        number_match = re.search(r"\d+", str(final_course_number))
        final_course_number = number_match.group(0) if number_match else final_course_number

    if not course_id_raw:
        course_id_raw = _rebuild_course_id_raw_from_parts(
            has_plus_marker=final_has_plus_marker,
            has_star_marker=final_has_star_marker,
            course_prefix=final_course_prefix,
            course_number=final_course_number,
        )

    if not course_id_raw and not final_course_number:
        return None

    return {
        "row_index": _coerce_int(row.get("row_index")),
        "block_index": _coerce_int(row.get("block_index")),
        "row_in_block": _coerce_int(row.get("row_in_block")),
        "section_name": _clean_text(row.get("section_name")),
        "year": _derive_year(
            explicit_year=_first_non_empty(row.get("year"), row.get("crs_year"), row.get("school_year")),
            academic_year=_clean_text(row.get("academic_year")),
            term_name=_clean_text(row.get("term_name")),
            section_name=_clean_text(row.get("section_name")),
        ),
        "month": _month_to_int(_first_non_empty(row.get("month"), row.get("crs_month"), row.get("month_number"), row.get("month_name"))),
        "grade_level": _coerce_int(_first_non_empty(row.get("grade_level"), row.get("grade_year"), row.get("crs_grade"))),
        "course_id_raw": course_id_raw,
        "visible_course_tag": visible_course_tag,
        "has_plus_marker": final_has_plus_marker,
        "has_star_marker": final_has_star_marker,
        "course_prefix": final_course_prefix,
        "course_number": final_course_number,
        "course_name": _clean_text(_first_non_empty(row.get("course_name"), row.get("course_title"), row.get("name"), row.get("title"))),
        "grade": _clean_grade_text(_first_non_empty(row.get("grade"), row.get("mark"), row.get("course_mark"), row.get("crs_letter_grade"))),
        "credit_attempted": _coerce_float(_first_non_empty(row.get("credit_attempted"), row.get("credits_attempted"), row.get("att"), row.get("attempted"), row.get("credits"))),
        "credit_completed": _coerce_float(_first_non_empty(row.get("credit_completed"), row.get("credits_completed"), row.get("cmp"), row.get("completed"), row.get("credits"))),
        "course_id_confidence": _coerce_confidence(_first_non_empty(row.get("course_id_confidence"), row.get("confidence"), row.get("extraction_confidence"))),
        "raw_course_id_row": row,
    }


def _normalize_course_id_for_compare(value: Any) -> str:
    if value in (None, ""):
        return ""

    text = str(value).upper().strip()
    text = text.replace("＊", "*")
    text = text.replace("﹡", "*")
    text = text.replace("⁎", "*")
    text = text.replace("∗", "*")
    text = text.replace("✱", "*")
    text = text.replace("＋", "+")
    text = text.replace("﹢", "+")
    text = re.sub(r"[^A-Z0-9+*]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _course_id_values_equal(left: Any, right: Any) -> bool:
    return bool(
        _normalize_course_id_for_compare(left)
        and _normalize_course_id_for_compare(left) == _normalize_course_id_for_compare(right)
    )


def _course_id_scan_safe_apply_same_number_tags_enabled() -> bool:
    # Safe default ON: this only enriches the main Gemini row when the verifier
    # sees the same numeric course ID plus a missing visible tag/prefix.
    # It does not apply digit-changing Course ID corrections.
    value = os.getenv("GEMINI_COURSE_ID_SCAN_APPLY_SAME_NUMBER_TAGS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _course_id_scan_same_number_tag_apply_min_score() -> float:
    try:
        return max(1.0, float(os.getenv("GEMINI_COURSE_ID_SCAN_SAME_NUMBER_TAG_MIN_SCORE", "6.0")))
    except Exception:
        return 6.0


def _course_id_scan_same_number_tag_apply_min_confidence() -> float:
    try:
        return max(0.0, min(float(os.getenv("GEMINI_COURSE_ID_SCAN_SAME_NUMBER_TAG_MIN_CONFIDENCE", "0.90")), 1.0))
    except Exception:
        return 0.90


def _course_id_scan_is_same_number_tag_enrichment(
    before_course_id_raw: Any,
    scan_course_id_raw: Any,
) -> bool:
    # Numeric-only course IDs are valid. This function returns True only when
    # the verifier sees the SAME numeric course number plus an actually visible
    # tag/prefix that the main extraction missed. It never adds a tag when the
    # verifier also sees a numeric-only row.
    before_parts = _parse_course_id_parts(before_course_id_raw)
    scan_parts = _parse_course_id_parts(scan_course_id_raw)

    before_number = before_parts.get("course_number")
    scan_number = scan_parts.get("course_number")

    if not before_number or not scan_number or before_number != scan_number:
        return False

    before_has_tag = bool(
        before_parts.get("has_plus_marker")
        or before_parts.get("has_star_marker")
        or before_parts.get("course_prefix")
    )
    scan_has_tag = bool(
        scan_parts.get("has_plus_marker")
        or scan_parts.get("has_star_marker")
        or scan_parts.get("course_prefix")
    )

    if not scan_has_tag:
        return False

    if not before_has_tag:
        return True

    # Also allow prefix enrichment such as H -> HP when the verifier sees the
    # longer exact same-row prefix and the numeric ID is unchanged.
    before_prefix = str(before_parts.get("course_prefix") or "").strip().upper()
    scan_prefix = str(scan_parts.get("course_prefix") or "").strip().upper()

    return bool(scan_prefix and before_prefix and scan_prefix != before_prefix and before_prefix in scan_prefix)


def _apply_same_number_course_id_tag_enrichment(
    course: dict[str, Any],
    course_id_row: dict[str, Any],
    *,
    scan_course_id_raw: str,
    score: float,
    confidence: float | None,
) -> bool:
    if not _course_id_scan_safe_apply_same_number_tags_enabled():
        return False

    if confidence is not None and confidence < _course_id_scan_same_number_tag_apply_min_confidence():
        return False

    if score < _course_id_scan_same_number_tag_apply_min_score():
        return False

    before_course_id_raw = _clean_course_id_text(course.get("course_id_raw"))

    if not _course_id_scan_is_same_number_tag_enrichment(before_course_id_raw, scan_course_id_raw):
        return False

    scan_parts = _parse_course_id_parts(scan_course_id_raw)
    visible_course_tag = _row_visible_course_tag(course_id_row)

    course["course_id_raw"] = scan_course_id_raw
    course["visible_course_tag"] = visible_course_tag or course.get("visible_course_tag")
    course["has_plus_marker"] = bool(scan_parts.get("has_plus_marker"))
    course["has_star_marker"] = bool(scan_parts.get("has_star_marker"))
    course["course_prefix"] = scan_parts.get("course_prefix")
    course["course_number"] = scan_parts.get("course_number") or course.get("course_number")
    course["course_id_scan_applied_to_main"] = True

    raw_gemini_row = course.get("raw_gemini_row")
    if isinstance(raw_gemini_row, dict):
        raw_gemini_row["backend_course_id_scan_applied_to_main"] = True
        raw_gemini_row["backend_course_id_scan_apply_reason"] = "same_number_visible_tag_enrichment"
        raw_gemini_row["backend_course_id_scan_before_main_course_id_raw"] = before_course_id_raw
        raw_gemini_row["backend_course_id_raw"] = scan_course_id_raw
        raw_gemini_row["backend_visible_course_tag"] = course.get("visible_course_tag")
        raw_gemini_row["backend_course_prefix"] = course.get("course_prefix")
        raw_gemini_row["backend_course_number"] = course.get("course_number")
        raw_gemini_row["backend_has_plus_marker"] = course.get("has_plus_marker")
        raw_gemini_row["backend_has_star_marker"] = course.get("has_star_marker")

    return True


def _course_id_scan_merge_score(course: dict[str, Any], course_id_row: dict[str, Any]) -> float:
    score = 0.0

    course_row_index = _coerce_int(course.get("row_index"))
    scan_row_index = _coerce_int(course_id_row.get("row_index"))

    if course_row_index is not None and scan_row_index is not None:
        distance = abs(course_row_index - scan_row_index)
        if distance == 0:
            score += 4.0
        elif distance == 1:
            score += 1.0
        else:
            score -= min(distance, 8) * 0.40

    course_block_index = _coerce_int(course.get("block_index"))
    scan_block_index = _coerce_int(course_id_row.get("block_index"))

    if course_block_index is not None and scan_block_index is not None:
        if course_block_index == scan_block_index:
            score += 2.0
        else:
            return -1.0

    course_row_in_block = _coerce_int(course.get("row_in_block"))
    scan_row_in_block = _coerce_int(course_id_row.get("row_in_block"))

    if course_row_in_block is not None and scan_row_in_block is not None:
        if course_row_in_block == scan_row_in_block:
            score += 2.0
        else:
            score -= min(abs(course_row_in_block - scan_row_in_block), 5) * 0.50

    if course.get("section_name") and course_id_row.get("section_name"):
        if _same_clean_text(course.get("section_name"), course_id_row.get("section_name")):
            score += 1.5

    if course.get("year") is not None and course_id_row.get("year") is not None:
        if _coerce_int(course.get("year")) == _coerce_int(course_id_row.get("year")):
            score += 1.0
        else:
            return -1.0

    if course.get("month") is not None and course_id_row.get("month") is not None:
        if _month_to_int(course.get("month")) == _month_to_int(course_id_row.get("month")):
            score += 1.0
        else:
            return -1.0

    if course.get("grade_level") is not None and course_id_row.get("grade_level") is not None:
        if _coerce_int(course.get("grade_level")) == _coerce_int(course_id_row.get("grade_level")):
            score += 1.0
        else:
            score -= 0.75

    score += _name_overlap_score(course.get("course_name"), course_id_row.get("course_name"))

    if course.get("grade") and course_id_row.get("grade"):
        if _grade_values_equal(course.get("grade"), course_id_row.get("grade")):
            score += 0.5

    if course.get("credit_completed") is not None and course_id_row.get("credit_completed") is not None:
        if abs(float(course.get("credit_completed")) - float(course_id_row.get("credit_completed"))) < 0.001:
            score += 0.5

    if course.get("credit_attempted") is not None and course_id_row.get("credit_attempted") is not None:
        if abs(float(course.get("credit_attempted")) - float(course_id_row.get("credit_attempted"))) < 0.001:
            score += 0.5

    # Same course number is helpful, but a different course number must not
    # reject the match because this verifier exists to catch wrong course IDs.
    course_number = str(course.get("course_number") or "")
    scan_number = str(course_id_row.get("course_number") or "")

    if course_number and scan_number and course_number == scan_number:
        score += 0.5

    return score


def _apply_course_id_scan_results(
    courses: list[dict[str, Any]],
    course_id_scan_json: dict[str, Any],
) -> tuple[int, int, list[str]]:
    warnings: list[str] = []
    raw_course_id_rows = _course_id_scan_rows(course_id_scan_json)
    course_id_rows: list[dict[str, Any]] = []

    for raw_row in raw_course_id_rows:
        normalized = _normalize_course_id_scan_row(raw_row)
        if normalized:
            course_id_rows.append(normalized)

    if not course_id_rows:
        return 0, 0, warnings

    used_course_indexes: set[int] = set()
    candidate_pairs: list[tuple[float, int, int]] = []

    for scan_index, course_id_row in enumerate(course_id_rows):
        confidence = course_id_row.get("course_id_confidence")
        if confidence is not None and confidence < _course_id_scan_min_confidence():
            continue

        for course_index, course in enumerate(courses):
            score = _course_id_scan_merge_score(course, course_id_row)

            if score >= _course_id_scan_min_apply_score():
                candidate_pairs.append((score, scan_index, course_index))

    candidate_pairs.sort(reverse=True, key=lambda item: item[0])

    applied_count = 0
    disagreement_count = 0

    for score, scan_index, course_index in candidate_pairs:
        if course_index in used_course_indexes:
            continue

        course_id_row = course_id_rows[scan_index]
        course = courses[course_index]
        scan_course_id_raw = course_id_row.get("course_id_raw")

        if not scan_course_id_raw:
            continue

        before_course_id_raw = _clean_course_id_text(course.get("course_id_raw"))
        confidence = course_id_row.get("course_id_confidence")
        agrees_with_main = _course_id_values_equal(before_course_id_raw, scan_course_id_raw)

        course["course_id_scan_course_id_raw"] = scan_course_id_raw
        course["course_id_scan_confidence"] = confidence
        course["course_id_scan_match_score"] = round(score, 3)
        course["course_id_scan_agrees_with_main"] = agrees_with_main

        raw_gemini_row = course.get("raw_gemini_row")
        if isinstance(raw_gemini_row, dict):
            raw_gemini_row["backend_course_id_scan_applied"] = True
            raw_gemini_row["backend_course_id_scan_before_course_id_raw"] = before_course_id_raw
            raw_gemini_row["backend_course_id_scan_course_id"] = scan_course_id_raw
            raw_gemini_row["backend_course_id_scan_confidence"] = confidence
            raw_gemini_row["backend_course_id_scan_match_score"] = round(score, 3)
            raw_gemini_row["backend_course_id_scan_agrees_with_main"] = agrees_with_main
            raw_gemini_row["backend_course_id_scan_row"] = course_id_row.get("raw_course_id_row")
            raw_gemini_row["backend_course_id_scan_evidence_only"] = True

        applied_to_main = False

        if not agrees_with_main:
            applied_to_main = _apply_same_number_course_id_tag_enrichment(
                course,
                course_id_row,
                scan_course_id_raw=scan_course_id_raw,
                score=score,
                confidence=confidence,
            )

            if applied_to_main:
                # Recompute after safe tag/prefix enrichment so warnings remain
                # meaningful for true digit-changing disagreements only.
                agrees_with_main = _course_id_values_equal(
                    course.get("course_id_raw"),
                    scan_course_id_raw,
                )

        if not agrees_with_main:
            disagreement_count += 1
            warnings.append(
                f"Gemini Course ID verifier evidence disagrees on row {course.get('row_index')}: "
                f"main={before_course_id_raw or 'missing'}, verifier={scan_course_id_raw}, "
                f"confidence={confidence}, match_score={round(score, 3)}."
            )
        elif applied_to_main:
            warnings.append(
                f"Gemini Course ID verifier safely enriched row {course.get('row_index')} "
                f"from {before_course_id_raw or 'missing'} to {scan_course_id_raw}."
            )

        used_course_indexes.add(course_index)
        applied_count += 1

    return applied_count, disagreement_count, warnings


def _should_run_grade_scan(courses: list[dict[str, Any]]) -> bool:
    if not _grade_scan_enabled() or not courses:
        return False

    if len(courses) > _grade_scan_max_rows():
        return False

    return True


def _clean_grade_text(value: Any) -> str | None:
    text = _clean_text(value)

    if not text:
        return None

    text = text.strip().upper()

    # DR is not a valid grade in these transcripts. When OCR/Gemini emits DR,
    # it is usually the printed grade D with a nearby artifact. Do not convert
    # DR to CR; CR is valid only when CR is explicitly read.
    if text in {"DR", "D R", "D/R"}:
        return "D"

    match = re.search(r"\b(A[+-]?|B[+-]?|C[+-]?|D[+-]?|F|P|NP|CR|NC|NM|I|W)\b", text)

    if match:
        return match.group(1)

    return text if len(text) <= 4 else None


def _grade_values_equal(left: Any, right: Any) -> bool:
    return (_clean_grade_text(left) or "") == (_clean_grade_text(right) or "")


def _grade_scan_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("grade_rows", "rows", "course_grades", "grade_data"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for container_key in ("data", "result", "extraction"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue

        for key in ("grade_rows", "rows", "course_grades", "grade_data"):
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _normalize_grade_scan_row(row: dict[str, Any]) -> dict[str, Any] | None:
    grade = _clean_grade_text(
        _first_non_empty(
            row.get("grade"),
            row.get("mark"),
            row.get("course_mark"),
            row.get("crs_letter_grade"),
        )
    )

    if not grade:
        return None

    course_id_raw = _clean_course_id_text(
        _first_non_empty(
            row.get("course_id_raw"),
            row.get("crs_id_raw"),
            row.get("course_id"),
            row.get("crs_id"),
        )
    )
    id_parts = _parse_course_id_parts(course_id_raw)

    course_number = _clean_text(
        _first_non_empty(
            row.get("course_number"),
            row.get("number"),
            id_parts.get("course_number"),
        )
    )

    if course_number:
        number_match = re.search(r"\d+", course_number)
        course_number = number_match.group(0) if number_match else None

    return {
        "row_index": _coerce_int(row.get("row_index")),
        "block_index": _coerce_int(row.get("block_index")),
        "row_in_block": _coerce_int(row.get("row_in_block")),
        "section_name": _clean_text(row.get("section_name")),
        "year": _derive_year(
            explicit_year=_first_non_empty(row.get("year"), row.get("crs_year"), row.get("school_year")),
            academic_year=_clean_text(row.get("academic_year")),
            term_name=_clean_text(row.get("term_name")),
            section_name=_clean_text(row.get("section_name")),
        ),
        "month": _month_to_int(_first_non_empty(row.get("month"), row.get("crs_month"), row.get("month_number"), row.get("month_name"))),
        "grade_level": _coerce_int(_first_non_empty(row.get("grade_level"), row.get("grade_year"), row.get("crs_grade"))),
        "course_id_raw": course_id_raw,
        "course_number": course_number,
        "course_name": _clean_text(_first_non_empty(row.get("course_name"), row.get("course_title"), row.get("name"), row.get("title"))),
        "grade": grade,
        "credit_attempted": _coerce_float(_first_non_empty(row.get("credit_attempted"), row.get("credits_attempted"), row.get("att"), row.get("attempted"), row.get("credits"))),
        "credit_completed": _coerce_float(_first_non_empty(row.get("credit_completed"), row.get("credits_completed"), row.get("cmp"), row.get("completed"), row.get("credits"))),
        "grade_confidence": _coerce_confidence(_first_non_empty(row.get("grade_confidence"), row.get("confidence"), row.get("extraction_confidence"))),
        "raw_grade_row": row,
    }


def _same_clean_text(left: Any, right: Any) -> bool:
    left_text = _normalize_course_name(left)
    right_text = _normalize_course_name(right)
    return bool(left_text and right_text and left_text == right_text)


def _course_grade_scan_merge_score(course: dict[str, Any], grade_row: dict[str, Any]) -> float:
    score = 0.0

    course_number = str(course.get("course_number") or "")
    grade_course_number = str(grade_row.get("course_number") or "")

    if course_number and grade_course_number:
        if course_number != grade_course_number:
            return -1.0
        score += 2.0

    course_row_index = _coerce_int(course.get("row_index"))
    grade_row_index = _coerce_int(grade_row.get("row_index"))

    if course_row_index is not None and grade_row_index is not None:
        distance = abs(course_row_index - grade_row_index)
        if distance == 0:
            score += 4.0
        elif distance == 1:
            score += 1.0
        else:
            score -= min(distance, 8) * 0.40

    course_block_index = _coerce_int(course.get("block_index"))
    grade_block_index = _coerce_int(grade_row.get("block_index"))

    if course_block_index is not None and grade_block_index is not None:
        if course_block_index == grade_block_index:
            score += 2.0
        else:
            return -1.0

    course_row_in_block = _coerce_int(course.get("row_in_block"))
    grade_row_in_block = _coerce_int(grade_row.get("row_in_block"))

    if course_row_in_block is not None and grade_row_in_block is not None:
        if course_row_in_block == grade_row_in_block:
            score += 2.0
        else:
            score -= min(abs(course_row_in_block - grade_row_in_block), 5) * 0.50

    if course.get("section_name") and grade_row.get("section_name"):
        if _same_clean_text(course.get("section_name"), grade_row.get("section_name")):
            score += 1.5

    if course.get("year") is not None and grade_row.get("year") is not None:
        if _coerce_int(course.get("year")) == _coerce_int(grade_row.get("year")):
            score += 1.0
        else:
            return -1.0

    if course.get("month") is not None and grade_row.get("month") is not None:
        if _month_to_int(course.get("month")) == _month_to_int(grade_row.get("month")):
            score += 1.0
        else:
            return -1.0

    if course.get("grade_level") is not None and grade_row.get("grade_level") is not None:
        if _coerce_int(course.get("grade_level")) == _coerce_int(grade_row.get("grade_level")):
            score += 1.0
        else:
            score -= 0.75

    if course.get("course_id_raw") and grade_row.get("course_id_raw"):
        if _same_clean_text(course.get("course_id_raw"), grade_row.get("course_id_raw")):
            score += 1.5

    score += _name_overlap_score(course.get("course_name"), grade_row.get("course_name"))

    if course.get("credit_completed") is not None and grade_row.get("credit_completed") is not None:
        if abs(float(course.get("credit_completed")) - float(grade_row.get("credit_completed"))) < 0.001:
            score += 0.5

    if course.get("credit_attempted") is not None and grade_row.get("credit_attempted") is not None:
        if abs(float(course.get("credit_attempted")) - float(grade_row.get("credit_attempted"))) < 0.001:
            score += 0.5

    return score


def _grade_scan_can_safely_update_main_grade(
    *,
    score: float,
    confidence: float | None,
    before_grade: Any,
    grade_scan_grade: Any,
) -> bool:
    if not _grade_scan_safe_apply_to_main_enabled():
        return False

    if confidence is None or confidence < _grade_scan_safe_apply_min_confidence():
        return False

    if score < _grade_scan_safe_apply_min_score():
        return False

    before_clean = _clean_grade_text(before_grade)
    scan_clean = _clean_grade_text(grade_scan_grade)

    if not scan_clean or before_clean == scan_clean:
        return False

    return True


def _apply_grade_scan_results(courses: list[dict[str, Any]], grade_scan_json: dict[str, Any]) -> tuple[int, int, list[str]]:
    warnings: list[str] = []
    raw_grade_rows = _grade_scan_rows(grade_scan_json)
    grade_rows: list[dict[str, Any]] = []

    for raw_row in raw_grade_rows:
        normalized = _normalize_grade_scan_row(raw_row)
        if normalized:
            grade_rows.append(normalized)

    if not grade_rows:
        return 0, 0, warnings

    used_course_indexes: set[int] = set()
    candidate_pairs: list[tuple[float, int, int]] = []

    for grade_index, grade_row in enumerate(grade_rows):
        grade_confidence = grade_row.get("grade_confidence")
        if grade_confidence is not None and grade_confidence < _grade_scan_min_confidence():
            continue

        for course_index, course in enumerate(courses):
            score = _course_grade_scan_merge_score(course, grade_row)

            if score >= _grade_scan_min_apply_score():
                candidate_pairs.append((score, grade_index, course_index))

    candidate_pairs.sort(reverse=True, key=lambda item: item[0])

    applied_count = 0
    disagreement_count = 0
    direct_overwrite_enabled = _grade_scan_overwrite_main_grade_enabled()

    for score, grade_index, course_index in candidate_pairs:
        if course_index in used_course_indexes:
            continue

        grade_row = grade_rows[grade_index]
        course = courses[course_index]
        grade_scan_grade = grade_row.get("grade")

        if not grade_scan_grade:
            continue

        before_grade = _clean_grade_text(course.get("grade"))
        grade_scan_confidence = grade_row.get("grade_confidence")
        agrees_with_main = _grade_values_equal(before_grade, grade_scan_grade)

        course["grade_scan_grade"] = grade_scan_grade
        course["grade_scan_confidence"] = grade_scan_confidence
        course["grade_scan_match_score"] = round(score, 3)
        course["grade_scan_agrees_with_main"] = agrees_with_main

        raw_gemini_row = course.get("raw_gemini_row")
        if isinstance(raw_gemini_row, dict):
            raw_gemini_row["backend_grade_scan_applied"] = True
            raw_gemini_row["backend_grade_scan_before_grade"] = before_grade
            raw_gemini_row["backend_grade_scan_grade"] = grade_scan_grade
            raw_gemini_row["backend_grade_scan_confidence"] = grade_scan_confidence
            raw_gemini_row["backend_grade_scan_match_score"] = round(score, 3)
            raw_gemini_row["backend_grade_scan_agrees_with_main"] = agrees_with_main
            raw_gemini_row["backend_grade_scan_row"] = grade_row.get("raw_grade_row")
            raw_gemini_row["backend_grade_scan_evidence_only"] = not direct_overwrite_enabled

        if not agrees_with_main:
            disagreement_count += 1
            warnings.append(
                f"Gemini grade verifier evidence disagrees on row {course.get('row_index')}: "
                f"main={before_grade or 'missing'}, verifier={grade_scan_grade}, "
                f"confidence={grade_scan_confidence}, match_score={round(score, 3)}."
            )

            if direct_overwrite_enabled or _grade_scan_can_safely_update_main_grade(
                score=score,
                confidence=grade_scan_confidence,
                before_grade=before_grade,
                grade_scan_grade=grade_scan_grade,
            ):
                course["grade"] = grade_scan_grade
                course["grade_scan_applied_to_main"] = True
                if isinstance(raw_gemini_row, dict):
                    raw_gemini_row["backend_grade_scan_direct_overwrite"] = bool(direct_overwrite_enabled)
                    raw_gemini_row["backend_grade_scan_applied_to_main"] = True
                    raw_gemini_row["backend_grade_scan_apply_reason"] = (
                        "direct_overwrite_enabled"
                        if direct_overwrite_enabled
                        else "high_confidence_same_row_grade_scan"
                    )

        used_course_indexes.add(course_index)
        applied_count += 1

    return applied_count, disagreement_count, warnings


def _generate_json_with_gemini(
    client: genai.Client,
    *,
    model_name: str,
    pdf_part: Any,
    prompt: str,
    temperature: float = 0.0,
) -> tuple[dict[str, Any], str]:
    from app.services.gemini_rate_limit import generate_content_limited

    response = generate_content_limited(
        client,
        model=model_name,
        contents=[pdf_part, prompt],
        config=types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
        ),
    )

    raw_response = response.text or ""
    return _safe_json_loads(raw_response), raw_response



def _is_bottom_or_summary_section(section_name: str | None) -> bool:
    text = _normalize_course_name(section_name)

    blocked_sections = [
        "TEST TAKEN",
        "CREDIT SUMMARY",
        "EVENTS",
        "COURSE TAGS",
        "GPA",
        "DIPLOMA",
        "CLASS RANK",
        "PHYSICAL FITNESS",
        "STUDENT INFORMATION",
        "COMMENTS",
        "ATTENDANCE",
    ]

    return any(blocked in text for blocked in blocked_sections)


def _is_non_course_name(course_name: str | None) -> bool:
    text = _normalize_course_name(course_name)

    blocked_values = [
        "",
        "TOTAL",
        "TOTALS",
        "COURSE TITLE",
        "CREDIT ATT CMP",
        "CREDIT ATT",
        "CREDIT CMP",
        "TGPA",
        "GPA",
        "MARK",
        "CRS ID",
        "CRS-ID",
        "GRADE",
        "DATE",
        "EVENT",
        "HOURS",
        "COMMENTS",
        "SCHOOL",
    ]

    if text in blocked_values:
        return True

    blocked_contains = [
        "CREDIT ATT",
        "CREDIT SUMMARY",
        "TEST TAKEN",
        "COURSE TAGS",
        "FINANCIAL AID APPLICATION",
        "GOLDEN STATE SEAL",
        "STATE SEAL OF BILITERACY",
        "PHYSICAL FITNESS TESTING",
        "GRADUATION REQUIREMENT",
    ]

    return any(blocked in text for blocked in blocked_contains)


def _normalize_gemini_course_row(
    row: dict[str, Any],
    fallback_index: int,
) -> tuple[dict[str, Any] | None, str | None]:
    section_name = _clean_text(row.get("section_name"))

    course_name = _clean_text(
        _first_non_empty(
            row.get("course_name"),
            row.get("course_title"),
            row.get("title"),
            row.get("name"),
            row.get("course"),
            row.get("crs_description"),
        )
    )

    course_name = _repair_common_course_name_order(course_name)

    raw_grade = _clean_grade_text(
        _first_non_empty(
            row.get("grade"),
            row.get("mark"),
            row.get("course_mark"),
            row.get("crs_letter_grade"),
        )
    )

    (
        course_name,
        raw_grade,
        trailing_grade_title_repaired,
    ) = _split_known_trailing_grade_from_course_name(course_name, raw_grade)

    if not course_name:
        return None, f"Skipped row {fallback_index} because course_name was empty."

    if _is_bottom_or_summary_section(section_name):
        return None, f"Skipped row {fallback_index} from non-course section: {section_name}"

    if _is_non_course_name(course_name):
        return None, f"Skipped row {fallback_index} because it was not a real course: {course_name}"

    visible_course_tag = _row_visible_course_tag(row)
    visible_tag_parts = _parse_course_id_parts(visible_course_tag)

    has_plus_marker = (
        _bool_from_value(row.get("has_plus_marker"))
        or visible_tag_parts["has_plus_marker"]
    )
    has_star_marker = (
        _bool_from_value(row.get("has_star_marker"))
        or visible_tag_parts["has_star_marker"]
    )

    course_prefix = _clean_text(
        _first_non_empty(
            row.get("course_prefix"),
            row.get("prefix"),
            visible_tag_parts["course_prefix"],
        )
    )
    course_number = _clean_text(
        _first_non_empty(
            row.get("course_number"),
            row.get("number"),
            visible_tag_parts["course_number"],
        )
    )

    course_id_raw = _clean_course_id_text(
        _first_non_empty(
            row.get("course_id_raw"),
            row.get("crs_id_raw"),
            row.get("raw_course_id"),
            row.get("course_id"),
            row.get("crs_id"),
            row.get("local_course_id"),
        )
    )

    if not course_id_raw:
        course_id_raw = _rebuild_course_id_raw_from_parts(
            has_plus_marker=has_plus_marker,
            has_star_marker=has_star_marker,
            course_prefix=course_prefix,
            course_number=course_number,
        )

    id_parts = _parse_course_id_parts(course_id_raw)

    final_has_plus_marker = (
        has_plus_marker
        or id_parts["has_plus_marker"]
        or visible_tag_parts["has_plus_marker"]
    )
    final_has_star_marker = (
        has_star_marker
        or id_parts["has_star_marker"]
        or visible_tag_parts["has_star_marker"]
    )
    final_course_prefix = (
        course_prefix
        or id_parts["course_prefix"]
        or visible_tag_parts["course_prefix"]
    )
    final_course_number = (
        course_number
        or id_parts["course_number"]
        or visible_tag_parts["course_number"]
    )
    final_course_id_raw = id_parts["course_id_raw"]

    rebuilt_course_id_raw = _rebuild_course_id_raw_from_parts(
        has_plus_marker=final_has_plus_marker,
        has_star_marker=final_has_star_marker,
        course_prefix=final_course_prefix,
        course_number=final_course_number,
    )

    if rebuilt_course_id_raw and (
        not final_course_id_raw
        or (final_has_plus_marker and "+" not in final_course_id_raw)
        or (final_has_star_marker and "*" not in final_course_id_raw)
        or (
            final_course_prefix
            and not re.search(
                rf"\b{re.escape(str(final_course_prefix))}\b",
                final_course_id_raw,
                flags=re.IGNORECASE,
            )
        )
    ):
        final_course_id_raw = rebuilt_course_id_raw

    credit_attempted = _coerce_float(
        _first_non_empty(
            row.get("credit_attempted"),
            row.get("credits_attempted"),
            row.get("att"),
            row.get("attempted"),
            row.get("credits"),
            row.get("crs_credit_attempted"),
        )
    )

    credit_completed = _coerce_float(
        _first_non_empty(
            row.get("credit_completed"),
            row.get("credits_completed"),
            row.get("cmp"),
            row.get("completed"),
            row.get("credits"),
            row.get("crs_credit_completed"),
        )
    )

    if credit_attempted is None and credit_completed is not None:
        credit_attempted = credit_completed

    if credit_completed is None and credit_attempted is not None:
        credit_completed = credit_attempted

    grade_level = _coerce_int(
        _first_non_empty(
            row.get("grade_level"),
            row.get("grade_year"),
            row.get("crs_grade"),
        )
    )

    if grade_level is None:
        grade_level = _extract_grade_level_from_text(section_name)

    term_name = _clean_text(row.get("term_name")) or _extract_term_name_from_text(section_name)

    explicit_year_value = _first_non_empty(
        row.get("year"),
        row.get("crs_year"),
        row.get("school_year"),
    )

    month = _month_to_int(
        _first_non_empty(
            row.get("month"),
            row.get("crs_month"),
            row.get("month_number"),
            row.get("month_name"),
        )
    )

    academic_year = (
        _clean_text(row.get("academic_year"))
        or _extract_academic_year_from_text(section_name)
    )

    if not academic_year and (
        _is_lbusd_text(section_name)
        or _is_lbusd_text(row.get("school_name"))
        or re.search(r"\bYr\s*:", str(section_name or ""), flags=re.IGNORECASE)
    ):
        academic_year = _derive_lbusd_academic_year_from_visible_year_month(
            visible_year=explicit_year_value,
            month=month,
        )

    year = _derive_year(
        explicit_year=explicit_year_value,
        academic_year=academic_year,
        term_name=term_name,
        section_name=section_name,
    )

    raw_explicit_year = _year_to_int(explicit_year_value)
    academic_start_year = _academic_year_start_year(academic_year)

    normalized = {
        "row_index": _coerce_int(row.get("row_index")) or fallback_index,
        "section_name": section_name,
        "grade_level": grade_level,
        "term_name": term_name,
        "academic_year": academic_year,
        "year": year,
        "month": month,
        "school_name": _clean_text(row.get("school_name")),

        "course_id_raw": final_course_id_raw,
        "visible_course_tag": visible_course_tag,
        "has_plus_marker": final_has_plus_marker,
        "has_star_marker": final_has_star_marker,
        "course_prefix": final_course_prefix,
        "course_number": final_course_number,

        "course_name": course_name,
        "grade": raw_grade,
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "extraction_confidence": _coerce_confidence(
            _first_non_empty(
                row.get("extraction_confidence"),
                row.get("confidence"),
                row.get("gemini_confidence"),
            )
        ),
        "raw_gemini_row": {
            **row,
            "backend_visible_course_tag": visible_course_tag,
            "backend_course_id_raw": final_course_id_raw,
            "backend_course_prefix": final_course_prefix,
            "backend_course_number": final_course_number,
            "backend_has_plus_marker": final_has_plus_marker,
            "backend_has_star_marker": final_has_star_marker,
            "backend_academic_year": academic_year,
            "backend_year_start_rule_applied": (
                academic_start_year is not None
                and raw_explicit_year is not None
                and raw_explicit_year != academic_start_year
            ),
            "backend_original_year": raw_explicit_year,
            "backend_saved_year": year,
            "backend_trailing_grade_title_repaired": trailing_grade_title_repaired,
        },
    }

    return normalized, None


def _section_count_warnings(
    raw_json: dict[str, Any],
    normalized_courses: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    section_counts = raw_json.get("section_course_counts")

    if not isinstance(section_counts, list):
        return warnings

    actual_by_section: dict[str, int] = {}

    for course in normalized_courses:
        section_name = course.get("section_name") or "UNKNOWN"
        actual_by_section[section_name] = actual_by_section.get(section_name, 0) + 1

    for idx, item in enumerate(section_counts, start=1):
        if not isinstance(item, dict):
            continue

        section_name = _clean_text(item.get("section_name")) or "UNKNOWN"
        reported_count = _coerce_int(item.get("course_count"))

        if reported_count is None:
            continue

        actual_count = actual_by_section.get(section_name, 0)

        if actual_count != reported_count:
            warnings.append(
                f"Section count mismatch for {section_name}: "
                f"Gemini reported {reported_count}, backend parsed {actual_count}."
            )

    return warnings


def _row_quality_warnings(
    courses: list[dict[str, Any]],
    *,
    allow_missing_course_id: bool = False,
) -> list[str]:
    warnings: list[str] = []

    for idx, row in enumerate(courses, start=1):
        missing_fields = []

        if not allow_missing_course_id and not row.get("course_id_raw"):
            missing_fields.append("course_id_raw")

        if not row.get("course_name"):
            missing_fields.append("course_name")

        if not row.get("grade"):
            missing_fields.append("grade")

        if row.get("credit_attempted") is None:
            missing_fields.append("credit_attempted")

        if row.get("credit_completed") is None:
            missing_fields.append("credit_completed")

        if row.get("grade_level") is None:
            missing_fields.append("grade_level")

        if row.get("year") is None:
            missing_fields.append("year")

        if missing_fields:
            warnings.append(
                f"Parsed Gemini course row {idx} is missing: {', '.join(missing_fields)}."
            )

    return warnings


def _fill_missing_course_context_from_previous_rows(
    normalized_courses: list[dict[str, Any]],
) -> int:
    """
    Fill missing row context from the immediately preceding visual course rows.

    This is intentionally narrow and only fills context fields, not course ID,
    course name, grade, or credits. It fixes Mayfair community-college mini
    sections where Gemini reads the course row but misses the surrounding
    Grade/Fall/Spring/Summer header. It also helps LBUSD continuation blocks
    when a single row misses Year/Month/Grade context.
    """

    context_fields = [
        "section_name",
        "grade_level",
        "term_name",
        "academic_year",
        "year",
        "month",
    ]

    carry: dict[str, Any] = {}
    filled_count = 0

    for course in normalized_courses:
        if not isinstance(course, dict):
            continue

        filled_fields: list[str] = []

        for field_name in context_fields:
            if course.get(field_name) in (None, "") and carry.get(field_name) not in (None, ""):
                course[field_name] = carry[field_name]
                filled_fields.append(field_name)

        # School name is safe to backfill only when missing. If the row has its
        # own mini-section school, such as Cerritos Community College, keep it.
        if course.get("school_name") in (None, "") and carry.get("school_name") not in (None, ""):
            course["school_name"] = carry["school_name"]
            filled_fields.append("school_name")

        if filled_fields:
            filled_count += 1
            raw_gemini_row = course.get("raw_gemini_row")
            if isinstance(raw_gemini_row, dict):
                raw_gemini_row["backend_context_backfilled_fields"] = filled_fields
                raw_gemini_row["backend_context_backfill_source"] = "previous_visual_course_rows"

        for field_name in [*context_fields, "school_name"]:
            if course.get(field_name) not in (None, ""):
                carry[field_name] = course.get(field_name)

    return filled_count


def _parse_gemini_courses(
    result: dict[str, Any],
    *,
    allow_missing_course_id: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    raw_rows = result.get("courses")

    if raw_rows is None:
        for key in (
            "course_rows",
            "transcript_courses",
            "course_data",
            "rows",
            "items",
        ):
            candidate = result.get(key)
            if isinstance(candidate, list):
                raw_rows = candidate
                break

    if raw_rows is None:
        for container_key in ("data", "result", "extraction"):
            container = result.get(container_key)
            if not isinstance(container, dict):
                continue

            for key in (
                "courses",
                "course_rows",
                "transcript_courses",
                "course_data",
                "rows",
                "items",
            ):
                candidate = container.get(key)
                if isinstance(candidate, list):
                    raw_rows = candidate
                    break

            if isinstance(raw_rows, list):
                break

    warnings: list[str] = []

    if not isinstance(raw_rows, list):
        return [], ["Gemini response did not contain a courses list."]

    normalized_courses: list[dict[str, Any]] = []

    for idx, row in enumerate(raw_rows, start=1):
        if not isinstance(row, dict):
            warnings.append(f"Skipped row {idx} because it was not an object.")
            continue

        normalized_row, warning = _normalize_gemini_course_row(
            row,
            fallback_index=len(normalized_courses) + 1,
        )

        if warning:
            warnings.append(warning)

        if normalized_row:
            # Preserve Gemini/PDF visual order as backend sequence.
            # Do not deduplicate repeated rows.
            normalized_row["row_index"] = len(normalized_courses) + 1
            normalized_courses.append(normalized_row)

    _apply_mayfair_month_inference(result, normalized_courses)

    if not allow_missing_course_id:
        context_filled_count = _fill_missing_course_context_from_previous_rows(normalized_courses)
        if context_filled_count:
            warnings.append(
                f"Backend filled missing term/year/month context on {context_filled_count} Gemini row(s) "
                "from previous visual course rows."
            )

    warnings.extend(_section_count_warnings(result, normalized_courses))
    warnings.extend(
        _row_quality_warnings(
            normalized_courses,
            allow_missing_course_id=allow_missing_course_id,
        )
    )

    return normalized_courses, warnings


def _build_pdf_part(
    *,
    pdf_path: str | None = None,
    gcs_uri: str | None = None,
):
    if gcs_uri:
        return types.Part.from_uri(
            file_uri=gcs_uri,
            mime_type="application/pdf",
        )

    if pdf_path:
        with open(pdf_path, "rb") as file:
            pdf_bytes = file.read()

        return types.Part.from_bytes(
            data=pdf_bytes,
            mime_type="application/pdf",
        )

    return None


def run_gemini_course_extraction(
    pdf_path: str | None = None,
    gcs_uri: str | None = None,
    transcript_format: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """
    Extract raw Gemini course rows from a transcript PDF.

    Returns:
    {
        "status": "completed" | "completed_with_warnings" | "needs_review" | "failed",
        "courses": [...],
        "course_count": int,
        "total_course_count": int,
        "gemini_reported_total_course_count": int | None,
        "model": str,
        "parser_warnings": [...],
        "raw_gemini_json": {...} | None,
        "raw_response": str | None,
        "error": str | None
    }
    """

    model_name = _resolve_gemini_model()
    (
        extraction_prompt,
        prompt_type,
        is_st_anthony,
        is_lbusd,
    ) = _select_extraction_prompt(
        pdf_path=pdf_path,
        gcs_uri=gcs_uri,
        transcript_format=transcript_format,
    )

    pdf_part = _build_pdf_part(
        pdf_path=pdf_path,
        gcs_uri=gcs_uri,
    )

    if pdf_part is None:
        return {
            "status": "failed",
            "courses": [],
            "course_count": 0,
            "total_course_count": 0,
            "gemini_reported_total_course_count": None,
            "model": model_name,
            "parser_warnings": [],
            "raw_gemini_json": None,
            "raw_response": None,
            "prompt_type": prompt_type,
            "is_st_anthony_prompt": is_st_anthony,
            "is_lbusd_prompt": is_lbusd,
            "error": "No pdf_path or gcs_uri was provided for Gemini extraction.",
        }

    try:
        client = _make_gemini_client()
        raw_json, raw_response = _generate_json_with_gemini(
            client,
            model_name=model_name,
            pdf_part=pdf_part,
            prompt=extraction_prompt,
            temperature=temperature,
        )

    except Exception as exc:
        return {
            "status": "failed",
            "courses": [],
            "course_count": 0,
            "total_course_count": 0,
            "gemini_reported_total_course_count": None,
            "model": model_name,
            "parser_warnings": [],
            "raw_gemini_json": None,
            "raw_response": None,
            "prompt_type": prompt_type,
            "is_st_anthony_prompt": is_st_anthony,
            "is_lbusd_prompt": is_lbusd,
            "error": f"Gemini API extraction failed: {str(exc)}",
        }

    courses, parser_warnings = _parse_gemini_courses(
        raw_json,
        allow_missing_course_id=is_st_anthony,
    )

    tag_scan_json: dict[str, Any] | None = None
    tag_scan_raw_response: str | None = None
    tag_scan_applied_count = 0

    course_id_scan_json: dict[str, Any] | None = None
    course_id_scan_raw_response: str | None = None
    course_id_scan_applied_count = 0
    course_id_scan_disagreement_count = 0

    grade_scan_json: dict[str, Any] | None = None
    grade_scan_raw_response: str | None = None
    grade_scan_applied_count = 0
    grade_scan_disagreement_count = 0
    grade_scan_changed_count = 0

    scan_requests: dict[str, str] = {}

    if _should_run_tag_scan(courses, is_st_anthony=is_st_anthony, is_lbusd=is_lbusd):
        scan_requests["tag"] = GEMINI_COURSE_TAG_SCAN_PROMPT

    if _should_run_course_id_scan(courses, is_st_anthony=is_st_anthony):
        scan_requests["course_id"] = GEMINI_COURSE_ID_SCAN_PROMPT

    if _should_run_grade_scan(courses):
        scan_requests["grade"] = GEMINI_GRADE_SCAN_PROMPT

    scan_results: dict[str, tuple[dict[str, Any], str]] = {}

    if scan_requests:
        if _optional_scans_parallel_enabled() and len(scan_requests) > 1:
            with ThreadPoolExecutor(
                max_workers=min(_optional_scan_worker_count(), len(scan_requests))
            ) as executor:
                futures = {
                    executor.submit(
                        _generate_json_with_new_client,
                        model_name=model_name,
                        pdf_part=pdf_part,
                        prompt=prompt,
                    ): scan_name
                    for scan_name, prompt in scan_requests.items()
                }

                for future in as_completed(futures):
                    scan_name = futures[future]

                    try:
                        scan_results[scan_name] = future.result()
                    except Exception as exc:
                        parser_warnings.append(
                            f"Optional Gemini {scan_name} verifier failed: {str(exc)}"
                        )
        else:
            for scan_name, prompt in scan_requests.items():
                try:
                    scan_results[scan_name] = _generate_json_with_new_client(
                        model_name=model_name,
                        pdf_part=pdf_part,
                        prompt=prompt,
                    )
                except Exception as exc:
                    parser_warnings.append(
                        f"Optional Gemini {scan_name} verifier failed: {str(exc)}"
                    )

    if "tag" in scan_results:
        tag_scan_json, tag_scan_raw_response = scan_results["tag"]

        try:
            tag_scan_applied_count, tag_scan_warnings = _apply_tag_scan_results(
                courses,
                tag_scan_json,
            )
            parser_warnings.extend(tag_scan_warnings)

            if tag_scan_applied_count:
                parser_warnings.append(
                    f"Gemini tag scan applied visible course tags to "
                    f"{tag_scan_applied_count} row(s)."
                )

            raw_json["backend_tag_scan"] = {
                "applied_count": tag_scan_applied_count,
                "raw_json": tag_scan_json,
            }

        except Exception as exc:
            parser_warnings.append(f"Optional Gemini tag scan post-processing failed: {str(exc)}")

    if "course_id" in scan_results:
        course_id_scan_json, course_id_scan_raw_response = scan_results["course_id"]

        try:
            (
                course_id_scan_applied_count,
                course_id_scan_disagreement_count,
                course_id_scan_warnings,
            ) = _apply_course_id_scan_results(courses, course_id_scan_json)
            parser_warnings.extend(course_id_scan_warnings)

            raw_json["backend_course_id_scan"] = {
                "applied_count": course_id_scan_applied_count,
                "disagreement_count": course_id_scan_disagreement_count,
                "evidence_only": True,
                "raw_json": course_id_scan_json,
            }

            if course_id_scan_applied_count:
                parser_warnings.append(
                    f"Gemini Course ID verifier attached evidence for "
                    f"{course_id_scan_applied_count} row(s); found "
                    f"{course_id_scan_disagreement_count} row(s) where verifier evidence "
                    f"disagrees with the main Gemini Course ID. Verifier did not overwrite "
                    f"main Gemini Course IDs."
                )

        except Exception as exc:
            parser_warnings.append(
                f"Optional Gemini Course ID verifier post-processing failed: {str(exc)}"
            )

    if "grade" in scan_results:
        grade_scan_json, grade_scan_raw_response = scan_results["grade"]

        try:
            (
                grade_scan_applied_count,
                grade_scan_disagreement_count,
                grade_scan_warnings,
            ) = _apply_grade_scan_results(courses, grade_scan_json)
            grade_scan_changed_count = 0
            parser_warnings.extend(grade_scan_warnings)

            raw_json["backend_grade_scan"] = {
                "applied_count": grade_scan_applied_count,
                "changed_count": 0,
                "disagreement_count": grade_scan_disagreement_count,
                "evidence_only": not _grade_scan_overwrite_main_grade_enabled(),
                "raw_json": grade_scan_json,
            }

            if grade_scan_applied_count:
                parser_warnings.append(
                    f"Gemini grade verifier attached evidence for "
                    f"{grade_scan_applied_count} row(s); found "
                    f"{grade_scan_disagreement_count} row(s) where verifier evidence "
                    f"disagrees with the main Gemini grade. Verifier did not overwrite "
                    f"main Gemini grades."
                )

        except Exception as exc:
            parser_warnings.append(
                f"Optional Gemini grade verifier post-processing failed: {str(exc)}"
            )


    backend_count = len(courses)
    reported_total = _coerce_int(raw_json.get("total_course_count"))

    if reported_total is not None and reported_total != backend_count:
        parser_warnings.append(
            f"Gemini reported total_course_count={reported_total}, "
            f"but backend parsed {backend_count} real course row(s)."
        )

    status = "completed"

    if backend_count == 0:
        status = "needs_review"
        parser_warnings.append("Gemini returned zero parsed course rows.")

    elif parser_warnings:
        status = "completed_with_warnings"

    return {
        "status": status,
        "courses": courses,
        "course_count": backend_count,
        "total_course_count": backend_count,
        "gemini_reported_total_course_count": reported_total,
        "model": model_name,
        "parser_warnings": parser_warnings,
        "raw_gemini_json": raw_json,
        "raw_response": raw_response,
        "tag_scan_raw_response": tag_scan_raw_response,
        "tag_scan_applied_count": tag_scan_applied_count,
        "course_id_scan_raw_response": course_id_scan_raw_response,
        "course_id_scan_applied_count": course_id_scan_applied_count,
        "course_id_scan_disagreement_count": course_id_scan_disagreement_count,
        "grade_scan_raw_response": grade_scan_raw_response,
        "grade_scan_applied_count": grade_scan_applied_count,
        "grade_scan_disagreement_count": grade_scan_disagreement_count,
        "grade_scan_changed_count": grade_scan_changed_count,
        "optional_scans_parallel": _optional_scans_parallel_enabled(),
        "optional_scan_worker_count": _optional_scan_worker_count(),
        "tag_scan_enabled": _tag_scan_enabled(),
        "course_id_scan_enabled": _course_id_scan_enabled(),
        "grade_scan_enabled": _grade_scan_enabled(),
        "prompt_type": prompt_type,
        "is_st_anthony_prompt": is_st_anthony,
        "is_lbusd_prompt": is_lbusd,
        "error": None,
    }