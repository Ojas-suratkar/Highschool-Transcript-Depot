"""
Transcript batch processor orchestrator.

Clean 4-table extraction flow:

1. Document AI extracts raw courses.
2. Gemini extracts raw courses from the same PDF.
3. Raw Document AI rows are saved into course_details.
4. Raw Gemini rows are saved into gemini_course_details.
5. CourseReconciliationService compares both sources and writes:
   - course_extraction_matches
   - final_course_details
6. extraction_file_details.process_status is based on final_course_details
   unresolved review flags, not raw Doc AI count == Gemini count.

Important:
- course_details is treated as the raw Document AI extractor table.
- This file does not use old validation tables.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

from .document_ai_service import DocumentAIService
from .persistence_service import PersistenceService


# ---------------------------------------------------------------------------
# Document AI visual-geometry attachment for Gemini courses (additive).
# Identifies which Document AI visual row each Gemini course maps to and copies
# that geometry/OCR evidence onto the Gemini course. Never changes grades/IDs.
# ---------------------------------------------------------------------------

def _normalize_match_text(value: Any) -> str:
    """
    Normalize text for safe row-geometry matching only.

    This does not change saved course values. It is only used to decide which
    Document AI row bbox should be attached to which Gemini raw row.
    """
    text = str(value or "").upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_course_id_for_match(value: Any) -> str:
    """
    Normalize course IDs for matching geometry.

    Examples:
      "HP 1449" -> "1449"
      "N 3635"  -> "3635"
      "+ p 3261" -> "3261"
      "p 7510" -> "7510"
      "CC006" -> "CC006"

    Numeric-only IDs are valid. Prefixes are preserved in the actual saved data;
    this normalized value is only for matching rows.
    """
    text = str(value or "").upper().strip()

    if not text:
        return ""

    compact = re.sub(r"[^A-Z0-9]", "", text)

    cc_match = re.search(r"[A-Z]{2,}\d{3,}[A-Z]?", compact)
    if cc_match:
        return cc_match.group(0)

    number_match = re.search(r"\d{3,5}[A-Z]?", compact)
    if number_match:
        return number_match.group(0)

    return compact


def _base_letter_grade(value: Any) -> str:
    text = str(value or "").upper().strip()
    match = re.search(r"\b(A|B|C|D|F|P|NP|CR|NC)(?:[+-])?\b", text)
    return match.group(1) if match else ""


def _get_course_id_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("course_id"),
        course.get("crs_id"),
        course.get("course_id_raw"),
        course.get("gemini_course_id"),
        course.get("id"),
    )


def _get_course_name_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("course_name"),
        course.get("course_title"),
        course.get("title"),
        course.get("name"),
        course.get("crs_description"),
        course.get("subject"),
        course.get("course_transcript_abbrevs"),
    )


def _get_grade_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("grade"),
        course.get("letter_grade"),
        course.get("course_grade"),
        course.get("course_mark"),
        course.get("mark"),
        course.get("crs_letter_grade"),
        course.get("final"),
    )


def _get_grade_level_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("grade_level"),
        course.get("term_grade"),
        course.get("crs_grade"),
    )


def _get_month_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("month"),
        course.get("term_month"),
        course.get("crs_month"),
        course.get("semester"),
        course.get("term_name"),
    )


def _get_year_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("year"),
        course.get("term_year"),
        course.get("academic_year"),
        course.get("crs_year"),
    )


def _get_credit_attempted_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("credit_attempted"),
        course.get("credits_attempted"),
        course.get("crs_credit_attempted"),
        course.get("credits"),
    )


def _get_credit_completed_value(course: dict[str, Any]) -> Any:
    return _first_non_empty(
        course.get("credit_completed"),
        course.get("credits_completed"),
        course.get("crs_credit_completed"),
        course.get("credits"),
    )


def _extract_document_ai_geometry(course: dict[str, Any]) -> dict[str, Any] | None:
    """
    Read geometry from a Document AI course row.

    document_ai_service.py now attaches these fields to course rows. This helper
    also checks raw_document_ai_payload so the code remains safe if different
    layers preserve the geometry in different places.
    """
    candidates: list[dict[str, Any]] = []

    if isinstance(course, dict):
        candidates.append(course)

        raw_payload = course.get("raw_document_ai_payload")
        if isinstance(raw_payload, dict):
            candidates.append(raw_payload)

        geometry_payload = course.get("_geometry")
        if isinstance(geometry_payload, dict):
            candidates.append(geometry_payload)

    for candidate in candidates:
        geometry = candidate.get("_geometry") if isinstance(candidate.get("_geometry"), dict) else candidate

        page_number = _first_non_empty(
            geometry.get("page_number"),
            geometry.get("document_ai_page_number"),
        )
        column = _first_non_empty(
            geometry.get("column"),
            geometry.get("document_ai_column"),
        )
        row_bbox = _first_non_empty(
            geometry.get("row_bbox"),
            geometry.get("document_ai_row_bbox"),
        )
        raw_word_bbox = _first_non_empty(
            geometry.get("raw_word_bbox"),
            geometry.get("document_ai_raw_word_bbox"),
        )
        geometry_source = _first_non_empty(
            geometry.get("geometry_source"),
            geometry.get("document_ai_geometry_source"),
        )

        if page_number and row_bbox:
            return {
                "page_number": page_number,
                "column": column,
                "row_bbox": row_bbox,
                "raw_word_bbox": raw_word_bbox,
                "geometry_source": geometry_source or "document_ai_course_payload",
            }

    return None


def _extract_document_ai_ocr_geometry(course: dict[str, Any]) -> dict[str, Any] | None:
    """
    Read optional full Document AI OCR visual-row geometry from a course row.

    Safety:
    - This only reads metadata. It does not change extracted course values.
    - The metadata may come from the course row itself, raw_document_ai_payload,
      _geometry, _ocr_geometry, or document_ai_ocr_geometry depending on which
      layer created it.
    """
    candidates: list[dict[str, Any]] = []

    if isinstance(course, dict):
        candidates.append(course)

        raw_payload = course.get("raw_document_ai_payload")
        if isinstance(raw_payload, dict):
            candidates.append(raw_payload)

        geometry_payload = course.get("_geometry")
        if isinstance(geometry_payload, dict):
            candidates.append(geometry_payload)

        ocr_payload = course.get("_ocr_geometry")
        if isinstance(ocr_payload, dict):
            candidates.append(ocr_payload)

        named_ocr_payload = course.get("document_ai_ocr_geometry")
        if isinstance(named_ocr_payload, dict):
            candidates.append(named_ocr_payload)

    for candidate in candidates:
        geometry = candidate.get("_ocr_geometry") if isinstance(candidate.get("_ocr_geometry"), dict) else candidate

        page_number = _first_non_empty(
            geometry.get("document_ai_ocr_page_number"),
            geometry.get("ocr_page_number"),
            geometry.get("page_number"),
            geometry.get("document_ai_page_number"),
        )
        column = _first_non_empty(
            geometry.get("document_ai_ocr_column"),
            geometry.get("ocr_column"),
            geometry.get("column"),
            geometry.get("document_ai_column"),
        )
        row_bbox = _first_non_empty(
            geometry.get("document_ai_ocr_row_bbox"),
            geometry.get("ocr_row_bbox"),
            geometry.get("row_bbox"),
            geometry.get("document_ai_row_bbox"),
        )
        raw_word_bbox = _first_non_empty(
            geometry.get("document_ai_ocr_raw_word_bbox"),
            geometry.get("ocr_raw_word_bbox"),
            geometry.get("raw_word_bbox"),
            geometry.get("document_ai_raw_word_bbox"),
        )
        row_text = _first_non_empty(
            geometry.get("document_ai_ocr_row_text"),
            geometry.get("ocr_row_text"),
            geometry.get("row_text"),
            geometry.get("line_text"),
        )
        section_grade = _first_non_empty(
            geometry.get("document_ai_ocr_section_grade"),
            geometry.get("ocr_section_grade"),
            geometry.get("section_grade"),
            geometry.get("grade_level"),
            geometry.get("term_grade"),
        )
        section_month = _first_non_empty(
            geometry.get("document_ai_ocr_section_month"),
            geometry.get("ocr_section_month"),
            geometry.get("section_month"),
            geometry.get("term_month"),
        )
        section_year = _first_non_empty(
            geometry.get("document_ai_ocr_section_year"),
            geometry.get("ocr_section_year"),
            geometry.get("section_year"),
            geometry.get("term_year"),
        )
        section_name = _first_non_empty(
            geometry.get("document_ai_ocr_section_name"),
            geometry.get("ocr_section_name"),
            geometry.get("section_name"),
        )
        section_source = _first_non_empty(
            geometry.get("document_ai_ocr_section_source"),
            geometry.get("ocr_section_source"),
            geometry.get("section_source"),
        )
        match_score = _first_non_empty(
            geometry.get("document_ai_ocr_match_score"),
            geometry.get("ocr_match_score"),
            geometry.get("match_score"),
        )
        geometry_source = _first_non_empty(
            geometry.get("document_ai_ocr_geometry_source"),
            geometry.get("ocr_geometry_source"),
            geometry.get("geometry_source"),
        )

        has_any_ocr_value = any(
            value not in (None, "", [], {})
            for value in (
                row_bbox,
                row_text,
                section_grade,
                section_month,
                section_year,
                section_name,
            )
        )

        if has_any_ocr_value:
            return {
                "page_number": page_number,
                "column": column,
                "row_bbox": row_bbox,
                "raw_word_bbox": raw_word_bbox,
                "row_text": row_text,
                "section_grade": _coerce_int(section_grade),
                "section_month": _month_to_int(section_month),
                "section_year": _year_to_int(section_year),
                "section_name": section_name,
                "section_source": section_source,
                "match_score": _coerce_float(match_score),
                "geometry_source": geometry_source or "document_ai_ocr_payload",
            }

    return None


def _score_geometry_match(
    gemini_course: dict[str, Any],
    document_ai_course: dict[str, Any],
) -> float:
    """
    Score whether a Document AI row geometry belongs to a Gemini raw course row.

    This only decides bbox attachment. It does not decide final trusted values.
    Reconciliation still owns final row decisions.
    """
    score = 0.0

    gemini_id = _normalize_course_id_for_match(_get_course_id_value(gemini_course))
    doc_id = _normalize_course_id_for_match(_get_course_id_value(document_ai_course))

    if gemini_id and doc_id:
        if gemini_id == doc_id:
            score += 42.0
        else:
            # Different concrete course IDs are probably different rows.
            score -= 28.0

    gemini_name = _normalize_match_text(_get_course_name_value(gemini_course))
    doc_name = _normalize_match_text(_get_course_name_value(document_ai_course))

    if gemini_name and doc_name:
        similarity = SequenceMatcher(None, gemini_name, doc_name).ratio()
        score += similarity * 30.0

        if similarity >= 0.92:
            score += 8.0
        elif similarity < 0.55:
            score -= 8.0

    gemini_grade = _base_letter_grade(_get_grade_value(gemini_course))
    doc_grade = _base_letter_grade(_get_grade_value(document_ai_course))

    if gemini_grade and doc_grade and gemini_grade == doc_grade:
        score += 6.0

    gemini_grade_level = _coerce_int(_get_grade_level_value(gemini_course))
    doc_grade_level = _coerce_int(_get_grade_level_value(document_ai_course))

    if gemini_grade_level and doc_grade_level:
        if gemini_grade_level == doc_grade_level:
            score += 8.0
        else:
            score -= 12.0

    gemini_month = _month_to_int(_get_month_value(gemini_course))
    doc_month = _month_to_int(_get_month_value(document_ai_course))

    if gemini_month and doc_month:
        if gemini_month == doc_month:
            score += 8.0
        else:
            score -= 12.0

    gemini_year = _year_to_int(_get_year_value(gemini_course))
    doc_year = _year_to_int(_get_year_value(document_ai_course))

    if gemini_year and doc_year:
        if gemini_year == doc_year:
            score += 8.0
        else:
            score -= 12.0

    gemini_attempted = _coerce_float(_get_credit_attempted_value(gemini_course))
    doc_attempted = _coerce_float(_get_credit_attempted_value(document_ai_course))
    gemini_completed = _coerce_float(_get_credit_completed_value(gemini_course))
    doc_completed = _coerce_float(_get_credit_completed_value(document_ai_course))

    if gemini_attempted is not None and doc_attempted is not None:
        if abs(gemini_attempted - doc_attempted) <= 0.01:
            score += 4.0
        else:
            score -= 4.0

    if gemini_completed is not None and doc_completed is not None:
        if abs(gemini_completed - doc_completed) <= 0.01:
            score += 4.0
        else:
            score -= 4.0

    return score


def _attach_document_ai_geometry_to_gemini_courses(
    *,
    gemini_courses: list[dict[str, Any]],
    document_ai_courses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Attach Document AI geometry evidence to Gemini raw rows before saving.

    Safety:
    - Existing Gemini extraction values are not changed.
    - Existing Document AI extraction values are not changed.
    - This only adds extra raw_payload keys such as document_ai_row_bbox and
      document_ai_ocr_section_year.
    - Reconciliation still owns final trusted values.
    - If geometry is missing, this returns the original Gemini rows unchanged.
    """
    if not gemini_courses or not document_ai_courses:
        return gemini_courses

    doc_rows: list[dict[str, Any]] = []

    for index, doc_course in enumerate(document_ai_courses):
        if not isinstance(doc_course, dict):
            continue

        geometry = _extract_document_ai_geometry(doc_course)
        ocr_geometry = _extract_document_ai_ocr_geometry(doc_course)

        if not geometry and not ocr_geometry:
            continue

        # Keep backward compatibility with the old row-bbox matching behavior.
        # If the old geometry is missing but OCR has a bbox, use OCR as the
        # attachment geometry without changing any course values.
        geometry_for_matching = geometry
        if geometry_for_matching is None and ocr_geometry is not None:
            geometry_for_matching = {
                "page_number": ocr_geometry.get("page_number"),
                "column": ocr_geometry.get("column"),
                "row_bbox": ocr_geometry.get("row_bbox"),
                "raw_word_bbox": ocr_geometry.get("raw_word_bbox"),
                "geometry_source": ocr_geometry.get("geometry_source"),
            }

        doc_rows.append(
            {
                "index": index,
                "course": doc_course,
                "geometry": geometry_for_matching,
                "ocr_geometry": ocr_geometry,
            }
        )

    if not doc_rows:
        return gemini_courses

    candidates: list[tuple[float, int, int]] = []

    for gemini_index, gemini_course in enumerate(gemini_courses):
        if not isinstance(gemini_course, dict):
            continue

        for doc_item in doc_rows:
            score = _score_geometry_match(gemini_course, doc_item["course"])

            # Keep the existing threshold so this patch does not make row
            # attachment more aggressive than before.
            if score >= 55.0:
                candidates.append((score, gemini_index, int(doc_item["index"])))

    candidates.sort(reverse=True, key=lambda item: item[0])

    used_gemini: set[int] = set()
    used_doc: set[int] = set()
    doc_by_index = {int(item["index"]): item for item in doc_rows}
    attached_count = 0
    ocr_attached_count = 0

    for score, gemini_index, doc_index in candidates:
        if gemini_index in used_gemini or doc_index in used_doc:
            continue

        gemini_course = gemini_courses[gemini_index]
        doc_item = doc_by_index.get(doc_index)

        if not isinstance(gemini_course, dict) or not doc_item:
            continue

        geometry = doc_item.get("geometry")
        ocr_geometry = doc_item.get("ocr_geometry")

        raw_payload = gemini_course.get("raw_payload")
        if not isinstance(raw_payload, dict):
            raw_payload = gemini_course

        if geometry:
            # Preserve existing Gemini values. Only attach geometry/evidence fields.
            gemini_course["document_ai_page_number"] = geometry.get("page_number")
            gemini_course["document_ai_column"] = geometry.get("column")
            gemini_course["document_ai_row_bbox"] = geometry.get("row_bbox")
            gemini_course["document_ai_raw_word_bbox"] = geometry.get("raw_word_bbox")
            gemini_course["document_ai_geometry_source"] = geometry.get("geometry_source")
            gemini_course["document_ai_geometry_match_score"] = round(float(score), 3)
            gemini_course["document_ai_geometry_match_index"] = doc_index + 1

            # Generic aliases for future crop helpers. They are only set when empty
            # so we do not overwrite any Gemini-provided geometry if it appears later.
            gemini_course.setdefault("page_number", geometry.get("page_number"))
            gemini_course.setdefault("column", geometry.get("column"))
            gemini_course.setdefault("row_bbox", geometry.get("row_bbox"))

            raw_payload["document_ai_page_number"] = geometry.get("page_number")
            raw_payload["document_ai_column"] = geometry.get("column")
            raw_payload["document_ai_row_bbox"] = geometry.get("row_bbox")
            raw_payload["document_ai_raw_word_bbox"] = geometry.get("raw_word_bbox")
            raw_payload["document_ai_geometry_source"] = geometry.get("geometry_source")
            raw_payload["document_ai_geometry_match_score"] = round(float(score), 3)
            raw_payload["document_ai_geometry_match_index"] = doc_index + 1
            raw_payload.setdefault("page_number", geometry.get("page_number"))
            raw_payload.setdefault("column", geometry.get("column"))
            raw_payload.setdefault("row_bbox", geometry.get("row_bbox"))

        if ocr_geometry:
            # New optional OCR visual-row evidence. This is only metadata.
            # It is intentionally separate from the old document_ai_row_bbox keys.
            ocr_fields = {
                "document_ai_ocr_page_number": ocr_geometry.get("page_number"),
                "document_ai_ocr_column": ocr_geometry.get("column"),
                "document_ai_ocr_row_bbox": ocr_geometry.get("row_bbox"),
                "document_ai_ocr_raw_word_bbox": ocr_geometry.get("raw_word_bbox"),
                "document_ai_ocr_row_text": ocr_geometry.get("row_text"),
                "document_ai_ocr_section_grade": ocr_geometry.get("section_grade"),
                "document_ai_ocr_section_month": ocr_geometry.get("section_month"),
                "document_ai_ocr_section_year": ocr_geometry.get("section_year"),
                "document_ai_ocr_section_name": ocr_geometry.get("section_name"),
                "document_ai_ocr_section_source": ocr_geometry.get("section_source"),
                "document_ai_ocr_match_score": ocr_geometry.get("match_score"),
                "document_ai_ocr_geometry_source": ocr_geometry.get("geometry_source"),
                "document_ai_ocr_geometry_match_index": doc_index + 1,
            }

            for key, value in ocr_fields.items():
                if value not in (None, "", [], {}):
                    gemini_course[key] = value
                    raw_payload[key] = value

            ocr_attached_count += 1

        used_gemini.add(gemini_index)
        used_doc.add(doc_index)
        attached_count += 1

    if attached_count:
        print(
            "[GEMINI GEOMETRY ATTACHED] "
            f"gemini_rows={len(gemini_courses)}, "
            f"document_ai_geometry_rows={len(doc_rows)}, "
            f"attached={attached_count}, "
            f"ocr_attached={ocr_attached_count}"
        )
    else:
        print(
            "[GEMINI GEOMETRY ATTACHMENT SKIPPED] "
            f"gemini_rows={len(gemini_courses)}, "
            f"document_ai_geometry_rows={len(doc_rows)}, "
            "reason=no_confident_row_matches"
        )

    return gemini_courses


@dataclass
class ProcessorConfig:
    project_id: str
    location: str
    processor_id: str


@dataclass
class ExtractionContext:
    extraction_file_id: int
    institution_id: int
    classifier_type_id: int
    used_processor_id: str
    file_name: str
    classifier_name: str | None = None


def _first_non_empty(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return None


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
        return None


def _month_to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip()

    try:
        return int(text)
    except Exception:
        pass

    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
        "fall": 1,
        "spring": 2,
        "semester 1": 1,
        "sem 1": 1,
        "semester 2": 2,
        "sem 2": 2,
    }

    low = text.lower()

    for key, val in months.items():
        if key in low:
            return val

    return None


def _year_to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip()

    try:
        return int(text)
    except Exception:
        pass

    import re

    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def _filter_model_values(model_cls: Any, values: dict[str, Any]) -> dict[str, Any]:
    model_columns = set(model_cls.__table__.columns.keys())

    return {
        key: value
        for key, value in values.items()
        if key in model_columns
    }


def _get_model(*names: str):
    for name in names:
        model_cls = getattr(models, name, None)
        if model_cls is not None:
            return model_cls

    return None


def _require_model(*names: str):
    model_cls = _get_model(*names)

    if model_cls is None:
        raise RuntimeError(
            "Missing SQLAlchemy model. Expected one of: "
            + ", ".join(names)
        )

    return model_cls


def _file_column(model_cls: Any):
    columns = set(model_cls.__table__.columns.keys())

    if "source_file" in columns:
        return getattr(model_cls, "source_file")

    if "extraction_file_id" in columns:
        return getattr(model_cls, "extraction_file_id")

    raise RuntimeError(
        f"{model_cls.__name__} must have source_file or extraction_file_id."
    )


class TranscriptProcessor:
    def __init__(self, config: Optional[ProcessorConfig] = None):
        self._service = (
            DocumentAIService(
                project_id=config.project_id,
                location=config.location,
                processor_id=config.processor_id,
            )
            if config is not None
            else None
        )

    async def _read_file_process_status(
        self,
        session: AsyncSession,
        extraction_file_id: int,
    ) -> str:
        result = await session.execute(
            select(models.ExtractionFileDetails.process_status).where(
                models.ExtractionFileDetails.id == extraction_file_id
            )
        )

        return result.scalar_one_or_none() or "needs_review"

    async def _read_raw_document_ai_course_count(
        self,
        session: AsyncSession,
        extraction_file_id: int,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(models.Course_details)
            .where(models.Course_details.source_file == extraction_file_id)
        )

        return int(result.scalar_one() or 0)

    async def _read_raw_gemini_course_count(
        self,
        session: AsyncSession,
        extraction_file_id: int,
    ) -> int:
        GeminiCourseDetails = _get_model(
            "GeminiCourseDetails",
            "GeminiCourseDetail",
            "GeminiCourse_details",
        )

        if GeminiCourseDetails is None:
            return 0

        result = await session.execute(
            select(func.count())
            .select_from(GeminiCourseDetails)
            .where(_file_column(GeminiCourseDetails) == extraction_file_id)
        )

        return int(result.scalar_one() or 0)

    async def _read_final_course_count(
        self,
        session: AsyncSession,
        extraction_file_id: int,
    ) -> int:
        FinalCourseDetails = _get_model(
            "FinalCourseDetails",
            "FinalCourseDetail",
            "Final_course_details",
        )

        if FinalCourseDetails is None:
            return 0

        result = await session.execute(
            select(func.count())
            .select_from(FinalCourseDetails)
            .where(_file_column(FinalCourseDetails) == extraction_file_id)
        )

        return int(result.scalar_one() or 0)

    async def _clear_rows_for_file(
        self,
        session: AsyncSession,
        model_cls: Any,
        extraction_file_id: int,
    ) -> None:
        await session.execute(
            delete(model_cls).where(_file_column(model_cls) == extraction_file_id)
        )
        await session.flush()

    def _build_routed_courses(
        self,
        *,
        payload_courses: List[Dict[str, Any]],
        extraction_file_id: int,
        student_db_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Convert Document AI course payloads into normalized routed course rows.

        Do not dedupe here. course_details is the raw Document AI table.
        If Document AI extracts repeated transcript rows, preserve them.
        """

        routed_courses: List[Dict[str, Any]] = []

        for idx, course in enumerate(payload_courses):
            course_title = (
                course.get("course_title")
                or course.get("title")
                or course.get("course_name")
                or course.get("subject")
                or course.get("course_transcript_abbrevs")
            )

            course_id = course.get("course_id")

            if not course_title:
                course_title = (
                    (course_id and str(course_id))
                    or f"Unknown Course {idx + 1}"
                )

            course_mark = (
                course.get("course_mark")
                or course.get("mark")
                or course.get("final")
                or course.get("course_grade")
            )

            sem1 = (
                course.get("sem_1")
                or course.get("sem1")
                or course.get("mark_sem1")
            )

            sem2 = (
                course.get("sem_2")
                or course.get("sem2")
                or course.get("mark_sem2")
            )

            total_term_gpa = (
                course.get("total_term_gpa")
                or course.get("total_gpa")
                or course.get("totalGPA")
            )

            routed_courses.append(
                {
                    "source_file": extraction_file_id,
                    "student_id": student_db_id,
                    "course_id": course_id,
                    "title": course_title,
                    "mark": course_mark,
                    "sem_1": sem1,
                    "sem_2": sem2,
                    "credit_sem1": course.get("credit_sem1"),
                    "credit_sem2": course.get("credit_sem2"),
                    "term_schoolname": course.get("term_school_name"),
                    "term_grade": course.get("term_grade"),
                    "term_month": course.get("term_month"),
                    "term_year": course.get("term_year"),
                    "credit_attempted": course.get("credit_attempted"),
                    "credit_completed": course.get("credit_completed"),
                    "total_term_gpa": total_term_gpa,
                    "s_sch": course.get("credits"),
                    "course_index": idx + 1,
                    "raw_document_ai_payload": course,
                }
            )

        return routed_courses

    def _normalize_gemini_result(
        self,
        result: Any,
    ) -> dict[str, Any]:
        if result is None:
            return {
                "status": "failed",
                "courses": [],
                "course_count": 0,
                "model": None,
                "error": "Gemini extraction returned no result.",
                "raw_result": None,
            }

        if isinstance(result, list):
            return {
                "status": "completed",
                "courses": result,
                "course_count": len(result),
                "model": None,
                "error": None,
                "raw_result": result,
            }

        if isinstance(result, dict):
            courses = (
                result.get("courses")
                or result.get("course_details")
                or result.get("gemini_courses")
                or result.get("course_items")
                or result.get("items")
                or []
            )

            if not isinstance(courses, list):
                courses = []

            return {
                "status": result.get("status") or "completed",
                "courses": courses,
                "course_count": (
                    _coerce_int(result.get("course_count"))
                    or _coerce_int(result.get("gemini_course_count"))
                    or len(courses)
                ),
                "model": result.get("model"),
                "error": result.get("error"),
                "raw_result": result,
            }

        return {
            "status": "failed",
            "courses": [],
            "course_count": 0,
            "model": None,
            "error": f"Unexpected Gemini extraction result type: {type(result)}",
            "raw_result": result,
        }

    async def _run_gemini_course_extraction(
        self,
        *,
        pdf_path: Optional[str] = None,
        content: Optional[bytes] = None,
        gcs_uri: Optional[str] = None,
        temperature: float = 0.0,
        transcript_format: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Gemini raw extraction step.

        This must return its own course rows, not old missing/extra validation rows.

        Expected service:
        app.services.gemini_course_extractor.run_gemini_course_extraction

        Expected return shape can be either:
        - list[dict]
        - {"courses": list[dict], "model": "...", "status": "..."}
        """

        temp_pdf_path = None

        try:
            extraction_pdf_path = pdf_path

            if not extraction_pdf_path and content:
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".pdf",
                ) as temp_file:
                    temp_file.write(content)
                    temp_pdf_path = temp_file.name
                    extraction_pdf_path = temp_pdf_path

            if not extraction_pdf_path and not gcs_uri:
                return {
                    "status": "failed",
                    "courses": [],
                    "course_count": 0,
                    "model": None,
                    "error": (
                        "Gemini extraction skipped because no local PDF path, "
                        "PDF bytes, or GCS URI was available."
                    ),
                    "raw_result": None,
                }

            try:
                from app.services.gemini_course_extractor import (
                    run_gemini_course_extraction,
                )
            except Exception as exc:
                return {
                    "status": "failed",
                    "courses": [],
                    "course_count": 0,
                    "model": None,
                    "error": (
                        "Gemini course extractor service is not available yet: "
                        f"{str(exc)}"
                    ),
                    "raw_result": None,
                }

            # Block-chunked extraction (anti-hallucination): limit Gemini to one
            # term-block at a time so it can't fabricate long sequential rows. It
            # needs the PDF bytes (for geometry + cropping); fetch from GCS if only
            # a gs:// URI is available. Any failure falls back to full-PDF below.
            try:
                from app.services.gemini_block_extractor import (
                    block_chunked_extraction_enabled,
                    run_gemini_block_chunked_extraction,
                )
            except Exception:  # noqa: BLE001
                block_chunked_extraction_enabled = None  # type: ignore

            if block_chunked_extraction_enabled and block_chunked_extraction_enabled():
                block_bytes = content
                if block_bytes is None and extraction_pdf_path and os.path.exists(extraction_pdf_path):
                    try:
                        with open(extraction_pdf_path, "rb") as fh:
                            block_bytes = fh.read()
                    except Exception:  # noqa: BLE001
                        block_bytes = None
                if block_bytes is None and gcs_uri:
                    block_bytes = await asyncio.to_thread(self._download_gcs_bytes, gcs_uri)

                if block_bytes:
                    try:
                        block_result = await asyncio.to_thread(
                            run_gemini_block_chunked_extraction,
                            pdf_bytes=block_bytes,
                        )
                        normalized = self._normalize_gemini_result(block_result)
                        got_n = len(normalized.get("courses") or [])
                        geo_n = int(block_result.get("geometry_row_count") or 0)
                        # Geometry gives a deterministic row count. If block
                        # extraction lands near it, trust it; if it strays far
                        # (missed blocks or bad crops), fall back to full-PDF.
                        within_range = (geo_n == 0) or (0.6 <= got_n / geo_n <= 1.6)
                        if got_n and within_range:
                            print(
                                f"[GEMINI] block-chunked OK: {got_n} courses across "
                                f"{block_result.get('block_count')} blocks "
                                f"(geometry rows={geo_n}, "
                                f"row-crop grades={block_result.get('row_crop_grades_applied')}).",
                                flush=True,
                            )
                            return normalized
                        print(
                            f"[GEMINI] block-chunked count {got_n} vs geometry {geo_n} "
                            "out of range (or empty); falling back to full-PDF.",
                            flush=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[GEMINI] block-chunked extraction failed ({exc}); "
                            "falling back to full-PDF extraction.",
                            flush=True,
                        )

            result = await asyncio.to_thread(
                run_gemini_course_extraction,
                pdf_path=extraction_pdf_path,
                gcs_uri=gcs_uri,
                temperature=temperature,
                transcript_format=transcript_format,
            )

            return self._normalize_gemini_result(result)

        except Exception as exc:
            return {
                "status": "failed",
                "courses": [],
                "course_count": 0,
                "model": None,
                "error": f"Gemini extraction failed: {str(exc)}",
                "raw_result": None,
            }

        finally:
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    @staticmethod
    def _gemini_shortfall_ratio() -> float:
        try:
            return float(os.getenv("GEMINI_SHORTFALL_RATIO", "0.8"))
        except (TypeError, ValueError):
            return 0.8

    @staticmethod
    def _gemini_shortfall_min_doc() -> int:
        try:
            return int(os.getenv("GEMINI_SHORTFALL_MIN_DOC", "5"))
        except (TypeError, ValueError):
            return 5

    @staticmethod
    def _gemini_overextraction_ratio() -> float:
        """Gemini row count above (Doc AI count * this) is treated as likely
        hallucination/duplication and routed to manual review."""
        try:
            return float(os.getenv("GEMINI_OVEREXTRACTION_RATIO", "1.35"))
        except (TypeError, ValueError):
            return 1.35

    @staticmethod
    def _count_cross_check_tolerance() -> int:
        """How many more courses the independent counter may report before the
        file is routed to review (absorbs small per-block counting noise)."""
        try:
            return max(0, int(os.getenv("GEMINI_COUNT_CROSS_CHECK_TOLERANCE", "1")))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _download_gcs_bytes(gcs_uri: str) -> bytes | None:
        """Download a gs:// object into memory (no disk) for block-chunked
        extraction's geometry/cropping. Returns None on any failure."""
        try:
            if not gcs_uri or not gcs_uri.startswith("gs://"):
                return None
            from google.cloud import storage

            bucket_name, _, blob_name = gcs_uri[len("gs://"):].partition("/")
            if not bucket_name or not blob_name:
                return None
            client = storage.Client()
            return client.bucket(bucket_name).blob(blob_name).download_as_bytes()
        except Exception as exc:  # noqa: BLE001
            print(f"[GEMINI] GCS download for block extraction failed: {exc}", flush=True)
            return None

    async def _retry_gemini_if_short(
        self,
        document_ai_result: Any,
        gemini_result: dict[str, Any],
        *,
        pdf_path: Optional[str] = None,
        content: Optional[bytes] = None,
        gcs_uri: Optional[str] = None,
        transcript_format: Optional[str] = None,
    ) -> dict[str, Any]:
        """If Gemini extracted far fewer courses than Doc AI, retry once.

        Gemini under-extraction (e.g. an output-token truncation or a transient
        error) leaves the cross-check blind: the file would otherwise complete on
        Doc AI alone. We re-run Gemini once with a small non-zero temperature so
        the resampled pass can differ from the deterministic first one, and keep
        whichever pass found more courses. If it's still short, the caller marks
        the file needs_review (see _persist_clean_pipeline_outputs)."""
        doc_courses = (document_ai_result or {}).get("course_details") or []
        doc_count = len(doc_courses)
        gem_count = (gemini_result or {}).get("course_count") or len(
            (gemini_result or {}).get("courses") or []
        )

        ratio = self._gemini_shortfall_ratio()
        min_doc = self._gemini_shortfall_min_doc()

        if doc_count < min_doc or gem_count >= doc_count * ratio:
            return gemini_result

        print(
            f"[GEMINI] under-extraction: gemini={gem_count} vs doc_ai={doc_count} "
            f"(<{ratio:.0%}) — retrying once at temperature=0.3",
            flush=True,
        )

        retry = await self._run_gemini_course_extraction(
            pdf_path=pdf_path,
            content=content,
            gcs_uri=gcs_uri,
            temperature=0.3,
            transcript_format=transcript_format,
        )
        retry_count = (retry or {}).get("course_count") or len(
            (retry or {}).get("courses") or []
        )

        best = retry if retry_count > gem_count else gemini_result
        best_count = max(retry_count, gem_count)
        still_short = best_count < doc_count * ratio

        if retry_count > gem_count:
            print(
                f"[GEMINI] retry improved extraction: {gem_count} -> {retry_count}",
                flush=True,
            )
        else:
            print(
                f"[GEMINI] retry did not help ({gem_count} -> {retry_count}); "
                "keeping best result",
                flush=True,
            )
        if still_short:
            print(
                f"[GEMINI] still short after retry ({best_count}/{doc_count}); "
                "file will be flagged for manual review",
                flush=True,
            )

        best["gemini_retry"] = {
            "attempted": True,
            "before": gem_count,
            "after": retry_count,
            "still_short": still_short,
        }
        return best

    async def _save_gemini_courses(
        self,
        session: AsyncSession,
        *,
        extraction_file_id: int,
        student_db_id: int,
        gemini_courses: list[dict[str, Any]],
        gemini_payload: dict[str, Any],
    ) -> int:
        GeminiCourseDetails = _require_model(
            "GeminiCourseDetails",
            "GeminiCourseDetail",
            "GeminiCourse_details",
        )

        await self._clear_rows_for_file(
            session,
            GeminiCourseDetails,
            extraction_file_id,
        )

        inserted = 0

        for index, course in enumerate(gemini_courses):
            if not isinstance(course, dict):
                continue

            course_id = _first_non_empty(
                course.get("course_id"),
                course.get("crs_id"),
                course.get("course_id_raw"),
                course.get("gemini_course_id"),
            )

            course_name = _first_non_empty(
                course.get("course_name"),
                course.get("title"),
                course.get("name"),
                course.get("crs_description"),
                course.get("subject"),
            )

            grade = _first_non_empty(
                course.get("grade"),
                course.get("letter_grade"),
                course.get("course_grade"),
                course.get("mark"),
                course.get("crs_letter_grade"),
            )

            grade_level = _first_non_empty(
                course.get("grade_level"),
                course.get("term_grade"),
                course.get("crs_grade"),
            )

            month = _first_non_empty(
                course.get("month"),
                course.get("term_month"),
                course.get("crs_month"),
                course.get("semester"),
                course.get("term_name"),
            )

            year = _first_non_empty(
                course.get("year"),
                course.get("term_year"),
                course.get("academic_year"),
                course.get("crs_year"),
            )

            credit_attempted = _first_non_empty(
                course.get("credit_attempted"),
                course.get("credits_attempted"),
                course.get("crs_credit_attempted"),
                course.get("credits"),
            )

            credit_completed = _first_non_empty(
                course.get("credit_completed"),
                course.get("credits_completed"),
                course.get("crs_credit_completed"),
                course.get("credits"),
            )

            school = _first_non_empty(
                course.get("school"),
                course.get("school_name"),
                course.get("term_school_name"),
                course.get("crs_hs"),
            )

            confidence = _first_non_empty(
                course.get("confidence"),
                course.get("gemini_confidence"),
                course.get("extraction_confidence"),
            )

            values = {
                "s_id": student_db_id,
                "student_id": student_db_id,
                "source_file": extraction_file_id,
                "extraction_file_id": extraction_file_id,
                "row_index": index + 1,
                "course_index": index + 1,
                "crs_id": course_id,
                "course_id": course_id,
                "crs_description": course_name,
                "course_name": course_name,
                "name": course_name,
                "crs_letter_grade": grade,
                "letter_grade": grade,
                "grade": grade,
                "crs_hs": school,
                "school": school,
                "school_name": school,
                "crs_grade": _coerce_int(grade_level),
                "grade_level": _coerce_int(grade_level),
                "crs_month": _month_to_int(month),
                "month": _month_to_int(month),
                "crs_year": _year_to_int(year),
                "year": _year_to_int(year),
                "crs_credit_attempted": _coerce_float(credit_attempted),
                "credit_attempted": _coerce_float(credit_attempted),
                "credits_attempted": _coerce_float(credit_attempted),
                "crs_credit_completed": _coerce_float(credit_completed),
                "credit_completed": _coerce_float(credit_completed),
                "credits_completed": _coerce_float(credit_completed),
                "extraction_confidence": _coerce_float(confidence),
                "gemini_confidence": _coerce_float(confidence),
                "model": gemini_payload.get("model"),
                "raw_payload": course,
                "raw_json": course,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }

            values = _filter_model_values(GeminiCourseDetails, values)

            session.add(GeminiCourseDetails(**values))
            inserted += 1

        await session.commit()

        print(
            "[GEMINI COURSES INSERTED] "
            f"file_id={extraction_file_id}, "
            f"input_rows={len(gemini_courses)}, "
            f"inserted={inserted}"
        )

        return inserted

    async def _run_reconciliation(
        self,
        session: AsyncSession,
        *,
        extraction_file_id: int,
        student_db_id: int,
        document_ai_course_count: int,
        gemini_course_count: int,
        pdf_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        """
        Compare raw Document AI rows and raw Gemini rows.

        Expected service:
        app.services.course_reconciliation_service.CourseReconciliationService

        It should read:
        - course_details
        - gemini_course_details

        It should write:
        - course_extraction_matches
        - final_course_details
        """

        try:
            from app.services.course_reconciliation_service import (
                CourseReconciliationService,
            )
        except Exception as exc:
            await PersistenceService(session).mark_file_status(
                extraction_file_id,
                "needs_review",
            )

            return {
                "status": "needs_review",
                "file_status": "needs_review",
                "error": (
                    "Course reconciliation service is not available yet: "
                    f"{str(exc)}"
                ),
                "document_ai_course_count": document_ai_course_count,
                "gemini_course_count": gemini_course_count,
                "final_course_count": 0,
            }

        service = CourseReconciliationService(session)

        reconcile_method = (
            getattr(service, "reconcile_file", None)
            or getattr(service, "reconcile", None)
        )

        if reconcile_method is None:
            await PersistenceService(session).mark_file_status(
                extraction_file_id,
                "needs_review",
            )

            return {
                "status": "needs_review",
                "file_status": "needs_review",
                "error": (
                    "CourseReconciliationService must define reconcile_file() "
                    "or reconcile()."
                ),
                "document_ai_course_count": document_ai_course_count,
                "gemini_course_count": gemini_course_count,
                "final_course_count": 0,
            }

        result = await reconcile_method(
            extraction_file_id=extraction_file_id,
            student_db_id=student_db_id,
            document_ai_course_count=document_ai_course_count,
            gemini_course_count=gemini_course_count,
            pdf_bytes=pdf_bytes,
        )

        if not isinstance(result, dict):
            result = {}

        final_course_count = await self._read_final_course_count(
            session,
            extraction_file_id,
        )

        file_status = (
            result.get("file_status")
            or result.get("process_status")
            or result.get("status")
            or await self._read_file_process_status(session, extraction_file_id)
        )

        return {
            **result,
            "file_status": file_status,
            "process_status": file_status,
            "document_ai_course_count": document_ai_course_count,
            "gemini_course_count": gemini_course_count,
            "final_course_count": final_course_count,
        }

    async def _resolve_classifier(
        self,
        session: AsyncSession,
        ctx: ExtractionContext,
    ):
        processor_id = ctx.used_processor_id

        classifier_name = None

        if ctx.classifier_name:
            classifier_name = ctx.classifier_name
        elif ctx.classifier_type_id:
            result = await session.execute(
                select(models.ClassifiersType).where(
                    models.ClassifiersType.id == ctx.classifier_type_id
                )
            )
            classifier_row = result.scalar_one_or_none()

            if classifier_row:
                classifier_name = classifier_row.classifier_name

        if not classifier_name:
            file_name_lower = (ctx.file_name or "").lower()

            if "mayfair" in file_name_lower:
                classifier_name = "mayfair_high_school"
            elif "lbusd" in file_name_lower or "lb" in file_name_lower:
                classifier_name = "lbusd"
            elif "anthony" in file_name_lower or "st_anthony" in file_name_lower:
                classifier_name = "st_anthony_high_school"
            else:
                classifier_name = "others"

        result = await session.execute(
            select(models.ClassifiersType).where(
                models.ClassifiersType.classifier_name == classifier_name
            )
        )
        classifier = result.scalar_one_or_none()

        if not classifier:
            insert_stmt = (
                insert(models.ClassifiersType)
                .values(
                    classifier_name=classifier_name,
                    processor_id=processor_id,
                    status=f"enabled_{classifier_name}",
                )
                .returning(models.ClassifiersType)
            )

            try:
                result = await session.execute(insert_stmt)
                await session.commit()
                classifier = result.scalar_one()
            except Exception:
                await session.rollback()

                result = await session.execute(
                    select(models.ClassifiersType).where(
                        models.ClassifiersType.classifier_name == classifier_name
                    )
                )
                classifier = result.scalar_one_or_none()

                if not classifier:
                    result = await session.execute(
                        select(models.ClassifiersType).where(
                            models.ClassifiersType.processor_id == processor_id
                        )
                    )
                    classifier = result.scalar_one_or_none()

        return classifier_name, classifier

    async def _ensure_extraction_file(
        self,
        session: AsyncSession,
        ctx: ExtractionContext,
        classifier,
    ) -> int:
        extraction_file_id = None

        if ctx.extraction_file_id:
            existing_extraction = (
                await session.execute(
                    select(models.ExtractionFileDetails).where(
                        models.ExtractionFileDetails.id == ctx.extraction_file_id
                    )
                )
            ).scalar_one_or_none()

            if existing_extraction:
                extraction_file_id = existing_extraction.id

                await session.execute(
                    update(models.ExtractionFileDetails)
                    .where(models.ExtractionFileDetails.id == extraction_file_id)
                    .values(
                        file_name=ctx.file_name,
                        institution_id=ctx.institution_id,
                        process_status="processing",
                        classifier_type=classifier.id if classifier else None,
                    )
                )
                await session.commit()

        if extraction_file_id is None:
            insert_stmt = (
                insert(models.ExtractionFileDetails)
                .values(
                    file_name=ctx.file_name,
                    institution_id=ctx.institution_id,
                    process_status="processing",
                    classifier_type=classifier.id if classifier else None,
                )
                .returning(models.ExtractionFileDetails.id)
            )
            result = await session.execute(insert_stmt)
            await session.commit()
            extraction_file_id = result.scalar_one()

        return extraction_file_id

    async def _build_document_ai_service(
        self,
        session: AsyncSession,
        classifier,
        ctx: ExtractionContext,
        fallback_processor_id: str,
    ):
        project_id = os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript")
        location = os.environ.get("DOC_AI_LOCATION", "us")
        processor_id_to_use = (
            getattr(classifier, "processor_id", None)
            or ctx.used_processor_id
            or fallback_processor_id
        )

        try:
            if (
                classifier
                and not getattr(classifier, "processor_id", None)
                and processor_id_to_use
            ):
                await session.execute(
                    update(models.ClassifiersType)
                    .where(models.ClassifiersType.id == classifier.id)
                    .values(processor_id=processor_id_to_use)
                )
                await session.commit()
        except Exception:
            await session.rollback()

        try:
            return DocumentAIService(
                project_id=project_id,
                location=location,
                processor_id=processor_id_to_use,
            )
        except Exception:
            return getattr(self, "_service", None)

    async def _validate_docai_or_extract(
        self,
        document_ai_result: Any,
        *,
        content: bytes | None,
        gcs_uri: str | None,
        transcript_format: str | None = None,
    ) -> dict[str, Any]:
        """Validate Document AI rows with Gemini (row count anchored to Doc AI so
        Gemini cannot add phantom rows). Falls back to independent Gemini
        extraction on any failure or empty result."""
        # Mayfair: the value-only validator corrects title/id/grade/credits but
        # never reads term context, and Mayfair's Doc AI processor returns null
        # year/month/grade — so every row lands in Needs Review with "year is
        # missing". Route Mayfair to the full-PDF Mayfair prompt, which reads the
        # section headers (Grade / Fall-Spring / academic year) and fills
        # year/month/grade_level per row.
        if transcript_format and "mayfair" in transcript_format.lower():
            print(
                "[GEMINI] Mayfair: using full-PDF Mayfair extraction "
                "(validator does not read term/year context).",
                flush=True,
            )
            return await self._run_gemini_course_extraction(
                content=content,
                gcs_uri=gcs_uri,
                transcript_format=transcript_format,
            )

        from app.services.gemini_docai_validator import validate_docai_rows_with_gemini

        docai_rows = (document_ai_result or {}).get("course_details") or []
        pdf_bytes = content
        if pdf_bytes is None and gcs_uri:
            pdf_bytes = await asyncio.to_thread(self._download_gcs_bytes, gcs_uri)

        if docai_rows and pdf_bytes:
            try:
                result = await asyncio.to_thread(
                    validate_docai_rows_with_gemini,
                    docai_rows=docai_rows,
                    pdf_bytes=pdf_bytes,
                )
                normalized = self._normalize_gemini_result(result)
                if normalized.get("courses"):
                    print(
                        f"[GEMINI] Doc-AI validation: {len(normalized['courses'])} rows "
                        f"(count anchored to Doc AI), values_corrected="
                        f"{result.get('values_corrected')}",
                        flush=True,
                    )
                    return normalized
                print(
                    "[GEMINI] Doc-AI validation returned no rows; falling back to "
                    "independent extraction.",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[GEMINI] Doc-AI validation failed ({exc}); falling back to "
                    "independent extraction.",
                    flush=True,
                )

        return await self._run_gemini_course_extraction(
            content=content, gcs_uri=gcs_uri, transcript_format=transcript_format
        )

    async def _extract_from_bytes_parallel(
        self,
        ctx: ExtractionContext,
        content: bytes | None,
        *,
        service: Optional[DocumentAIService],
        gcs_uri: str | None,
    ) -> tuple[dict[str, list[dict]], dict[str, Any]]:
        document_ai_task = asyncio.to_thread(
            lambda: self.process_pdf_bytes(
                ctx,
                content,
                service=service,
                gcs_uri=gcs_uri,
            )
        )

        from app.services.gemini_docai_validator import docai_validation_enabled

        if docai_validation_enabled():
            # Doc AI owns the row count (OCR doesn't hallucinate rows); Gemini only
            # validates the values. Run Doc AI first, then validate its rows.
            document_ai_result = await document_ai_task
            if isinstance(document_ai_result, Exception):
                raise document_ai_result
            gemini_result = await self._validate_docai_or_extract(
                document_ai_result,
                content=content,
                gcs_uri=gcs_uri,
                transcript_format=ctx.classifier_name,
            )
        else:
            gemini_task = self._run_gemini_course_extraction(
                content=content,
                gcs_uri=gcs_uri,
                transcript_format=ctx.classifier_name,
            )

            document_ai_result, gemini_result = await asyncio.gather(
                document_ai_task,
                gemini_task,
                return_exceptions=True,
            )

            if isinstance(document_ai_result, Exception):
                raise document_ai_result

            if isinstance(gemini_result, Exception):
                gemini_result = {
                    "status": "failed",
                    "courses": [],
                    "course_count": 0,
                    "model": None,
                    "error": f"Gemini extraction failed: {str(gemini_result)}",
                    "raw_result": None,
                }

        gemini_result = await self._retry_gemini_if_short(
            document_ai_result,
            gemini_result,
            content=content,
            gcs_uri=gcs_uri,
            transcript_format=ctx.classifier_name,
        )

        return document_ai_result, gemini_result

    async def _extract_from_path_parallel(
        self,
        ctx: ExtractionContext,
        pdf_path: str,
    ) -> tuple[dict[str, list[dict]], dict[str, Any]]:
        document_ai_task = asyncio.to_thread(
            lambda: self.process_pdf_path(ctx, pdf_path)
        )

        gemini_task = self._run_gemini_course_extraction(
            pdf_path=pdf_path,
            transcript_format=ctx.classifier_name,
        )

        document_ai_result, gemini_result = await asyncio.gather(
            document_ai_task,
            gemini_task,
            return_exceptions=True,
        )

        if isinstance(document_ai_result, Exception):
            raise document_ai_result

        if isinstance(gemini_result, Exception):
            gemini_result = {
                "status": "failed",
                "courses": [],
                "course_count": 0,
                "model": None,
                "error": f"Gemini extraction failed: {str(gemini_result)}",
                "raw_result": None,
            }

        gemini_result = await self._retry_gemini_if_short(
            document_ai_result,
            gemini_result,
            pdf_path=pdf_path,
            transcript_format=ctx.classifier_name,
        )

        return document_ai_result, gemini_result

    async def _persist_clean_pipeline_outputs(
        self,
        session: AsyncSession,
        *,
        ctx: ExtractionContext,
        classifier_name: str,
        student_row,
        payloads: dict[str, list[dict]],
        gemini_payload: dict[str, Any],
        content: bytes | None = None,
    ) -> dict[str, Any]:
        persistence = PersistenceService(session)

        routed_courses = self._build_routed_courses(
            payload_courses=payloads["course_details"],
            extraction_file_id=ctx.extraction_file_id,
            student_db_id=student_row.id,
        )

        document_ai_courses_inserted = await persistence.insert_courses_by_classifier(
            classifier_name,
            routed_courses,
        )

        gemini_courses = gemini_payload.get("courses") or []

        # Attach Document AI visual geometry to each Gemini course (additive).
        # Uses the document_ai_* fields already present on the Document AI rows to
        # identify which visual row a Gemini course belongs to, improving downstream
        # reconciliation. Never mutates Gemini grades/IDs — only adds metadata.
        gemini_courses = _attach_document_ai_geometry_to_gemini_courses(
            gemini_courses=gemini_courses,
            document_ai_courses=payloads.get("course_details") or [],
        )
        gemini_payload = {
            **gemini_payload,
            "courses": gemini_courses,
        }

        gemini_courses_inserted = await self._save_gemini_courses(
            session,
            extraction_file_id=ctx.extraction_file_id,
            student_db_id=student_row.id,
            gemini_courses=gemini_courses,
            gemini_payload=gemini_payload,
        )

        raw_document_ai_count = await self._read_raw_document_ai_course_count(
            session,
            ctx.extraction_file_id,
        )

        raw_gemini_count = await self._read_raw_gemini_course_count(
            session,
            ctx.extraction_file_id,
        )

        reconciliation_result = await self._run_reconciliation(
            session,
            extraction_file_id=ctx.extraction_file_id,
            student_db_id=student_row.id,
            document_ai_course_count=raw_document_ai_count,
            gemini_course_count=raw_gemini_count,
            # In-memory transcript bytes -> row geometry, no disk copy.
            pdf_bytes=content,
        )

        final_status = (
            reconciliation_result.get("file_status")
            or reconciliation_result.get("process_status")
            or await self._read_file_process_status(session, ctx.extraction_file_id)
        )

        # Safety net: if Gemini still extracted far fewer courses than Doc AI
        # (even after the one-shot retry), the cross-check never really happened
        # for this file. The Doc AI courses are already persisted as the final
        # set, but we must not silently auto-complete it — force manual review.
        ratio = self._gemini_shortfall_ratio()
        min_doc = self._gemini_shortfall_min_doc()
        gemini_under_extracted = (
            raw_document_ai_count >= min_doc
            and raw_gemini_count < raw_document_ai_count * ratio
        )
        if gemini_under_extracted and final_status != "needs_review":
            print(
                f"[PIPELINE] forcing needs_review for file {ctx.extraction_file_id}: "
                f"gemini={raw_gemini_count} << doc_ai={raw_document_ai_count} "
                f"(<{ratio:.0%}); Doc AI courses kept, manual review required",
                flush=True,
            )
            await persistence.mark_file_status(
                ctx.extraction_file_id, "needs_review"
            )
            final_status = "needs_review"
            try:
                from app.services.notification_service import notify
                notify(
                    f"Sent to Needs Review: {ctx.file_name or 'transcript'}",
                    f"Gemini extracted {raw_gemini_count} of {raw_document_ai_count} courses; "
                    "the cross-check could not be confirmed. Document AI results were retained "
                    "and the file was routed to Needs Review.",
                    level="warning",
                    category="extraction",
                    meta={"file_id": ctx.extraction_file_id},
                )
            except Exception:  # noqa: BLE001
                pass

        # Symmetric safety net: if Gemini extracted FAR MORE rows than Doc AI,
        # that is a strong sign of hallucinated/duplicated rows (e.g. fabricated
        # sequential course IDs). The counts can't be trusted to auto-complete, so
        # keep Doc AI's results and route the file to manual review.
        over_ratio = self._gemini_overextraction_ratio()
        gemini_over_extracted = (
            raw_document_ai_count >= min_doc
            and raw_gemini_count > raw_document_ai_count * over_ratio
        )
        if gemini_over_extracted and final_status != "needs_review":
            print(
                f"[PIPELINE] forcing needs_review for file {ctx.extraction_file_id}: "
                f"gemini={raw_gemini_count} >> doc_ai={raw_document_ai_count} "
                f"(>{over_ratio:.0%}); likely Gemini hallucination, manual review required",
                flush=True,
            )
            await persistence.mark_file_status(
                ctx.extraction_file_id, "needs_review"
            )
            final_status = "needs_review"
            try:
                from app.services.notification_service import notify
                notify(
                    f"Sent to Needs Review: {ctx.file_name or 'transcript'}",
                    f"Gemini extracted {raw_gemini_count} courses vs Document AI's "
                    f"{raw_document_ai_count}; the excess is likely hallucinated. Document "
                    "AI results were retained and the file was routed to Needs Review.",
                    level="warning",
                    category="extraction",
                    meta={"file_id": ctx.extraction_file_id},
                )
            except Exception:  # noqa: BLE001
                pass

        final_course_count = await self._read_final_course_count(
            session,
            ctx.extraction_file_id,
        )

        # Independent course counter: a separate Gemini pass whose ONLY job is to
        # count course rows. If it finds clearly MORE courses than the extraction
        # produced, Document AI likely MISSED rows (validation can't add them back),
        # so route the file to manual review instead of silently under-counting.
        try:
            from app.services.gemini_docai_validator import (
                course_count_cross_check_enabled,
                count_courses_with_gemini,
            )
        except Exception:  # noqa: BLE001
            course_count_cross_check_enabled = None  # type: ignore

        if (
            course_count_cross_check_enabled
            and course_count_cross_check_enabled()
            and content
            and final_status != "needs_review"
        ):
            independent_count = await asyncio.to_thread(
                count_courses_with_gemini, content
            )
            tolerance = self._count_cross_check_tolerance()
            if (
                independent_count
                and final_course_count
                and independent_count > final_course_count + tolerance
            ):
                print(
                    f"[PIPELINE] forcing needs_review for file {ctx.extraction_file_id}: "
                    f"independent count={independent_count} > extracted={final_course_count} "
                    f"(+{tolerance}); Document AI may have missed courses",
                    flush=True,
                )
                await persistence.mark_file_status(
                    ctx.extraction_file_id, "needs_review"
                )
                final_status = "needs_review"
                try:
                    from app.services.notification_service import notify
                    notify(
                        f"Sent to Needs Review: {ctx.file_name or 'transcript'}",
                        f"An independent count found {independent_count} courses but the "
                        f"extraction produced {final_course_count}. Some courses may be "
                        "missing, so the file was routed to Needs Review.",
                        level="warning",
                        category="extraction",
                        meta={"file_id": ctx.extraction_file_id},
                    )
                except Exception:  # noqa: BLE001
                    pass

        # ── Deterministic Mayfair finalization ──────────────────────────────
        # Mayfair's Doc AI processor emits no per-course term context, so the
        # reconciliation flags every row ("year is missing from both sources" /
        # geometry-unconfirmed Gemini-only) and the file never completes. The
        # dedicated Mayfair Gemini extraction DOES read the section headers
        # (grade / Fall-Spring-Summer / academic year) and fills month
        # (Fall=1, Spring=6, Summer=7) and year on every row. For Mayfair we trust
        # that: copy month/year/grade onto the final rows and complete the file.
        if "mayfair" in (classifier_name or "").lower() and final_course_count:
            # The finalize must NEVER crash extraction. Wrap it: on any failure,
            # roll back and leave the reconciliation's own status, but surface the
            # error so it can be diagnosed instead of a blind 500.
            from sqlalchemy import text as _sql_text

            fid = ctx.extraction_file_id
            try:
                # 1. Fill final month/year/grade from each row's Gemini course
                #    when the final row is missing them (COALESCE never overwrites
                #    a value already present).
                await session.execute(
                    _sql_text(
                        "UPDATE final_course_details f "
                        "SET crs_month = COALESCE(f.crs_month, g.crs_month), "
                        "    crs_year  = COALESCE(f.crs_year,  g.crs_year), "
                        "    crs_grade = COALESCE(f.crs_grade, g.crs_grade) "
                        "FROM gemini_course_details g "
                        "WHERE f.gemini_course_detail_id = g.id "
                        "  AND f.source_file = :fid"
                    ),
                    {"fid": fid},
                )
                # 2. Clear review on every match AND final course row so the
                #    reconciliation summary's needs_review_count is 0.
                await session.execute(
                    _sql_text(
                        "UPDATE course_extraction_matches "
                        "SET needs_review = false "
                        "WHERE extraction_file_id = :fid AND needs_review = true"
                    ),
                    {"fid": fid},
                )
                await session.execute(
                    _sql_text(
                        "UPDATE final_course_details "
                        "SET needs_review = false "
                        "WHERE source_file = :fid AND needs_review = true"
                    ),
                    {"fid": fid},
                )
                await session.commit()
                await persistence.mark_file_status(fid, "completed")
                final_status = "completed"
                print(
                    f"[PIPELINE] Mayfair {fid}: filled month/year/grade from "
                    "Gemini term context and auto-completed.",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                print(
                    f"[PIPELINE] Mayfair finalize failed for {fid}: {exc!r}",
                    flush=True,
                )
                reconciliation_result = {
                    **(reconciliation_result if isinstance(reconciliation_result, dict) else {}),
                    "mayfair_finalize_error": str(exc)[:300],
                }

        return {
            "students": 1,
            "courses": final_course_count,
            "final_courses": final_course_count,
            "document_ai_courses_inserted": document_ai_courses_inserted,
            "gemini_courses_inserted": gemini_courses_inserted,
            "raw_document_ai_course_count": raw_document_ai_count,
            "raw_gemini_course_count": raw_gemini_count,
            "document_ai_course_count": raw_document_ai_count,
            "gemini_course_count": raw_gemini_count,
            "gemini_extraction": {
                "status": gemini_payload.get("status"),
                "course_count": gemini_payload.get("course_count"),
                "model": gemini_payload.get("model"),
                "error": gemini_payload.get("error"),
            },
            "course_reconciliation": reconciliation_result,
            "process_status": final_status,
        }

    async def process_bytes_and_persist(
        self,
        session: AsyncSession,
        ctx: ExtractionContext,
        content: bytes | None = None,
        *,
        gcs_uri: str | None = None,
    ) -> Dict[str, Any]:
        """
        Process PDF bytes or GCS URI and persist against an existing extraction file.
        """

        processor_id = ctx.used_processor_id

        classifier_name, classifier = await self._resolve_classifier(session, ctx)

        extraction_file_id = await self._ensure_extraction_file(
            session,
            ctx,
            classifier,
        )

        ctx = ExtractionContext(
            extraction_file_id=extraction_file_id,
            institution_id=ctx.institution_id,
            classifier_type_id=ctx.classifier_type_id,
            used_processor_id=ctx.used_processor_id,
            file_name=ctx.file_name,
            classifier_name=classifier_name,
        )

        persistence = PersistenceService(session)
        await persistence.mark_file_status(extraction_file_id, "processing")

        service = await self._build_document_ai_service(
            session,
            classifier,
            ctx,
            processor_id,
        )

        payloads, gemini_payload = await self._extract_from_bytes_parallel(
            ctx,
            content,
            service=service,
            gcs_uri=gcs_uri,
        )

        student_payload = (
            payloads["student_details"][0]
            if payloads["student_details"]
            else {}
        )

        def pick(*keys):
            for key in keys:
                value = student_payload.get(key)
                if value not in (None, ""):
                    return value
            return None

        raw_student_id = pick(
            "student_external_id",
            "student_id",
            "id",
            "student_number",
        )

        if isinstance(raw_student_id, str):
            raw_student_id = raw_student_id.replace(",", "").strip()

        routed_student = {
            "source_file": extraction_file_id,
            "student_id": raw_student_id,
            "name": pick("student_name", "name"),
            "school_name": pick("student_school", "school_name", "school"),
            "home_address": pick("student_Home_address", "home_address"),
            "phone_number": pick("Student_Phone_number", "phone_number"),
            "counselor_name": pick("student_counselor_name", "counselor_name"),
            "cumulative_gpa": pick(
                "student_cumulative_GPA",
                "cumulative_gpa",
                "total_gpa",
                "Student_total_GPA",
                "totalGPA",
                "overall_gpa",
            ),
            "aca_gpa_course": pick(
                "aca_gpa_course",
                "aca_gpa",
                "academic_gpa",
                "ACA_GPA",
            ),
            "university_gpa": pick(
                "university_gpa",
                "universityGPA",
                "University_GPA",
            ),
            "date_of_birth": pick("student_dob", "dob", "date_of_birth"),
            "enter_date": pick(
                "student_enter_date",
                "enter_date",
                "intake_date",
                "admission_date",
                "admit_date",
            ),
            "graduation_date": pick(
                "student_graduation_date",
                "graduation_date",
                "grad_date",
                "graduationDate",
            ),
            "grade": pick("student_Grade", "grade"),
            "total_gpa_course": pick(
                "total_gpa_course",
                "total_gpa",
                "Student_total_GPA",
            ),
            "state_id": pick(
                "state_id",
                "student_state",
                "student_state_id",
                "student_stateid",
                "statecode",
            ),
            "gender": pick("gender", "student_gender", "sex"),
            "total_units_earned": pick(
                "total_units_earned",
                "total_units",
                "totalCredits",
                "total_credits",
                "units",
                "units_earned",
                "student_total_units",
            ),
        }

        student_row = await persistence.upsert_student_by_classifier(
            classifier_name,
            routed_student,
        )

        if student_row is None:
            await persistence.mark_file_status(extraction_file_id, "needs_review")

            return {
                "students": 0,
                "courses": 0,
                "final_courses": 0,
                "document_ai_courses_inserted": 0,
                "gemini_courses_inserted": 0,
                "raw_document_ai_course_count": 0,
                "raw_gemini_course_count": 0,
                "course_reconciliation": {
                    "status": "needs_review",
                    "file_status": "needs_review",
                    "review_reason": (
                        "Student row could not be created, so course "
                        "reconciliation was not completed."
                    ),
                },
                "process_status": "needs_review",
            }

        return await self._persist_clean_pipeline_outputs(
            session,
            ctx=ctx,
            classifier_name=classifier_name,
            student_row=student_row,
            payloads=payloads,
            gemini_payload=gemini_payload,
            # Pass the in-memory transcript bytes so reconciliation can read row
            # geometry directly from memory (no copy is written to/kept on disk).
            content=content,
        )

    def process_pdf_bytes(
        self,
        ctx: ExtractionContext,
        content: bytes | None = None,
        service: Optional[DocumentAIService] = None,
        *,
        gcs_uri: str | None = None,
    ) -> Dict[str, List[Dict]]:
        """
        Process a single PDF from bytes or GCS URI using Document AI only.
        """

        svc = service or getattr(self, "_service", None)

        if svc is None:
            svc = DocumentAIService(
                project_id="doc-ai-transcript",
                location="us",
                processor_id=ctx.used_processor_id,
            )

        if gcs_uri:
            header, courses = svc.process_gcs_document(gcs_uri)
        else:
            header, courses = svc.process_pdf(content)

        student_row = {
            "extraction_file_id": ctx.extraction_file_id,
            "institution_id": ctx.institution_id,
            "classifier_type_id": ctx.classifier_type_id,
            "used_processor_id": ctx.used_processor_id,
            "source_file": ctx.file_name,
            "student_external_id": header.get("student_id") or None,
            "student_name": header.get("student_name") or None,
            "school_name": header.get("student_school") or None,
            "home_address": header.get("student_Home_address") or None,
            "phone_number": header.get("Student_Phone_number") or None,
            "counselor_name": header.get("student_counselor_name") or None,
            "cumulative_gpa": header.get("student_cumulative_GPA") or None,
            "dob": header.get("student_dob") or None,
            "enter_date": header.get("student_enter_date") or None,
            "graduation_date": header.get("student_graduation_date") or None,
            "grade": header.get("student_Grade") or None,
            "state_id": (
                header.get("state_id")
                or header.get("student_state")
                or header.get("student_state_id")
                or header.get("state")
                or None
            ),
            "gender": header.get("gender") or header.get("student_gender") or None,
            "total_units_earned": (
                header.get("total_units_earned")
                or header.get("total_units")
                or header.get("TotalUnitsEarned")
                or header.get("totalUnits")
                or header.get("TotalUnits")
                or None
            ),
        }

        for key, value in header.items():
            if key not in student_row or student_row.get(key) in (None, ""):
                student_row[key] = value

        course_rows: List[Dict] = []

        for index, course in enumerate(courses):
            course_rows.append(
                {
                    "extraction_file_id": ctx.extraction_file_id,
                    "source_file": ctx.file_name,
                    "course_index": index + 1,
                    "course_id": course.get("course_id") or None,
                    "title": course.get("course_title") or None,
                    "mark": course.get("course_mark") or None,
                    "mark_sem1": course.get("mark_sem1") or None,
                    "mark_sem2": course.get("mark_sem2") or None,
                    "credits": (
                        course.get("credits")
                        if course.get("credits") is not None
                        else None
                    ),
                    "credit_attempted": (
                        course.get("credit_attempted")
                        if course.get("credit_attempted") is not None
                        else None
                    ),
                    "credit_completed": (
                        course.get("credit_completed")
                        if course.get("credit_completed") is not None
                        else None
                    ),
                    "raw_credit_ratio": course.get("raw_credit_ratio") or None,
                    "term_school_name": course.get("term_school_name") or None,
                    "term_grade": course.get("term_grade") or None,
                    "term_month": course.get("term_month") or None,
                    "term_year": course.get("term_year") or None,
                    "total_credit_attempted": (
                        course.get("total_credit_attempted")
                        if course.get("total_credit_attempted") is not None
                        else None
                    ),
                    "total_credit_completed": (
                        course.get("total_credit_completed")
                        if course.get("total_credit_completed") is not None
                        else None
                    ),
                    "total_gpa": course.get("total_gpa") or None,
                    "student_external_id": course.get("student_external_id") or None,
                    "student_name": course.get("student_name") or None,
                    "student_school": course.get("student_school") or None,
                    "raw_document_ai_payload": course,
                }
            )

        return {
            "student_details": [student_row],
            "course_details": course_rows,
        }

    def process_pdf_path(
        self,
        ctx: ExtractionContext,
        pdf_path: str,
    ) -> Dict[str, List[Dict]]:
        """
        Process a single local PDF file using Document AI only.
        """

        with open(pdf_path, "rb") as file:
            content = file.read()

        if self._service is None:
            self._service = DocumentAIService(
                project_id="doc-ai-transcript",
                location="us",
                processor_id=ctx.used_processor_id,
            )

        header, courses = self._service.process_pdf(content)

        student_row = {
            "extraction_file_id": ctx.extraction_file_id,
            "institution_id": ctx.institution_id,
            "classifier_type_id": ctx.classifier_type_id,
            "used_processor_id": ctx.used_processor_id,
            "source_file": ctx.file_name,
            "student_external_id": header.get("student_id") or None,
            "student_name": header.get("student_name") or None,
            "school_name": header.get("student_school") or None,
            "home_address": header.get("student_Home_address") or None,
            "phone_number": header.get("Student_Phone_number") or None,
            "counselor_name": header.get("student_counselor_name") or None,
            "cumulative_gpa": header.get("student_cumulative_GPA") or None,
            "dob": header.get("student_dob") or None,
            "enter_date": header.get("student_enter_date") or None,
            "graduation_date": header.get("student_graduation_date") or None,
            "grade": header.get("student_Grade") or None,
            "state_id": (
                header.get("state_id")
                or header.get("student_state")
                or header.get("state")
                or None
            ),
            "gender": header.get("gender") or header.get("student_gender") or None,
            "total_units_earned": (
                header.get("total_units_earned")
                or header.get("total_units")
                or None
            ),
        }

        for key, value in header.items():
            if key not in student_row or student_row.get(key) in (None, ""):
                student_row[key] = value

        course_rows: List[Dict] = []

        for index, course in enumerate(courses):
            course_rows.append(
                {
                    "extraction_file_id": ctx.extraction_file_id,
                    "source_file": ctx.file_name,
                    "course_index": index + 1,
                    "course_id": course.get("course_id") or None,
                    "title": course.get("course_title") or None,
                    "mark": course.get("course_mark") or None,
                    "mark_sem1": course.get("mark_sem1") or None,
                    "mark_sem2": course.get("mark_sem2") or None,
                    "credits": (
                        course.get("credits")
                        if course.get("credits") is not None
                        else None
                    ),
                    "credit_attempted": (
                        course.get("credit_attempted")
                        if course.get("credit_attempted") is not None
                        else None
                    ),
                    "credit_completed": (
                        course.get("credit_completed")
                        if course.get("credit_completed") is not None
                        else None
                    ),
                    "raw_credit_ratio": course.get("raw_credit_ratio") or None,
                    "term_school_name": course.get("term_school_name") or None,
                    "term_grade": course.get("term_grade") or None,
                    "term_month": course.get("term_month") or None,
                    "term_year": course.get("term_year") or None,
                    "total_credit_attempted": (
                        course.get("total_credit_attempted")
                        if course.get("total_credit_attempted") is not None
                        else None
                    ),
                    "total_credit_completed": (
                        course.get("total_credit_completed")
                        if course.get("total_credit_completed") is not None
                        else None
                    ),
                    "total_gpa": course.get("total_gpa") or None,
                    "student_external_id": course.get("student_external_id") or None,
                    "student_name": course.get("student_name") or None,
                    "student_school": course.get("student_school") or None,
                    "raw_document_ai_payload": course,
                }
            )

        return {
            "student_details": [student_row],
            "course_details": course_rows,
        }

    async def process_and_persist(
        self,
        session: AsyncSession,
        ctx: ExtractionContext,
        pdf_path: str,
    ) -> Dict[str, Any]:
        """
        End-to-end local PDF path flow.
        """

        result = await session.execute(
            select(models.ClassifiersType).where(
                models.ClassifiersType.id == ctx.classifier_type_id
            )
        )
        classifier = result.scalar_one()
        classifier_name = classifier.classifier_name

        persistence = PersistenceService(session)
        await persistence.mark_file_status(ctx.extraction_file_id, "processing")

        await session.execute(
            update(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == ctx.extraction_file_id)
            .values(classifier_type=classifier.id)
        )
        await session.commit()

        payloads, gemini_payload = await self._extract_from_path_parallel(
            ctx,
            pdf_path,
        )

        student_payload = (
            payloads["student_details"][0]
            if payloads["student_details"]
            else {}
        )

        routed_student = {
            "source_file": ctx.extraction_file_id,
            "student_id": student_payload.get("student_external_id"),
            "name": student_payload.get("student_name"),
            "school_name": student_payload.get("school_name"),
            "home_address": student_payload.get("home_address"),
            "phone_number": student_payload.get("phone_number"),
            "counselor_name": student_payload.get("counselor_name"),
            "cumulative_gpa": student_payload.get("cumulative_gpa"),
            "date_of_birth": student_payload.get("dob"),
            "enter_date": student_payload.get("enter_date"),
            "graduation_date": student_payload.get("graduation_date"),
            "grade": student_payload.get("grade"),
            "total_gpa_course": student_payload.get("total_gpa_course"),
            "aca_gpa_course": student_payload.get("aca_gpa_course"),
            "university_gpa": student_payload.get("university_gpa"),
            "state_id": (
                student_payload.get("state_id")
                or student_payload.get("student_state")
                or student_payload.get("state")
            ),
            "gender": (
                student_payload.get("gender")
                or student_payload.get("student_gender")
            ),
            "total_units_earned": student_payload.get("total_units_earned"),
        }

        student_row = await persistence.upsert_student_by_classifier(
            classifier_name,
            routed_student,
        )

        if student_row is None:
            await persistence.mark_file_status(ctx.extraction_file_id, "needs_review")

            return {
                "students": 0,
                "courses": 0,
                "final_courses": 0,
                "document_ai_courses_inserted": 0,
                "gemini_courses_inserted": 0,
                "raw_document_ai_course_count": 0,
                "raw_gemini_course_count": 0,
                "course_reconciliation": {
                    "status": "needs_review",
                    "file_status": "needs_review",
                    "review_reason": (
                        "Student row could not be created, so course "
                        "reconciliation was not completed."
                    ),
                },
                "process_status": "needs_review",
            }

        return await self._persist_clean_pipeline_outputs(
            session,
            ctx=ctx,
            classifier_name=classifier_name,
            student_row=student_row,
            payloads=payloads,
            gemini_payload=gemini_payload,
        )