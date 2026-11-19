from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Literal

import google.auth
from google import genai
from google.cloud import storage
from google.genai import types
from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as db_models


logger = logging.getLogger(__name__)


_VALID_GEMINI_MODELS = {
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
}


def _resolve_gemini_model(explicit_model: str | None = None) -> str:
    configured = (
        explicit_model
        or os.environ.get("NEW_TRANSCRIPT_GEMINI_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or "gemini-2.5-flash"
    ).strip()

    if configured not in _VALID_GEMINI_MODELS:
        logger.warning(
            "Gemini model %r is not supported by the existing extractor; "
            "using gemini-2.5-flash",
            configured,
        )
        return "gemini-2.5-flash"

    return configured


def _make_gemini_client() -> genai.Client:
    """Create a client using the same auth order as gemini_course_extractor."""
    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if api_key:
        return genai.Client(api_key=api_key)

    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT",
        "doc-ai-transcript",
    )
    location = os.environ.get(
        "GEMINI_LOCATION",
        "us-central1",
    )

    service_account_b64 = os.environ.get("DOCAI_SA_KEY_B64")
    if service_account_b64:
        try:
            account_info = json.loads(
                base64.b64decode(service_account_b64).decode("utf-8")
            )
            credentials = (
                service_account.Credentials.from_service_account_info(
                    account_info,
                    scopes=[
                        "https://www.googleapis.com/auth/cloud-platform"
                    ],
                )
            )
            project = account_info.get("project_id", project)
            return genai.Client(
                vertexai=True,
                project=project,
                location=location,
                credentials=credentials,
            )
        except Exception:
            logger.exception(
                "Could not create Gemini credentials from DOCAI_SA_KEY_B64"
            )

    try:
        _, adc_project = google.auth.default()
        project = adc_project or project
        return genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
    except Exception:
        logger.exception("Gemini ADC authentication failed")

    service_account_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "cloudsql",
            "service-account.json",
        )
    )
    if os.path.exists(service_account_path):
        try:
            credentials = (
                service_account.Credentials.from_service_account_file(
                    service_account_path,
                    scopes=[
                        "https://www.googleapis.com/auth/cloud-platform"
                    ],
                )
            )
            project = credentials.project_id or project
            return genai.Client(
                vertexai=True,
                project=project,
                location=location,
                credentials=credentials,
            )
        except Exception:
            logger.exception(
                "Bundled Gemini service-account authentication failed"
            )

    raise RuntimeError("All Gemini authentication methods failed.")


def _safe_json_loads(raw_text: str) -> dict[str, Any]:
    """Parse Gemini JSON, repair minor defects, then return one object."""
    if not raw_text:
        raise ValueError("Gemini returned an empty transcript response")

    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    try:
        from json_repair import repair_json

        parsed = json.loads(repair_json(cleaned))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidate = re.sub(
            r",\s*([}\]])",
            r"\1",
            cleaned[start : end + 1],
        )
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Gemini did not return a valid JSON object")


# ---------------------------------------------------------------------------
# Resolve models
# ---------------------------------------------------------------------------

def _find_model(*names: str):
    for name in names:
        model = getattr(db_models, name, None)
        if model is not None:
            return model

    raise ImportError(
        f"Could not find any of these SQLAlchemy models in app.models: {names}"
    )


ExtractionFileDetails = _find_model("ExtractionFileDetails")
NewTranscriptStudents = _find_model("NewTranscriptStudents")
NewTranscriptCourseDetails = _find_model("NewTranscriptCourseDetails")


# ---------------------------------------------------------------------------
# Gemini structured response models
# ---------------------------------------------------------------------------


class StrictModel(BaseModel):
    """Forbid silent schema drift in Gemini structured output."""

    model_config = ConfigDict(extra="forbid")


class FieldConfidence(StrictModel):
    course_id_raw: float = Field(default=0.0, ge=0.0, le=1.0)
    course_name: float = Field(default=0.0, ge=0.0, le=1.0)
    grade: float = Field(default=0.0, ge=0.0, le=1.0)
    credit_attempted: float = Field(default=0.0, ge=0.0, le=1.0)
    credit_completed: float = Field(default=0.0, ge=0.0, le=1.0)
    grade_level: float = Field(default=0.0, ge=0.0, le=1.0)
    term_name: float = Field(default=0.0, ge=0.0, le=1.0)
    academic_year: float = Field(default=0.0, ge=0.0, le=1.0)
    year: float = Field(default=0.0, ge=0.0, le=1.0)
    month: float = Field(default=0.0, ge=0.0, le=1.0)
    school_name: float = Field(default=0.0, ge=0.0, le=1.0)


class GeminiStudent(StrictModel):
    full_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    student_id: str | None = None
    state_id: str | None = None
    address: str | None = None
    phone_number: str | None = None
    gender: str | None = None
    date_of_birth: str | None = None
    primary_school_name: str | None = None
    district_name: str | None = None
    counselor_name: str | None = None
    current_grade_level: int | None = None
    total_units_earned: float | None = None
    total_gpa_course: float | None = None
    academic_gpa_course: float | None = None
    university_gpa: float | None = None
    enter_date: str | None = None
    graduation_date: str | None = None
    graduation_year: int | None = None
    extraction_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )
    uncertain_fields: list[str] = Field(default_factory=list)

    @property
    def school_name(self) -> str | None:
        return self.primary_school_name


class GeminiBlock(StrictModel):
    block_index: int = Field(ge=1)
    page_number: int = Field(default=1, ge=1)
    visual_column: int = Field(default=1, ge=1)
    layout_family: Literal[
        "row_table_with_context",
        "term_block_columns",
        "semester_matrix",
        "generic_course_table",
        "mixed",
        "unknown",
    ] = "unknown"
    block_header: str | None = None
    school_name: str | None = None
    grade_level: int | None = None
    term_name: str | None = None
    academic_year: str | None = None
    visible_year: int | None = None
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    month_source: Literal[
        "explicit",
        "derived",
        "not_available",
    ] = "not_available"
    term_gpa: float | None = None
    course_row_count: int = Field(default=0, ge=0)
    block_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )
    uncertain_fields: list[str] = Field(default_factory=list)


class GeminiCourse(StrictModel):
    row_index: int = Field(ge=1)
    block_index: int = Field(ge=1)
    row_in_block: int = Field(ge=1)
    page_number: int = Field(default=1, ge=1)
    visual_column: int = Field(default=1, ge=1)
    layout_family: Literal[
        "row_table_with_context",
        "term_block_columns",
        "semester_matrix",
        "generic_course_table",
        "mixed",
        "unknown",
    ] = "unknown"
    section_name: str | None = None
    school_name: str | None = None
    grade_level: int | None = None
    term_name: str | None = None
    academic_year: str | None = None
    visible_year: int | None = None
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    month_source: Literal[
        "explicit",
        "derived",
        "not_available",
    ] = "not_available"
    course_id_raw: str | None = None
    course_prefix_raw: str | None = None
    course_number: str | None = None
    has_plus_marker: bool = False
    has_star_marker: bool = False
    course_name: str | None = None
    grade: str | None = None
    credit_attempted: float | None = None
    credit_completed: float | None = None
    extraction_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )
    field_confidence: FieldConfidence = Field(
        default_factory=FieldConfidence
    )
    uncertain_fields: list[str] = Field(default_factory=list)
    review_reason: str | None = None

    @property
    def course_id(self) -> str | None:
        return self.course_id_raw

    @property
    def letter_grade(self) -> str | None:
        return self.grade


class GeminiTranscript(StrictModel):
    document_type: Literal[
        "high_school_transcript",
        "not_a_transcript",
        "uncertain",
    ] = "uncertain"
    primary_layout_family: Literal[
        "row_table_with_context",
        "term_block_columns",
        "semester_matrix",
        "generic_course_table",
        "mixed",
        "unknown",
    ] = "unknown"
    layout_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )
    student: GeminiStudent = Field(default_factory=GeminiStudent)
    total_course_count: int = Field(default=0, ge=0)
    blocks: list[GeminiBlock] = Field(default_factory=list)
    courses: list[GeminiCourse] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)

    @property
    def extraction_notes(self) -> list[str]:
        return self.extraction_warnings


NEW_TRANSCRIPT_GEMINI_PROMPT = """
You are extracting structured student and course data from a high-school
transcript PDF whose exact format may be unknown.

The transcript may resemble an LBUSD-style course table, a Mayfair-style
multi-column term layout, a St. Anthony-style semester matrix, or another
high-school transcript format.

Use only information visibly present in the PDF.
Do not use outside knowledge.
Do not guess unreadable values.
Return data that exactly follows the provided JSON schema.
Return no markdown, commentary, or text outside the JSON response.


======================================================================
STUDENT INFORMATION
======================================================================

Extract these student fields only when they are visibly printed:

- full_name
- first_name
- middle_name
- last_name
- student_id
- state_id
- address
- phone_number
- gender
- date_of_birth
- primary_school_name
- district_name
- counselor_name
- current_grade_level
- total_units_earned
- total_gpa_course
- academic_gpa_course
- university_gpa
- enter_date
- graduation_date
- graduation_year

Rules:

1. Do not derive student information from the filename.
2. Do not use a parent, guardian, counselor, or school employee name as the
   student name.
3. Preserve student_id and state_id exactly as visible strings.
4. Return date_of_birth, enter_date, and graduation_date as YYYY-MM-DD only
   when the complete date is visibly reliable.
5. If only a graduation year is visible, set graduation_year and leave
   graduation_date null.
6. Do not use cumulative GPA as term GPA.
7. Return null for every student field that is not visible or is unreadable.
8. Add unclear student fields to student.uncertain_fields.
9. Use student extraction_confidence below 1.0 whenever any extracted student
   character is unclear.

======================================================================
PRIMARY REQUIREMENT
======================================================================

Extract exactly one output course object for every visible transcript course
occurrence.

For a normal row-based transcript:
- One visible course row must produce exactly one course object.

For a semester-matrix transcript:
- Each non-empty subject-and-semester grade/credit cell is one course
  occurrence.
- A subject with SEM1 and SEM2 values must produce two separate course objects.

Repeated courses are valid.
Never deduplicate repeated course rows.

======================================================================
PASS 1 - IDENTIFY THE LAYOUT
======================================================================

Inspect the visible PDF structure before extracting rows.

Classify each course block as one of:

- row_table_with_context
- term_block_columns
- semester_matrix
- generic_course_table
- mixed
- unknown

Similarity to LBUSD, Mayfair, or St. Anthony does not mean the transcript is
exactly that format.

Apply rules from the visible layout, not from the school name alone.

======================================================================
PASS 2 - DETECT COURSE BLOCKS
======================================================================

Detect every visible course block before extracting course rows.

A block may begin with:

- a school name;
- a grade, term, or academic-year header;
- a Yr / Month / Grade header;
- a repeated course-table header;
- semester column headers;
- another visibly grouped course-section header.

A block ends before:

- the next course block;
- the next school or academic-year section;
- a GPA or credit summary;
- test scores;
- attendance;
- comments;
- a legend;
- a footer;
- the end of the visible course area.

Do not assume a fixed block height.

Read multi-column transcripts in visual order:

1. Left column top-to-bottom.
2. Middle column top-to-bottom.
3. Right column top-to-bottom.

A block may continue into the next column. A column boundary alone does not
change the term context. Continue using the previous block context until a new
visible header appears.

======================================================================
PASS 3 - EXTRACT EVERY COURSE OCCURRENCE
======================================================================

Extract every real visible course occurrence exactly once.

For each course occurrence, course ID, course title, grade, attempted credits,
and completed credits must come from the same visible horizontal row or the
same semester cell.

Never borrow a value from the row above, row below, another column, another
block, another repeated occurrence, or a summary row.

If a visible course occurrence is partially unreadable:

- still return the course object;
- return null for unreadable values;
- list those fields in uncertain_fields;
- lower extraction_confidence;
- provide review_reason.

Do not skip a real row merely because one field is unreadable.

======================================================================
COURSE COUNT REQUIREMENT
======================================================================

Before returning JSON:

1. Count every real visible course occurrence.
2. Ensure each visible occurrence has exactly one course object.
3. Set total_course_count equal to the exact length of courses.
4. Ensure the sum of course_row_count across all blocks equals
   total_course_count.
5. Ensure row_index values are sequential from 1 through total_course_count.

Do not count table headers, GPA rows, credit summaries, cumulative totals,
test scores, attendance, comments, legends, transcript notes, page headers,
or page footers.

======================================================================
TERM AND YEAR CONTEXT
======================================================================

grade_level, term_name, academic_year, year, and month must come from one
consistent visible block context.

Never combine grade level from one section with year or month from another.

When an academic-year range is visible, always use its start year for the
normalized year field.

Use these normalized term rules:

- Fall -> academic-year start year, month=1
- Spring -> academic-year start year, month=6
- Summer, Summer School, Summer/Intersession, or Intersession -> academic-year
  start year, month=7

Examples:

Fall 2023-2024 -> term_name="Fall", academic_year="2023-2024", year=2023,
month=1.

Spring 2023-2024 -> term_name="Spring", academic_year="2023-2024", year=2023,
month=6.

Summer 2023-2024 -> term_name="Summer", academic_year="2023-2024", year=2023,
month=7.

If a different month is explicitly printed, preserve the explicit month and
set month_source="explicit".

If no term, academic year, or month is visible or reliably derivable, return
null and do not guess.

For semester matrices:

- SEM 1 or Semester 1 -> term_name="SEM1"
- SEM 2 or Semester 2 -> term_name="SEM2"
- S_SCH, Summer, or Summer School column -> term_name="S_SCH"

Do not invent a month for semester-matrix layouts when no month is shown.

======================================================================
TERM GPA
======================================================================

Extract term GPA once at the block level.

Store it only in blocks[].term_gpa.
Do not independently extract or repeat term GPA inside course objects.
Each course references its block through block_index.
If no term GPA is visible for a block, use null.
Do not use cumulative GPA as term GPA.

======================================================================
COURSE ID AND RAW PREFIX MARKERS
======================================================================

Preserve the complete visible Course ID exactly in course_id_raw.
Preserve visible prefix markers exactly as printed, including lowercase and
marker order.

Important raw markers include p, +, *, and r. Other visibly printed markers
must also be preserved exactly rather than normalized.

Examples:

Visible p 7510 -> course_prefix_raw="p", course_number="7510",
course_id_raw="p 7510".

Visible + p 3431 -> course_prefix_raw="+ p", course_number="3431",
course_id_raw="+ p 3431".

Visible * 8130 -> course_prefix_raw="*", course_number="8130",
course_id_raw="* 8130".

Visible r 2201 -> course_prefix_raw="r", course_number="2201",
course_id_raw="r 2201".

Visible 8130 -> course_prefix_raw=null, course_number="8130",
course_id_raw="8130".

Rules:

1. Do not uppercase lowercase markers.
2. Do not normalize p to P or r to R.
3. Do not change marker order.
4. Do not add a marker because it appears in a legend.
5. A marker must be visibly attached to that exact course row.
6. Numeric-only IDs are valid.
7. If any ID character or digit is unclear, return course_id_raw=null or only
   the reliably visible portion, add course_id_raw to uncertain_fields, lower
   confidence below 1.0, and explain the uncertainty in review_reason.
8. Never copy a Course ID from a nearby row.
9. Set has_plus_marker=true only when + is visibly present.
10. Set has_star_marker=true only when * is visibly present.

======================================================================
COURSE TITLE
======================================================================

Extract course_name exactly as printed. Preserve word order, abbreviations,
punctuation, and visible capitalization. Join a wrapped continuation only when
it clearly belongs to the same course row and has no separate course ID, grade,
or credit value. Do not standardize or rename courses.

======================================================================
GRADE
======================================================================

Extract the exact visible grade from the same row or semester cell.
Possible values include A, A-, A+, B, B-, B+, C, C-, C+, D, D-, D+, F, P,
CR, NC, NM, and other visibly printed transcript codes.

Do not default an unclear grade to A.
Do not upgrade B or C to A.
CR is valid only when CR is visibly printed.

If the grade is unclear:

- grade=null;
- include "grade" in uncertain_fields;
- extraction_confidence must be below 0.8;
- review_reason must explain that the grade needs review.

Before returning JSON, perform a final row-by-row grade verification.

======================================================================
CREDITS
======================================================================

Credits must be individual per-course values. Do not use term totals,
cumulative totals, credit summaries, or graduation totals.

When two values are visibly shown as Attempted / Completed:

- first value -> credit_attempted
- second value -> credit_completed

Preserve 0.0 as a valid value.
When one visible credit clearly applies to both attempted and completed, use
that value for both.
If a credit is unreadable, return null and do not guess.

======================================================================
SCHOOL CONTEXT
======================================================================

A transcript may contain courses from multiple schools. For every course, use
the school name printed in that course's own section. Do not automatically use
the top-level transcript school. Preserve community-college or alternate-school
section names. Retain surrounding grade/term/year context unless a new context
header is visibly printed.

======================================================================
CONFIDENCE
======================================================================

Use extraction_confidence from 0.0 to 1.0.

Use 1.0 only when every extracted character and all important row alignment
are completely clear.

If any character in any extracted field is unclear:

- extraction_confidence must be below 1.0;
- include the affected field in uncertain_fields;
- provide a short review_reason.

Suggested levels:

- 1.0: every extracted character is clearly visible and aligned.
- 0.90 to 0.99: a minor character or formatting detail is slightly uncertain.
- 0.80 to 0.89: one field has meaningful uncertainty.
- 0.50 to 0.79: an important field or row alignment needs human review.
- below 0.50: the course occurrence or row alignment is highly uncertain.

Do not use 1.0 when anything was guessed.
A clearly inherited block context is valid and does not by itself reduce
confidence.
Missing Course ID should not reduce confidence when the layout has no Course ID
column. Missing month should not reduce confidence when the layout does not
show or define a month.

field_confidence must use the same principle. Any field with an unclear
character must have confidence below 1.0.

======================================================================
FINAL VERIFICATION
======================================================================

Before returning JSON:

1. Verify every course object against the PDF.
2. Verify exactly one object per visible course occurrence.
3. Verify course IDs row-by-row.
4. Verify grades row-by-row.
5. Verify credits row-by-row.
6. Verify term context block-by-block.
7. Verify block term GPA once per block.
8. Verify repeated courses were preserved.
9. Verify no summary rows became course rows.
10. Verify all count fields agree.

Return only data matching the provided JSON schema.
""".strip()


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class NewTranscriptTypeExtractionService:
    """
    Gemini-only extraction for transcript types that do not yet have a
    dedicated Document AI extractor.

    This service intentionally writes only to:

        new_transcript_student_details
        new_transcript_course_details

    It does not write to student_details, course_details,
    gemini_course_details, course_extraction_matches, or final_course_details.
    Confidence and uncertainty are used only in memory to describe why the
    transcript needs review. Every Gemini-only transcript remains in Human
    Review with Audit until a user explicitly moves it to Completed.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        auto_resolve_confidence: float | None = None,
        audit_confidence: float | None = None,
    ) -> None:
        self.model_name = _resolve_gemini_model(model_name)

        self.auto_resolve_confidence = (
            auto_resolve_confidence
            if auto_resolve_confidence is not None
            else float(
                os.environ.get(
                    "NEW_TRANSCRIPT_AUTO_RESOLVE_CONFIDENCE",
                    "1.00",
                )
            )
        )

        self.audit_confidence = (
            audit_confidence
            if audit_confidence is not None
            else float(
                os.environ.get(
                    "NEW_TRANSCRIPT_AUDIT_CONFIDENCE",
                    "0.65",
                )
            )
        )

        if not 0.0 <= self.audit_confidence <= 1.0:
            raise ValueError(
                "NEW_TRANSCRIPT_AUDIT_CONFIDENCE must be between 0 and 1."
            )

        if not 0.0 <= self.auto_resolve_confidence <= 1.0:
            raise ValueError(
                "NEW_TRANSCRIPT_AUTO_RESOLVE_CONFIDENCE must be between "
                "0 and 1."
            )

        if self.audit_confidence > self.auto_resolve_confidence:
            raise ValueError(
                "The audit confidence threshold cannot be greater than the "
                "auto-complete confidence threshold."
            )

    async def process_gemini_only_transcript(
        self,
        *,
        session: AsyncSession,
        extraction_file: Any,
        gcs_uri: str,
        institution_id: int,
        classifier_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract one PDF with Gemini and save only its real transcript fields in
        the isolated new-transcript tables.

        institution_id remains in the public method signature because the
        extraction router already supplies it. The two isolated tables mirror
        student_details/course_details and therefore do not have an
        institution_id column.
        """
        del institution_id  # Kept in the signature for router compatibility.

        extraction_file_id = int(extraction_file.id)
        file_name = str(extraction_file.file_name)

        extraction_file.process_status = "processing"
        await session.commit()

        try:
            pdf_bytes = await self._download_pdf(gcs_uri)

            transcript = await self._extract_with_gemini(
                pdf_bytes=pdf_bytes,
                file_name=file_name,
                classifier_name=classifier_name,
            )

            structure_was_normalised = (
                self._normalise_transcript_structure(transcript)
            )
            self._validate_transcript_structure(transcript)

            # Safe reruns: remove only prior rows from the two isolated tables.
            await self._clear_previous_results(
                session=session,
                extraction_file_id=extraction_file_id,
            )

            if transcript.document_type != "high_school_transcript":
                extraction_file.process_status = "needs_review_audit"
                self._set_processed_date(extraction_file)
                await session.commit()

                return {
                    "status": "processed",
                    "mode": "gemini_only_new_transcript",
                    "file_name": file_name,
                    "students": 0,
                    "courses": 0,
                    "unresolved_courses": 0,
                    "student_needs_review": True,
                    "average_confidence": 0.0,
                    "review_bucket": "human_review_with_audit",
                    "process_status": extraction_file.process_status,
                    "extraction_notes": transcript.extraction_warnings,
                }

            student_review_reasons = self._student_review_reasons(
                transcript.student
            )

            student_row = await self._create_student(
                session=session,
                extraction_file_id=extraction_file_id,
                student=transcript.student,
            )
            student_pk = int(student_row.id)

            block_by_index = {
                block.block_index: block
                for block in transcript.blocks
            }

            created_courses = 0
            unresolved_courses = 0
            confidence_values: list[float] = []

            for course in transcript.courses:
                block = block_by_index[course.block_index]
                transcript_school = self._resolve_course_school(
                    course=course,
                    block=block,
                    student=transcript.student,
                )
                (
                    effective_grade_level,
                    effective_year,
                    effective_month,
                    context_review_reasons,
                ) = self._resolve_course_context(
                    course=course,
                    block=block,
                )

                confidence = self._normalise_confidence(
                    course.extraction_confidence
                )
                confidence_values.append(confidence)

                review_reasons = self._course_review_reasons(
                    course=course,
                    transcript_school=transcript_school,
                    effective_grade_level=effective_grade_level,
                    effective_year=effective_year,
                    effective_month=effective_month,
                    confidence=confidence,
                )
                review_reasons.extend(context_review_reasons)
                review_reasons = list(dict.fromkeys(review_reasons))

                if review_reasons:
                    unresolved_courses += 1

                await self._create_course(
                    session=session,
                    extraction_file_id=extraction_file_id,
                    student_pk=student_pk,
                    course=course,
                    transcript_school=transcript_school,
                    grade_level=effective_grade_level,
                    year=effective_year,
                    month=effective_month,
                    block_term_gpa=block.term_gpa,
                )
                created_courses += 1

            average_confidence = (
                sum(confidence_values) / len(confidence_values)
                if confidence_values
                else 0.0
            )

            student_needs_review = bool(student_review_reasons)
            student_audit_required = bool(
                self._student_audit_reasons(transcript.student)
            )

            review_bucket = self._determine_review_bucket(
                transcript=transcript,
                created_courses=created_courses,
                unresolved_courses=unresolved_courses,
                student_needs_review=student_needs_review,
                student_audit_required=student_audit_required,
                average_confidence=average_confidence,
                structure_was_normalised=structure_was_normalised,
            )

            process_status_by_bucket = {
                "auto_complete": "completed",
                "human_review": "needs_review",
                "human_review_with_audit": "needs_review_audit",
            }
            extraction_file.process_status = process_status_by_bucket[
                review_bucket
            ]
            self._set_processed_date(extraction_file)

            await session.commit()

            return {
                "status": "processed",
                "mode": "gemini_only_new_transcript",
                "file_name": file_name,
                "students": 1,
                "courses": created_courses,
                "unresolved_courses": unresolved_courses,
                "student_needs_review": student_needs_review,
                "student_audit_required": student_audit_required,
                "student_review_reasons": student_review_reasons,
                "average_confidence": round(average_confidence, 4),
                "structure_was_normalised": structure_was_normalised,
                "review_bucket": review_bucket,
                "process_status": extraction_file.process_status,
                "extraction_notes": transcript.extraction_warnings,
            }

        except Exception:
            logger.exception(
                "Gemini-only new-transcript extraction failed for "
                "extraction_file_id=%s file=%s",
                extraction_file_id,
                file_name,
            )

            await session.rollback()

            refreshed_file = await session.get(
                ExtractionFileDetails,
                extraction_file_id,
            )
            if refreshed_file is not None:
                refreshed_file.process_status = "failed"
                self._set_processed_date(refreshed_file)
                await session.commit()

            raise

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    async def _extract_with_gemini(
        self,
        *,
        pdf_bytes: bytes,
        file_name: str,
        classifier_name: str | None,
    ) -> GeminiTranscript:
        client = self._create_gemini_client()
        prompt = self._build_prompt(
            file_name=file_name,
            classifier_name=classifier_name,
        )

        try:
            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type="application/pdf",
                    ),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
        finally:
            close_method = getattr(client.aio, "aclose", None)
            if close_method is not None:
                await close_method()

        parsed_response = getattr(response, "parsed", None)
        if isinstance(parsed_response, GeminiTranscript):
            return parsed_response
        if isinstance(parsed_response, dict):
            return GeminiTranscript.model_validate(parsed_response)

        payload = _safe_json_loads(
            getattr(response, "text", None) or ""
        )
        return GeminiTranscript.model_validate(payload)

    def _create_gemini_client(self) -> genai.Client:
        return _make_gemini_client()

    def _build_prompt(
        self,
        *,
        file_name: str,
        classifier_name: str | None,
    ) -> str:
        schema_text = json.dumps(
            GeminiTranscript.model_json_schema(mode="validation"),
            ensure_ascii=False,
            indent=2,
        )
        return (
            f"Source file: {file_name}\n"
            f"Detected transcript group: "
            f"{classifier_name or 'unknown'}\n\n"
            + NEW_TRANSCRIPT_GEMINI_PROMPT
            + "\n\nREQUIRED OUTPUT JSON SCHEMA:\n"
            + schema_text
        )

    async def _download_pdf(self, gcs_uri: str) -> bytes:
        match = re.match(r"^gs://([^/]+)/(.+)$", gcs_uri)
        if not match:
            raise ValueError(
                f"Expected a gs:// URI but received: {gcs_uri}"
            )

        bucket_name, blob_name = match.groups()

        def download() -> bytes:
            storage_client = storage.Client()
            blob = storage_client.bucket(bucket_name).blob(blob_name)
            return blob.download_as_bytes()

        return await asyncio.to_thread(download)

    # ------------------------------------------------------------------
    # Isolated persistence
    # ------------------------------------------------------------------

    async def _clear_previous_results(
        self,
        *,
        session: AsyncSession,
        extraction_file_id: int,
    ) -> None:
        await session.execute(
            delete(NewTranscriptCourseDetails).where(
                NewTranscriptCourseDetails.source_file
                == extraction_file_id
            )
        )
        await session.execute(
            delete(NewTranscriptStudents).where(
                NewTranscriptStudents.source_file
                == extraction_file_id
            )
        )
        await session.flush()

    async def _create_student(
        self,
        *,
        session: AsyncSession,
        extraction_file_id: int,
        student: GeminiStudent,
    ) -> Any:
        numeric_student_id = self._parse_numeric_identifier(
            student.student_id
        )

        # The mirrored student table requires a non-null integer s_id. When the
        # transcript does not contain a reliable numeric student ID, use the
        # extraction-file ID only as an internal surrogate and keep the file in
        # needs_review through _student_review_reasons().
        stored_student_id = (
            numeric_student_id
            if numeric_student_id is not None
            else extraction_file_id
        )

        row = NewTranscriptStudents(
            s_id=stored_student_id,
            s_name=self._student_display_name(student),
            s_address=self._clean_text(student.address),
            s_phone_number=self._clean_text(student.phone_number),
            s_gender=self._clean_text(student.gender),
            s_date_of_birth=self._parse_date(student.date_of_birth),
            s_state_id=self._parse_numeric_identifier(student.state_id),
            hs_name=self._clean_text(student.primary_school_name)
            or "Unknown School",
            hs_counselor_name=self._clean_text(student.counselor_name),
            hs_grade=student.current_grade_level,
            hs_total_units_earned=student.total_units_earned,
            hs_total_gpa_course=student.total_gpa_course,
            hs_aca_gpa_course=student.academic_gpa_course,
            hs_university_gpa=student.university_gpa,
            hs_enter_date=self._parse_date(student.enter_date),
            # The current isolated table has no district_name or
            # graduation_year-only text column. Do not invent a date from a
            # visible year; preserve only a complete, reliable date here.
            hs_graduation_date=self._parse_date(student.graduation_date),
            source_file=extraction_file_id,
        )

        session.add(row)
        await session.flush()
        return row

    async def _create_course(
        self,
        *,
        session: AsyncSession,
        extraction_file_id: int,
        student_pk: int,
        course: GeminiCourse,
        transcript_school: str | None,
        grade_level: int | None,
        year: int | None,
        month: int | None,
        block_term_gpa: float | None,
    ) -> Any:
        row = NewTranscriptCourseDetails(
            s_id=student_pk,
            source_file=extraction_file_id,
            crs_id=self._clean_text(course.course_id_raw),
            crs_letter_grade=self._clean_text(course.grade),
            crs_description=self._clean_text(course.course_name),
            crs_hs=self._clean_text(transcript_school),
            crs_grade=grade_level,
            crs_month=month,
            crs_year=year,
            crs_credit_attempted=course.credit_attempted,
            crs_credit_completed=course.credit_completed,
            crs_term_gpa=block_term_gpa,
        )

        session.add(row)
        await session.flush()
        return row

    # ------------------------------------------------------------------
    # Validation and review routing
    # ------------------------------------------------------------------

    def _normalise_transcript_structure(
        self,
        transcript: GeminiTranscript,
    ) -> bool:
        """
        Normalize only bookkeeping fields such as list order and sequential
        indexes. Real student/course values are never changed here.

        Gemini sometimes returns valid rows in a different JSON list order or
        with count/index metadata that does not exactly match the list. Those
        harmless formatting issues should route the file to Audit rather than
        discarding otherwise usable transcript rows as a failed extraction.
        """
        if transcript.document_type != "high_school_transcript":
            return False

        changed = False
        original_blocks = list(transcript.blocks)
        original_courses = list(transcript.courses)

        old_block_indexes = [block.block_index for block in original_blocks]
        if len(old_block_indexes) != len(set(old_block_indexes)):
            raise ValueError(
                "Gemini returned duplicate block_index values; course-to-block "
                "relationships are ambiguous."
            )

        ordered_blocks = sorted(
            original_blocks,
            key=lambda block: (
                block.page_number,
                block.visual_column,
                block.block_index,
            ),
        )
        if ordered_blocks != original_blocks:
            changed = True

        old_to_new_block_index: dict[int, int] = {}
        for new_index, block in enumerate(ordered_blocks, start=1):
            old_to_new_block_index[block.block_index] = new_index

        ordered_courses = sorted(
            original_courses,
            key=lambda course: (
                course.page_number,
                course.visual_column,
                course.row_index,
            ),
        )
        if ordered_courses != original_courses:
            changed = True

        for block in ordered_blocks:
            new_index = old_to_new_block_index[block.block_index]
            if block.block_index != new_index:
                changed = True
            block.block_index = new_index

        courses_by_block: dict[int, list[GeminiCourse]] = {
            block.block_index: []
            for block in ordered_blocks
        }

        for new_row_index, course in enumerate(ordered_courses, start=1):
            old_block_index = course.block_index
            if old_block_index not in old_to_new_block_index:
                raise ValueError(
                    "Gemini course references missing block_index="
                    f"{old_block_index}"
                )

            new_block_index = old_to_new_block_index[old_block_index]
            if course.block_index != new_block_index:
                changed = True
            course.block_index = new_block_index

            if course.row_index != new_row_index:
                changed = True
            course.row_index = new_row_index
            courses_by_block[new_block_index].append(course)

        for block in ordered_blocks:
            block_courses = courses_by_block[block.block_index]
            for row_in_block, course in enumerate(block_courses, start=1):
                if course.row_in_block != row_in_block:
                    changed = True
                course.row_in_block = row_in_block

            if block.course_row_count != len(block_courses):
                changed = True
            block.course_row_count = len(block_courses)

        if transcript.total_course_count != len(ordered_courses):
            changed = True
        transcript.total_course_count = len(ordered_courses)
        transcript.blocks = ordered_blocks
        transcript.courses = ordered_courses

        if changed:
            warning = (
                "Gemini structural order/count metadata was normalized; "
                "send this transcript to Human Review with Audit."
            )
            if warning not in transcript.extraction_warnings:
                transcript.extraction_warnings.append(warning)

        return changed

    def _validate_transcript_structure(
        self,
        transcript: GeminiTranscript,
    ) -> None:
        if transcript.document_type != "high_school_transcript":
            if transcript.courses or transcript.blocks:
                raise ValueError(
                    "A non-transcript response must not contain course rows "
                    "or course blocks."
                )
            if transcript.total_course_count != 0:
                raise ValueError(
                    "A non-transcript response must have "
                    "total_course_count=0."
                )
            return

        if transcript.total_course_count != len(transcript.courses):
            raise ValueError(
                "Gemini course count mismatch: "
                f"declared={transcript.total_course_count}, "
                f"actual={len(transcript.courses)}"
            )

        block_indexes = [block.block_index for block in transcript.blocks]
        if len(block_indexes) != len(set(block_indexes)):
            raise ValueError("Gemini returned duplicate block_index values.")

        expected_block_indexes = list(
            range(1, len(transcript.blocks) + 1)
        )
        if block_indexes != expected_block_indexes:
            raise ValueError(
                "Gemini block_index values must be sequential from 1: "
                f"received={block_indexes}"
            )

        expected_row_indexes = list(
            range(1, len(transcript.courses) + 1)
        )
        actual_row_indexes = [
            course.row_index
            for course in transcript.courses
        ]
        if actual_row_indexes != expected_row_indexes:
            raise ValueError(
                "Gemini row_index values must be sequential from 1: "
                f"received={actual_row_indexes}"
            )

        courses_by_block: dict[int, list[GeminiCourse]] = {
            block.block_index: []
            for block in transcript.blocks
        }

        for course in transcript.courses:
            if course.block_index not in courses_by_block:
                raise ValueError(
                    "Gemini course references missing block_index="
                    f"{course.block_index}"
                )
            courses_by_block[course.block_index].append(course)

        for block in transcript.blocks:
            block_courses = courses_by_block[block.block_index]
            if block.course_row_count != len(block_courses):
                raise ValueError(
                    "Gemini block count mismatch for block "
                    f"{block.block_index}: "
                    f"declared={block.course_row_count}, "
                    f"actual={len(block_courses)}"
                )

            expected_rows_in_block = list(
                range(1, len(block_courses) + 1)
            )
            actual_rows_in_block = [
                course.row_in_block
                for course in block_courses
            ]
            if actual_rows_in_block != expected_rows_in_block:
                raise ValueError(
                    "Gemini row_in_block values must be sequential for "
                    f"block {block.block_index}: "
                    f"received={actual_rows_in_block}"
                )

    def _student_review_reasons(
        self,
        student: GeminiStudent,
    ) -> list[str]:
        reasons: list[str] = []

        if not self._student_name_from_pdf(student):
            reasons.append("Student name is missing")

        if not self._clean_text(student.primary_school_name):
            reasons.append("Primary school name is missing")

        if self._parse_numeric_identifier(student.student_id) is None:
            reasons.append(
                "A reliable numeric student ID is missing"
            )

        if student.uncertain_fields:
            reasons.append(
                "Uncertain student fields: "
                + ", ".join(student.uncertain_fields)
            )

        if (
            self._normalise_confidence(
                student.extraction_confidence
            )
            < self.auto_resolve_confidence
        ):
            reasons.append(
                "Student extraction confidence is below the "
                "auto-complete threshold"
            )

        return list(dict.fromkeys(reasons))

    def _student_audit_reasons(
        self,
        student: GeminiStudent,
    ) -> list[str]:
        """
        Return only issues serious enough to require the PDF beside the form.

        Minor uncertainty belongs in normal Human Review. Missing identity,
        missing school context, unsupported/non-preservable student IDs, or
        confidence below the audit threshold requires Human Review with Audit.
        """
        reasons: list[str] = []

        if not self._student_name_from_pdf(student):
            reasons.append("Student identity is missing")

        if not self._clean_text(student.primary_school_name):
            reasons.append("Primary school context is missing")

        if self._parse_numeric_identifier(student.student_id) is None:
            reasons.append(
                "Student ID cannot be safely preserved in the current "
                "integer database column"
            )

        critical_uncertain_fields = {
            "full_name",
            "first_name",
            "last_name",
            "student_id",
            "primary_school_name",
        }
        uncertain_critical = sorted(
            critical_uncertain_fields.intersection(
                set(student.uncertain_fields)
            )
        )
        if uncertain_critical:
            reasons.append(
                "Critical student fields are uncertain: "
                + ", ".join(uncertain_critical)
            )

        if (
            self._normalise_confidence(student.extraction_confidence)
            < self.audit_confidence
        ):
            reasons.append(
                "Student extraction confidence is below the audit threshold"
            )

        return list(dict.fromkeys(reasons))

    def _course_review_reasons(
        self,
        *,
        course: GeminiCourse,
        transcript_school: str | None,
        effective_grade_level: int | None,
        effective_year: int | None,
        effective_month: int | None,
        confidence: float,
    ) -> list[str]:
        reasons: list[str] = []

        missing_fields = self._missing_required_course_fields(
            course=course,
            transcript_school=transcript_school,
            effective_grade_level=effective_grade_level,
            effective_year=effective_year,
            effective_month=effective_month,
        )
        if missing_fields:
            reasons.append(
                "Missing required fields: "
                + ", ".join(missing_fields)
            )

        if course.uncertain_fields:
            reasons.append(
                "Gemini marked uncertain fields: "
                + ", ".join(course.uncertain_fields)
            )

        if course.review_reason:
            reasons.append(course.review_reason)

        if confidence < self.auto_resolve_confidence:
            reasons.append(
                f"Course confidence {confidence:.2f} is below "
                f"{self.auto_resolve_confidence:.2f}"
            )

        low_confidence_fields = self._low_confidence_fields(course)
        if low_confidence_fields:
            reasons.append(
                "Low-confidence fields: "
                + ", ".join(low_confidence_fields)
            )

        return list(dict.fromkeys(reasons))

    def _missing_required_course_fields(
        self,
        *,
        course: GeminiCourse,
        transcript_school: str | None,
        effective_grade_level: int | None,
        effective_year: int | None,
        effective_month: int | None,
    ) -> list[str]:
        # Course ID and month are not universal. A semester matrix may have no
        # Course ID column, and some transcript formats do not show a month.
        required_values = {
            "course_name": course.course_name,
            "grade": course.grade,
            "school_name": transcript_school,
            "grade_level": effective_grade_level,
            "year": effective_year,
            "credit_attempted": course.credit_attempted,
            "credit_completed": course.credit_completed,
        }

        missing: list[str] = []
        for field_name, value in required_values.items():
            if value is None:
                missing.append(field_name)
            elif isinstance(value, str) and not value.strip():
                missing.append(field_name)

        return missing

    def _low_confidence_fields(
        self,
        course: GeminiCourse,
    ) -> list[str]:
        values = course.field_confidence.model_dump()
        ignored_fields: set[str] = set()

        if (
            course.layout_family == "semester_matrix"
            and course.course_id_raw is None
        ):
            ignored_fields.add("course_id_raw")

        if (
            course.month_source == "not_available"
            and course.month is None
        ):
            ignored_fields.add("month")

        return sorted(
            field_name
            for field_name, confidence in values.items()
            if (
                field_name not in ignored_fields
                and confidence < self.auto_resolve_confidence
            )
        )

    def _determine_review_bucket(
        self,
        *,
        transcript: GeminiTranscript,
        created_courses: int,
        unresolved_courses: int,
        student_needs_review: bool,
        student_audit_required: bool,
        average_confidence: float,
        structure_was_normalised: bool,
    ) -> str:
        """
        Enforce the product rule for Gemini-only transcript types.

        This service is used only for transcripts routed from the classified
        Others path. Those transcripts must never enter Auto Complete directly,
        even when Gemini confidence is high and every required field is present.

        The extracted student and course data is still saved normally, and all
        validation/confidence calculations remain available for the review UI.
        A user may move the file to Completed only through the explicit review
        completion endpoint.
        """
        del (
            transcript,
            created_courses,
            unresolved_courses,
            student_needs_review,
            student_audit_required,
            average_confidence,
            structure_was_normalised,
        )

        return "human_review_with_audit"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_course_context(
        self,
        *,
        course: GeminiCourse,
        block: GeminiBlock,
    ) -> tuple[int | None, int | None, int | None, list[str]]:
        """
        Keep grade level, year, and month from one section context.

        The block is the canonical context whenever it contains any context
        value. Missing block fields remain null rather than being filled from
        a potentially different row-level source. Row-level context is used
        only when the block has no grade/year/month context at all.
        """
        block_context = (
            block.grade_level,
            block.year,
            block.month,
        )
        course_context = (
            course.grade_level,
            course.year,
            course.month,
        )

        reasons: list[str] = []
        context_names = ("grade_level", "year", "month")

        for field_name, course_value, block_value in zip(
            context_names,
            course_context,
            block_context,
        ):
            if (
                course_value is not None
                and block_value is not None
                and course_value != block_value
            ):
                reasons.append(
                    f"{field_name} conflicts with the referenced block"
                )

        if any(value is not None for value in block_context):
            return (
                block.grade_level,
                block.year,
                block.month,
                reasons,
            )

        return (
            course.grade_level,
            course.year,
            course.month,
            reasons,
        )

    def _resolve_course_school(
        self,
        *,
        course: GeminiCourse,
        block: GeminiBlock,
        student: GeminiStudent,
    ) -> str | None:
        return (
            self._clean_text(course.school_name)
            or self._clean_text(block.school_name)
            or self._clean_text(student.primary_school_name)
        )

    def _student_name_from_pdf(
        self,
        student: GeminiStudent,
    ) -> str | None:
        full_name = self._clean_text(student.full_name)
        if full_name:
            return full_name

        parts = [
            self._clean_text(student.first_name),
            self._clean_text(student.middle_name),
            self._clean_text(student.last_name),
        ]
        combined = " ".join(part for part in parts if part)
        return combined or None

    def _student_display_name(
        self,
        student: GeminiStudent,
    ) -> str:
        return self._student_name_from_pdf(student) or "Unknown Student"

    def _parse_numeric_identifier(
        self,
        value: str | None,
    ) -> int | None:
        cleaned = self._clean_text(value)
        if not cleaned or not cleaned.isdigit():
            return None

        # The current database column is integer-based. Converting a visible
        # identifier such as "001234" to 1234 would silently change the
        # transcript value, so reject it and route the file to Audit instead.
        if len(cleaned) > 1 and cleaned.startswith("0"):
            return None

        try:
            return int(cleaned)
        except ValueError:
            return None

    def _parse_date(
        self,
        value: str | None,
    ) -> date | None:
        cleaned = self._clean_text(value)
        if not cleaned:
            return None
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            return None

    def _clean_text(
        self,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _normalise_confidence(
        self,
        value: float | int | None,
    ) -> float:
        if value is None:
            return 0.0
        return max(0.0, min(1.0, float(value)))

    def _set_processed_date(
        self,
        extraction_file: Any,
    ) -> None:
        if "processed_date" in extraction_file.__table__.columns.keys():
            extraction_file.processed_date = datetime.now(timezone.utc)
