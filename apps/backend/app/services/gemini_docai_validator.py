"""
Validate Document AI rows with Gemini (anchored — no hallucination).

On scanned-image transcripts, the plain OCR (Document AI) gives a RELIABLE row
count: it transcribes what it sees and never "continues a pattern" into phantom
rows the way a generative model does. (Verified on a real transcript: Doc AI read
the correct 53 rows; independent Gemini hallucinated up to 59.)

So Document AI owns the row SET, and Gemini is used only to VALIDATE/CORRECT the
VALUES (course id, grade, credits) of each existing row by looking at the page
image. Gemini is handed the exact rows Document AI found and told to return
EXACTLY those rows, in order, with corrected values — it cannot add or drop rows,
so it cannot invent extra courses. The result keeps Document AI's count with
Gemini-checked values.

Returns the same shape as gemini_course_extractor.run_gemini_course_extraction so
it is a drop-in for the Gemini step. Any hard failure raises so the caller can
fall back to independent extraction.
"""

from __future__ import annotations

import json
import os
from typing import Any

import fitz  # pymupdf
from google.genai import types

from app.services.gemini_course_extractor import (
    _make_gemini_client,
    _resolve_gemini_model,
    _safe_json_loads,
)
from app.services.gemini_rate_limit import generate_content_limited


def docai_validation_enabled() -> bool:
    return str(os.getenv("GEMINI_VALIDATE_DOCAI", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _render_dpi() -> int:
    try:
        return max(120, min(400, int(os.getenv("GEMINI_VALIDATE_DPI", "220"))))
    except (TypeError, ValueError):
        return 220


VALIDATION_PROMPT = """
You are validating a high school transcript extraction.

An OCR system (Document AI) already extracted the course rows below from the
attached transcript image(s). Look at the image and CORRECT any misread value for
each row — course title, course id, grade/mark, attempted credits, completed
credits.

CRITICAL RULES:
1. Return EXACTLY {n} rows, identified by their "i" index, in the same order.
2. Do NOT add rows. Do NOT remove rows. Do NOT merge or split rows. The count
   must stay exactly {n}. (Fall and Spring of the same course are two real rows —
   keep both.)
3. For each row, read its title, course id, grade, and credits from the SAME
   printed row in the image. If the OCR value already matches the image, return it
   unchanged.
4. Read the course id exactly as printed (e.g. "P 2986", "HP 1449", "8501").
   Do not invent or increment ids. Read the grade as a single mark (A, B, C, ...).
5. Read the course TITLE in normal human reading order, left-to-right. The OCR
   often scrambles titles that wrap onto a second line (e.g. it returns
   "Engineering (PLTW) Honors Principles of" when the real title is
   "Honors Principles of Engineering (PLTW)"). Return the correctly-ordered title.
6. If a value is genuinely unreadable, return null for that field only.

Document AI rows (JSON):
{rows}

Return ONLY JSON in exactly this shape, no markdown:
{{"rows": [{{"i": 0, "course_title": "Algebra 1", "course_id": "P 2986", "grade": "A", "credit_attempted": 5.0, "credit_completed": 5.0}}]}}
"""


def course_count_cross_check_enabled() -> bool:
    return str(os.getenv("GEMINI_COUNT_CROSS_CHECK", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


COUNT_PROMPT = """
You are an independent counter for a high school transcript. Your ONLY job is to
count course rows — do NOT extract values.

The transcript is organized into TERM BLOCKS. Each block has a header such as
"Yr: 2023  Month: 1  Grade: 10" followed by its course rows. A course row has a
course ID (e.g. P 2986, HP 1449) and a grade.

Instructions:
1. Go block by block. For EACH block, count how many course rows it contains.
2. Count Fall and Spring as separate blocks/rows — the same course in two terms
   is two rows.
3. Count every course row across all pages.
4. Be precise: do not skip rows, do not invent rows.

Return ONLY JSON, no markdown:
{"blocks": [{"term": "2023 M1 G10", "count": 7}], "total": 53}
"""


def count_courses_with_gemini(
    pdf_bytes: bytes,
    *,
    model_name: str | None = None,
) -> int | None:
    """Independent course-row count (per-block, then summed). Returns None on any
    failure. Used to catch Document AI *under*-counting (missed rows)."""
    try:
        page_parts = _render_pages(pdf_bytes)
        if not page_parts:
            return None
        client = _make_gemini_client()
        resolved_model = model_name or _resolve_gemini_model()
        response = generate_content_limited(
            client,
            model=resolved_model,
            contents=[*page_parts, COUNT_PROMPT],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        parsed = _safe_json_loads(response.text or "")
        if not isinstance(parsed, dict):
            return None
        # Prefer summing the per-block counts (more reliable than a single total),
        # fall back to the reported total.
        blocks = parsed.get("blocks")
        if isinstance(blocks, list) and blocks:
            summed = 0
            ok = False
            for b in blocks:
                if isinstance(b, dict) and isinstance(b.get("count"), int):
                    summed += b["count"]
                    ok = True
            if ok:
                return summed
        total = parsed.get("total")
        return int(total) if isinstance(total, (int, float)) else None
    except Exception:  # noqa: BLE001
        return None


def _render_pages(pdf_bytes: bytes) -> list[Any]:
    """Render every page to a PNG image Part for Gemini."""
    parts: list[Any] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        zoom = _render_dpi() / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            parts.append(
                types.Part.from_bytes(data=pix.tobytes("png"), mime_type="image/png")
            )
    finally:
        doc.close()
    return parts


def _docai_row_reference(docai_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ref: list[dict[str, Any]] = []
    for i, r in enumerate(docai_rows):
        ref.append(
            {
                "i": i,
                "course_id": r.get("course_id"),
                "course_title": r.get("course_title") or r.get("course_name") or r.get("title"),
                "grade": r.get("course_mark") or r.get("grade") or r.get("mark"),
                "credit_attempted": r.get("credit_attempted"),
                "credit_completed": r.get("credit_completed"),
                "year": r.get("term_year") or r.get("year"),
                "month": r.get("term_month") or r.get("month"),
                "grade_level": r.get("term_grade") or r.get("grade_level"),
            }
        )
    return ref


def _to_gemini_course(docai_row: dict[str, Any], corrected: dict[str, Any] | None) -> dict[str, Any]:
    """Build a Gemini-shaped course = Document AI row with validated values."""
    def pick(corr_key: str, *docai_keys: str) -> Any:
        if corrected and corrected.get(corr_key) not in (None, ""):
            return corrected.get(corr_key)
        for k in docai_keys:
            v = docai_row.get(k)
            if v not in (None, ""):
                return v
        return None

    return {
        "course_id": pick("course_id", "course_id"),
        "course_name": pick("course_title", "course_title", "course_name", "title"),
        "grade": pick("grade", "course_mark", "grade", "mark"),
        "credit_attempted": pick("credit_attempted", "credit_attempted"),
        "credit_completed": pick("credit_completed", "credit_completed"),
        "grade_level": docai_row.get("term_grade") or docai_row.get("grade_level"),
        "month": docai_row.get("term_month") or docai_row.get("month"),
        "year": docai_row.get("term_year") or docai_row.get("year"),
        "school": docai_row.get("term_school_name") or docai_row.get("school"),
        "raw_payload": {"backend_docai_validated": bool(corrected)},
    }


def validate_docai_rows_with_gemini(
    *,
    docai_rows: list[dict[str, Any]],
    pdf_bytes: bytes,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Validate Document AI rows with Gemini. Drop-in for run_gemini_course_extraction.

    Raises on hard failure so the caller can fall back to independent extraction.
    The returned course count ALWAYS equals len(docai_rows) (Doc AI owns the count).
    """
    if not docai_rows:
        raise RuntimeError("Doc-AI validation: no Document AI rows to validate.")

    client = _make_gemini_client()
    resolved_model = model_name or _resolve_gemini_model()

    page_parts = _render_pages(pdf_bytes)
    if not page_parts:
        raise RuntimeError("Doc-AI validation: could not render transcript pages.")

    ref = _docai_row_reference(docai_rows)
    prompt = VALIDATION_PROMPT.format(n=len(ref), rows=json.dumps(ref, ensure_ascii=False))

    response = generate_content_limited(
        client,
        model=resolved_model,
        contents=[*page_parts, prompt],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    parsed = _safe_json_loads(response.text or "")
    corrected_by_i: dict[int, dict[str, Any]] = {}
    if isinstance(parsed, dict):
        for row in parsed.get("rows") or []:
            if isinstance(row, dict) and isinstance(row.get("i"), int):
                corrected_by_i[row["i"]] = row

    # Count is anchored to Document AI; we only ever apply value corrections.
    courses = [
        _to_gemini_course(docai_row, corrected_by_i.get(i))
        for i, docai_row in enumerate(docai_rows)
    ]
    applied = sum(1 for c in courses if c["raw_payload"]["backend_docai_validated"])

    return {
        "status": "completed",
        "courses": courses,
        "course_count": len(courses),
        "total_course_count": len(courses),
        "gemini_reported_total_course_count": len(courses),
        "model": resolved_model,
        "parser_warnings": [],
        "raw_gemini_json": None,
        "raw_response": None,
        "error": None,
        "raw_result_keys": "docai_validation",
        "extraction_mode": "docai_validation",
        "docai_rows": len(docai_rows),
        "values_corrected": applied,
    }
