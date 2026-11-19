"""
Row crop verifier for transcript course rows.

Purpose:
- Render a PDF page as a high-resolution image.
- Crop one course row / row band.
- Send that crop to Gemini as an image.
- Ask Gemini to verify the grade from the SAME horizontal row only.

This is especially useful for LBUSD-style and Mayfair-style transcripts where
Gemini sometimes reads the Mark/grade from the row above or below.
"""

from __future__ import annotations

import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import fitz  # pymupdf
from PIL import Image
from google import genai
from google.genai import types


ROW_GRADE_VERIFY_PROMPT = """
You are verifying ONE cropped course row from a high school transcript.

Use ONLY this cropped row image.
Return ONLY valid JSON. No markdown. No explanation.

Critical rules:
1. This image contains one course row, possibly with small padding above and below.
2. Read the Mark/Grade from the SAME horizontal row as the course ID and course title.
3. Do NOT use a grade from the row above or below.
4. If two rows are visible, use only the row that best matches the expected course ID/title and is closest to the vertical center.
5. If the Mark cell is unclear, return grade=null and confidence below 0.8.
6. Return course ID, course title, grade, attempted credits, and completed credits from the same row.
7. Do not default the grade to A.
8. Preserve visible course ID prefixes/tags only when printed on this same row.
9. Numeric-only course IDs are valid. Do not invent a prefix.
10. Mayfair examples may include: p 7510, + p 3261, * 8501, CC006.
11. LBUSD examples may include: P 2986, N 3635, HP 1449, H 2318, 2986.

Expected row anchor:
course_id: {course_id}
course_name: {course_name}
grade_level: {grade_level}
year: {year}
month: {month}

Return JSON in exactly this shape:
{{
  "course_id_raw": "HP 1449",
  "course_name": "AP ENGL LIT",
  "grade": "A",
  "credit_attempted": 5.0,
  "credit_completed": 5.0,
  "confidence": 1.0,
  "used_expected_row": true,
  "notes": null
}}
"""

# Backward-compatible alias. Other files can keep using the old name.
LBUSD_ROW_GRADE_VERIFY_PROMPT = ROW_GRADE_VERIFY_PROMPT


def row_crop_verifier_enabled() -> bool:
    return str(os.getenv("GEMINI_ENABLE_ROW_CROP_VERIFIER", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def safe_json_loads(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]

    try:
        parsed = json.loads(cleaned)
    except Exception:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def crop_pdf_row_to_png_bytes(
    *,
    pdf_path: str | None = None,
    pdf_bytes: bytes | None = None,
    page_number: int,
    bbox: tuple[float, float, float, float],
    dpi: int = 300,
    pad_x: float = 0.01,
    pad_y: float = 0.006,
) -> bytes:
    """
    Crop a row/region from a PDF page and return PNG bytes.

    The PDF can be a path (``pdf_path``) or in-memory bytes (``pdf_bytes``).
    Passing bytes reads directly from memory, so nothing touches disk.

    page_number:
        1-based page number.

    bbox:
        Normalized coordinates: (x1, y1, x2, y2), each between 0 and 1.
    """

    x1, y1, x2, y2 = bbox

    if pdf_bytes is not None:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    else:
        if not pdf_path or not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]

        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = Image.open(io.BytesIO(pix.tobytes("png")))
        width, height = image.size

        left = max(0, int((x1 - pad_x) * width))
        top = max(0, int((y1 - pad_y) * height))
        right = min(width, int((x2 + pad_x) * width))
        bottom = min(height, int((y2 + pad_y) * height))

        if right <= left or bottom <= top:
            raise ValueError(f"Invalid crop bbox after scaling: {bbox}")

        crop = image.crop((left, top, right, bottom))

        output = io.BytesIO()
        crop.save(output, format="PNG")
        return output.getvalue()
    finally:
        doc.close()


def expand_transcript_row_bbox_to_table_width(
    *,
    row_bbox: tuple[float, float, float, float],
    column: str | None = None,
) -> tuple[float, float, float, float]:
    """
    Expand a detected row bbox to include course id, title, mark, and credits.

    Shared three-column transcript layout for:
    - Mayfair
    - LBUSD / Millikan / Cabrillo / SATO / McBride / Wilson-style transcripts

    Some transcripts may only populate two columns, but the blank third column
    still exists visually and simply produces no rows.

    Normalized column boundaries:
    - left   : 0.08 to 0.37
    - middle : 0.37 to 0.63
    - right  : 0.63 to 0.92
    """

    _x1, y1, _x2, y2 = row_bbox
    normalized_column = (column or "").strip().lower()

    if normalized_column in {
        "left",
        "col1",
        "column_1",
        "column1",
        "mayfair_left",
        "lbusd_left",
        "transcript_left",
    }:
        return (0.08, y1, 0.37, y2)

    if normalized_column in {
        "middle",
        "center",
        "centre",
        "col2",
        "column_2",
        "column2",
        "mayfair_middle",
        "lbusd_middle",
        "transcript_middle",
    }:
        return (0.37, y1, 0.63, y2)

    if normalized_column in {
        "right",
        "col3",
        "column_3",
        "column3",
        "mayfair_right",
        "lbusd_right",
        "transcript_right",
    }:
        return (0.63, y1, 0.92, y2)

    return (0.08, y1, 0.92, y2)


def expand_lbusd_row_bbox_to_table_width(
    *,
    row_bbox: tuple[float, float, float, float],
    column: str | None = None,
) -> tuple[float, float, float, float]:
    """
    Backward-compatible wrapper.

    Older code calls this LBUSD-specific name. It now uses the shared
    three-column transcript layout that works for both LBUSD-style and Mayfair
    transcripts.
    """

    return expand_transcript_row_bbox_to_table_width(
        row_bbox=row_bbox,
        column=column,
    )


def verify_lbusd_row_crop_with_gemini(
    *,
    crop_png_bytes: bytes,
    course_id: str | None,
    course_name: str | None,
    grade_level: int | None,
    year: int | None,
    month: int | None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """
    Send one cropped row image to Gemini and return parsed JSON evidence.
    """

    # Reuse the Cloud Run-compatible client + validated model from the main
    # extractor so this verifier never falls back to a non-existent model.
    from app.services.gemini_course_extractor import (
        _make_gemini_client,
        _resolve_gemini_model,
    )

    client = _make_gemini_client()
    selected_model = model_name or _resolve_gemini_model()

    prompt = ROW_GRADE_VERIFY_PROMPT.format(
        course_id=course_id or "",
        course_name=course_name or "",
        grade_level=grade_level or "",
        year=year or "",
        month=month or "",
    )

    image_part = types.Part.from_bytes(
        data=crop_png_bytes,
        mime_type="image/png",
    )

    from app.services.gemini_rate_limit import generate_content_limited

    response = generate_content_limited(
        client,
        model=selected_model,
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    raw_response = response.text or ""
    result = safe_json_loads(raw_response)

    result["raw_response"] = raw_response
    result["model"] = selected_model
    result["verifier_type"] = "row_crop_grade"
    return result


def verify_lbusd_row_crop_from_pdf(
    *,
    pdf_path: str,
    page_number: int,
    row_bbox: tuple[float, float, float, float],
    column: str | None,
    course_id: str | None,
    course_name: str | None,
    grade_level: int | None,
    year: int | None,
    month: int | None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """
    Convenience wrapper:
    PDF row bbox -> crop PNG -> Gemini verification.
    """

    expanded_bbox = expand_transcript_row_bbox_to_table_width(
        row_bbox=row_bbox,
        column=column,
    )

    crop_png_bytes = crop_pdf_row_to_png_bytes(
        pdf_path=pdf_path,
        page_number=page_number,
        bbox=expanded_bbox,
    )

    result = verify_lbusd_row_crop_with_gemini(
        crop_png_bytes=crop_png_bytes,
        course_id=course_id,
        course_name=course_name,
        grade_level=grade_level,
        year=year,
        month=month,
        model_name=model_name,
    )

    result["page_number"] = page_number
    result["row_bbox"] = row_bbox
    result["expanded_bbox"] = expanded_bbox
    result["column"] = column
    return result


def attach_row_crop_grade_evidence(
    *,
    course: dict[str, Any],
    crop_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Attach row-crop verifier evidence into a course payload.

    This is meant to be saved into gemini_course_details.raw_payload.
    """

    raw_payload = course.get("raw_payload")

    if not isinstance(raw_payload, dict):
        raw_payload = {}

    raw_payload["backend_row_crop_grade_applied"] = True
    raw_payload["backend_row_crop_grade"] = crop_result.get("grade")
    raw_payload["backend_row_crop_confidence"] = crop_result.get("confidence")
    raw_payload["backend_row_crop_course_id_raw"] = crop_result.get("course_id_raw")
    raw_payload["backend_row_crop_course_name"] = crop_result.get("course_name")
    raw_payload["backend_row_crop_credit_attempted"] = crop_result.get("credit_attempted")
    raw_payload["backend_row_crop_credit_completed"] = crop_result.get("credit_completed")
    raw_payload["backend_row_crop_used_expected_row"] = crop_result.get("used_expected_row")
    raw_payload["backend_row_crop_notes"] = crop_result.get("notes")
    raw_payload["backend_row_crop_model"] = crop_result.get("model")
    raw_payload["backend_row_crop_raw_response"] = crop_result.get("raw_response")
    raw_payload["backend_row_crop_page_number"] = crop_result.get("page_number")
    raw_payload["backend_row_crop_bbox"] = crop_result.get("expanded_bbox")
    raw_payload["backend_row_crop_column"] = crop_result.get("column")

    course["raw_payload"] = raw_payload
    return course


def verify_many_lbusd_row_crops(
    *,
    pdf_path: str,
    crop_jobs: list[dict[str, Any]],
    model_name: str | None = None,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """
    Verify multiple row crops with limited concurrency.

    Each job should include:
    {
      "row_index": 1,
      "page_number": 1,
      "row_bbox": (x1, y1, x2, y2),
      "column": "left" | "middle" | "right" | None,
      "course_id": "...",
      "course_name": "...",
      "grade_level": 10,
      "year": 2024,
      "month": 1
    }
    """

    if not row_crop_verifier_enabled():
        return []

    results: list[dict[str, Any]] = []

    def worker(job: dict[str, Any]) -> dict[str, Any]:
        crop_result = verify_lbusd_row_crop_from_pdf(
            pdf_path=pdf_path,
            page_number=int(job["page_number"]),
            row_bbox=tuple(job["row_bbox"]),
            column=job.get("column"),
            course_id=job.get("course_id"),
            course_name=job.get("course_name"),
            grade_level=job.get("grade_level"),
            year=job.get("year"),
            month=job.get("month"),
            model_name=model_name,
        )

        return {
            **job,
            "crop_result": crop_result,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker, job) for job in crop_jobs]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "error": str(exc),
                        "crop_result": {},
                    }
                )

    return sorted(results, key=lambda item: item.get("row_index") or 0)
