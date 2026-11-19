"""
Block-level chunked Gemini extraction (anti-hallucination).

Gemini hallucinates rows *deterministically* on dense full-page transcript
tables — at temperature 0 it "continues a sequence" into fabricated rows (e.g.
inventing P 1083, P 1084, P 1085 after a real P 1082). Because the input and
decoding are fixed, the same hallucination repeats on every run.

This module limits Gemini's scope. It uses transcript_row_geometry (deterministic
PyMuPDF text positions — neither Doc AI nor Gemini) only to locate the visual
term-blocks, renders each block as its own small image, and asks Gemini to
extract ONLY that block. On a small bounded region there is no long table to
over-pattern, so both the row count and the values become reliable. Every block's
courses are consolidated into one list. Gemini remains the authority for counts
and values; geometry just says where the blocks/rows are.

Optional per-row value check (row_crop_verifier): each row is cropped to a single
isolated image and Gemini re-reads its grade, which then becomes the course grade
(a single-row crop cannot be confused by adjacent rows).

Returns the SAME shape as gemini_course_extractor.run_gemini_course_extraction so
it is a drop-in for the extraction step. Any failure raises, so the caller can
fall back to the full-PDF extractor.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from google.genai import types

from app.services.transcript_row_geometry import extract_transcript_row_geometry
from app.services.gemini_course_extractor import (
    _make_gemini_client,
    _resolve_gemini_model,
    _safe_json_loads,
)
from app.services.gemini_rate_limit import generate_content_limited
from app.services.row_crop_verifier import (
    crop_pdf_row_to_png_bytes,
    expand_transcript_row_bbox_to_table_width,
)


# ---------------------------------------------------------------------------
# Tuning (all env-overridable)
# ---------------------------------------------------------------------------
def block_chunked_extraction_enabled() -> bool:
    return str(os.getenv("GEMINI_BLOCK_CHUNKED_EXTRACTION", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def block_row_crop_grade_enabled() -> bool:
    return str(os.getenv("GEMINI_BLOCK_ROW_CROP_GRADE", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _block_worker_count() -> int:
    try:
        return max(1, min(8, int(os.getenv("GEMINI_BLOCK_WORKERS", "4"))))
    except (TypeError, ValueError):
        return 4


def _row_crop_worker_count() -> int:
    try:
        return max(1, min(8, int(os.getenv("GEMINI_ROW_CROP_WORKERS", "6"))))
    except (TypeError, ValueError):
        return 6


GEMINI_BLOCK_EXTRACTION_PROMPT = """
You are reading ONE small block of a high school transcript. This image shows
only the course rows of a single term/grade block — a few rows at most.

Return ONLY valid JSON. No markdown, no explanation.

Rules:
1. Extract EVERY course row that is actually visible in THIS image, and ONLY
   those rows. Do not add rows that are not visible.
2. NEVER invent or increment a course ID. Read each course ID exactly as printed
   (examples: "P 2986", "HP 1449", "N 3635", "8501", "CC006"). If two rows look
   similar, read each one's printed ID separately — do not assume a sequence.
3. Read the Mark/Grade from the SAME horizontal row as the course. Do not borrow
   a grade from the row above or below.
4. Read attempted/completed credits as printed. If a cell is blank, use null.
5. Count only the rows you can actually see.

Return JSON in exactly this shape:
{
  "courses": [
    {
      "course_id": "P 2986",
      "course_name": "Algebra 1",
      "grade": "B",
      "credit_attempted": 5.0,
      "credit_completed": 5.0
    }
  ]
}
"""


GEMINI_ROW_GRADE_CROP_PROMPT = """
This image is ONE cropped course row from a high school transcript.

Return ONLY valid JSON. No markdown.

Read the Mark/Grade from THIS row only. Do not use any other row.
If the grade cell is unclear, return grade=null.

Return: {"grade": "B"}
"""


# ---------------------------------------------------------------------------
# Block grouping
# ---------------------------------------------------------------------------
def _group_geometry_rows_into_blocks(
    geometry_rows: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group geometry rows into visual term-blocks.

    A block = contiguous rows in the same column, page and term-block index
    (i.e. under the same section header). Order is preserved.
    """
    blocks: dict[tuple, list[dict[str, Any]]] = {}
    order: list[tuple] = []

    for row in geometry_rows:
        key = (
            row.get("page_number"),
            row.get("column_index"),
            row.get("block_index"),
            row.get("section_key"),
        )
        if key not in blocks:
            blocks[key] = []
            order.append(key)
        blocks[key].append(row)

    return [blocks[k] for k in order]


def _block_region_bbox(
    block_rows: list[dict[str, Any]],
) -> tuple[float, float, float, float] | None:
    """Normalized (x1, y1, x2, y2) covering a block, widened to the full column
    and padded a little vertically so every row reads cleanly."""
    boxes = [r.get("row_bbox") for r in block_rows if r.get("row_bbox")]
    if not boxes:
        return None

    y1 = min(b[1] for b in boxes)
    y2 = max(b[3] for b in boxes)

    column = block_rows[0].get("visual_column")
    widened = expand_transcript_row_bbox_to_table_width(
        row_bbox=(min(b[0] for b in boxes), y1, max(b[2] for b in boxes), y2),
        column=column,
    )
    x1, _, x2, _ = widened

    pad = 0.008
    return (
        max(0.0, x1),
        max(0.0, y1 - pad),
        min(1.0, x2),
        min(1.0, y2 + pad),
    )


def _attach_block_context(course: dict[str, Any], ctx_row: dict[str, Any]) -> None:
    """Copy the block's deterministic term context onto an extracted course."""
    course.setdefault("grade_level", ctx_row.get("grade_level"))
    course.setdefault("year", ctx_row.get("year"))
    course.setdefault("month", ctx_row.get("month"))
    course.setdefault("section_name", ctx_row.get("section_name"))
    course.setdefault("term_name", ctx_row.get("term_name"))
    course.setdefault("school", ctx_row.get("school_name"))
    course.setdefault("crs_hs", ctx_row.get("school_name"))


# ---------------------------------------------------------------------------
# Per-block extraction
# ---------------------------------------------------------------------------
def _extract_one_block(
    *,
    client: Any,
    model_name: str,
    pdf_bytes: bytes,
    block_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    region = _block_region_bbox(block_rows)
    page_number = block_rows[0].get("page_number") or 1
    if region is None:
        return []

    png = crop_pdf_row_to_png_bytes(
        pdf_bytes=pdf_bytes,
        page_number=int(page_number),
        bbox=region,
        pad_x=0.0,
        pad_y=0.0,
    )

    image_part = types.Part.from_bytes(data=png, mime_type="image/png")
    response = generate_content_limited(
        client,
        model=model_name,
        contents=[image_part, GEMINI_BLOCK_EXTRACTION_PROMPT],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )
    raw_json = _safe_json_loads(response.text or "")

    courses = raw_json.get("courses") if isinstance(raw_json, dict) else None
    if not isinstance(courses, list):
        return []

    ctx_row = block_rows[0]
    cleaned: list[dict[str, Any]] = []
    for c in courses:
        if not isinstance(c, dict):
            continue
        course = {
            "course_id": c.get("course_id") or c.get("crs_id"),
            "course_name": c.get("course_name") or c.get("title") or c.get("name"),
            "grade": c.get("grade") or c.get("mark") or c.get("letter_grade"),
            "credit_attempted": c.get("credit_attempted"),
            "credit_completed": c.get("credit_completed"),
            "raw_payload": {"backend_block_extraction": True},
        }
        _attach_block_context(course, ctx_row)
        cleaned.append(course)
    return cleaned


# ---------------------------------------------------------------------------
# Optional per-row grade crop verification
# ---------------------------------------------------------------------------
def _norm_grade(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def _verify_row_grade(
    *,
    client: Any,
    model_name: str,
    pdf_bytes: bytes,
    geometry_row: dict[str, Any],
) -> str | None:
    bbox = geometry_row.get("row_bbox")
    page_number = geometry_row.get("page_number") or 1
    if not bbox:
        return None

    expanded = expand_transcript_row_bbox_to_table_width(
        row_bbox=tuple(bbox),
        column=geometry_row.get("visual_column"),
    )
    png = crop_pdf_row_to_png_bytes(
        pdf_bytes=pdf_bytes,
        page_number=int(page_number),
        bbox=expanded,
    )
    image_part = types.Part.from_bytes(data=png, mime_type="image/png")
    parsed = _safe_json_loads(
        (
            generate_content_limited(
                client,
                model=model_name,
                contents=[image_part, GEMINI_ROW_GRADE_CROP_PROMPT],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            ).text
            or ""
        )
    )
    if isinstance(parsed, dict):
        grade = parsed.get("grade")
        if grade not in (None, ""):
            return str(grade).strip()
    return None


def _apply_row_crop_grades(
    *,
    client: Any,
    model_name: str,
    pdf_bytes: bytes,
    blocks: list[list[dict[str, Any]]],
    block_courses: list[list[dict[str, Any]]],
) -> int:
    """For each block whose Gemini course count matches the geometry row count,
    re-read each row's grade from an isolated crop and use it as the grade.
    Mismatched blocks are skipped (alignment is ambiguous)."""
    jobs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for geo_rows, courses in zip(blocks, block_courses):
        if len(geo_rows) != len(courses) or not courses:
            continue
        for geo_row, course in zip(geo_rows, courses):
            # Only spend a crop call where the block read and the deterministic
            # geometry read DISAGREE on the grade (or one is missing). Agreement
            # is high confidence and needs no extra verification — this cuts the
            # per-row crop calls (and RPM/cost) by ~90% on a typical transcript.
            block_grade = _norm_grade(course.get("grade"))
            geo_grade = _norm_grade(geo_row.get("grade"))
            if block_grade and geo_grade and block_grade == geo_grade:
                continue
            jobs.append((geo_row, course))

    if not jobs:
        return 0

    applied = 0
    with ThreadPoolExecutor(max_workers=_row_crop_worker_count()) as executor:
        futures = {
            executor.submit(
                _verify_row_grade,
                client=client,
                model_name=model_name,
                pdf_bytes=pdf_bytes,
                geometry_row=geo_row,
            ): course
            for geo_row, course in jobs
        }
        for future in as_completed(futures):
            course = futures[future]
            try:
                grade = future.result()
            except Exception:  # noqa: BLE001
                grade = None
            if grade is not None:
                rp = course.get("raw_payload")
                if not isinstance(rp, dict):
                    rp = {}
                rp["backend_row_crop_grade"] = grade
                rp["backend_row_crop_grade_applied"] = True
                course["raw_payload"] = rp
                course["grade"] = grade
                applied += 1
    return applied


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def run_gemini_block_chunked_extraction(
    *,
    pdf_bytes: bytes,
    transcript_format: str | None = None,
    model_name: str | None = None,
    run_row_crop_grade: bool | None = None,
) -> dict[str, Any]:
    """Block-chunked Gemini extraction. Drop-in for run_gemini_course_extraction.

    Raises on hard failure so the caller can fall back to the full-PDF extractor.
    """
    geometry_rows = extract_transcript_row_geometry(pdf_bytes=pdf_bytes)
    if not geometry_rows:
        raise RuntimeError(
            "Block-chunked extraction: transcript_row_geometry found no rows."
        )

    blocks = _group_geometry_rows_into_blocks(geometry_rows)
    if not blocks:
        raise RuntimeError("Block-chunked extraction: no blocks grouped.")

    client = _make_gemini_client()
    resolved_model = model_name or _resolve_gemini_model()

    # Extract every block (in parallel — each is a small, fast call).
    block_courses: list[list[dict[str, Any]]] = [[] for _ in blocks]
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=_block_worker_count()) as executor:
        futures = {
            executor.submit(
                _extract_one_block,
                client=client,
                model_name=resolved_model,
                pdf_bytes=pdf_bytes,
                block_rows=block_rows,
            ): idx
            for idx, block_rows in enumerate(blocks)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                block_courses[idx] = future.result()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Block {idx} extraction failed: {exc}")
                block_courses[idx] = []

    # Optional per-row grade crop verification.
    run_crops = (
        block_row_crop_grade_enabled()
        if run_row_crop_grade is None
        else run_row_crop_grade
    )
    row_crop_applied = 0
    if run_crops:
        try:
            row_crop_applied = _apply_row_crop_grades(
                client=client,
                model_name=resolved_model,
                pdf_bytes=pdf_bytes,
                blocks=blocks,
                block_courses=block_courses,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Row-crop grade verification failed: {exc}")

    courses: list[dict[str, Any]] = [c for block in block_courses for c in block]

    # Geometry gives a deterministic row count; use it as a sanity cross-check.
    geometry_row_count = len(geometry_rows)
    gemini_count = len(courses)
    if geometry_row_count and gemini_count > geometry_row_count * 1.5:
        warnings.append(
            f"Block extraction produced {gemini_count} rows vs geometry's "
            f"{geometry_row_count}; possible over-extraction."
        )

    return {
        "status": "completed" if courses else "needs_review",
        "courses": courses,
        "course_count": gemini_count,
        "total_course_count": gemini_count,
        "gemini_reported_total_course_count": gemini_count,
        "model": resolved_model,
        "parser_warnings": warnings,
        "raw_gemini_json": None,
        "raw_response": None,
        "error": None if courses else "Block-chunked extraction produced no rows.",
        "raw_result_keys": "block_chunked",
        "extraction_mode": "block_chunked",
        "block_count": len(blocks),
        "geometry_row_count": geometry_row_count,
        "row_crop_grades_applied": row_crop_applied,
    }
