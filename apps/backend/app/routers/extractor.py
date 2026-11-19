from __future__ import annotations

import asyncio
import json
import re as _re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, noload


# A transcript whose row is in one of these states is already done or in flight,
# so a duplicate 'uploaded' twin of it must not be counted as "Not Processed".
_HANDLED_TWIN_STATUSES = ("completed", "needs_review", "needs_review_audit", "processing")


def _processed_twin_exists(outer):
    """EXISTS clause: another extraction row for the SAME transcript (same term +
    same file base name) that is already completed / needs_review / needs_review_audit / processing.

    A transcript can be ingested more than once — the raw upload (e.g.
    "Ojas-test/x.pdf", left at status 'uploaded') and a later processed/in-flight
    copy ("x.pdf"). The stale upload twin would otherwise show under "Not
    Processed" even though that transcript is already done or being extracted.
    This predicate lets the count and the list ignore an un-processed row whose
    transcript is already handled elsewhere. Match is by file base name (path
    stripped) within the same term.
    """
    from sqlalchemy import func as _func

    P = aliased(models.ExtractionFileDetails)
    return (
        select(1)
        .where(
            P.id != outer.id,
            P.process_status.in_(_HANDLED_TWIN_STATUSES),
            _func.coalesce(P.year_intake, "") == _func.coalesce(outer.year_intake, ""),
            _func.regexp_replace(P.file_name, "^.*/", "")
            == _func.regexp_replace(outer.file_name, "^.*/", ""),
        )
        .exists()
    )


# Statuses that are NOT part of the "Human Review with Audit" backlog:
#   - done / awaiting review / in-flight / new type (each handled elsewhere), and
#   - "uploaded": a file that's been uploaded and (auto-)classified but NOT yet
#     extracted. Those belong ONLY on Upload + Classify until they're extracted,
#     so they must not appear in the audit backlog.
_NOT_PROCESSED_HANDLED_STATUSES = (
    "completed",
    "needs_review",
    "processing",
    "new_type",
    "uploaded",
)


def _not_processed_conditions(F):
    """The single definition of a "Human Review with Audit" (not-processed) row,
    shared by the /not-processed list AND the /section-counts badge so the count
    and the list can never disagree: any row that isn't completed / needs_review /
    processing / new_type / uploaded, whose transcript isn't already handled under
    a twin row. Returns predicates to splat into ``.where(*conds)``."""
    return [
        or_(
            F.process_status.is_(None),
            F.process_status.notin_(_NOT_PROCESSED_HANDLED_STATUSES),
        ),
        ~_processed_twin_exists(F),
    ]


from app import models
from app.db import get_session, AsyncSessionLocal
from app.services.cloud_storage_service import CloudStorageService

router = APIRouter(prefix="/extractor", tags=["extractor"])

# Cache only the resolved GCS object name (not PDF bytes) so repeated Review
# opens do not rescan storage. Bytes remain streamed per request.
_PDF_BLOB_NAME_CACHE: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Backend helpers - clean 4-table flow
#
# course_details = raw Document AI rows
# gemini_course_details = raw Gemini rows
# course_extraction_matches = row-by-row comparison decisions
# final_course_details = trusted final rows used by frontend/admission
#
# This router does NOT use old validation tables.
# ---------------------------------------------------------------------------

_COURSE_TYPE_MAP: dict[str, str] = {
    "H": "Honors",
    "HP": "Honors",
    "N": "Non-Academic",
    "P": "CSU/UC a-g Course",
    "R": "Repeat",
    "PR": "Repeat",
    "IN": "Independent Study",
    "W": "Withdrawn",
}

_AG_LETTER_MAP: dict[str, str] = {
    "a": "History / Social Science",
    "b": "English",
    "c": "Mathematics",
    "d": "Laboratory Science",
    "e": "Language other than English",
    "f": "Visual and Performing Arts",
    "g": "College-Preparatory Elective",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _first_non_empty(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    if isinstance(value, Decimal):
        return float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        match = _re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group(0)) if match else None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        match = _re.search(r"-?\d+", str(value))
        return int(match.group(0)) if match else None


def _parse_new_transcript_identifier(
    value: Any,
    *,
    field_name: str,
) -> int | None:
    """
    Parse an identifier for the isolated integer ID columns without silently
    changing what the user entered.

    Values such as ``001234`` and ``ABC123`` cannot be represented faithfully
    by the current BIGINT columns. They must be rejected instead of becoming
    ``1234`` or ``123``.
    """
    if value in (None, ""):
        return None

    if isinstance(value, bool):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a whole-number identifier.",
        )

    if isinstance(value, int):
        parsed = value
    else:
        raw = str(value).strip()
        if not _re.fullmatch(r"\d+", raw):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field_name} cannot be stored exactly in the current "
                    "integer database column. Use digits only."
                ),
            )
        if len(raw) > 1 and raw.startswith("0"):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field_name} begins with zero and cannot be stored "
                    "without changing its value in the current integer "
                    "database column."
                ),
            )
        parsed = int(raw)

    if parsed < 0:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} cannot be negative.",
        )

    if parsed > 9_223_372_036_854_775_807:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} is too large for the database column.",
        )

    return parsed


def _to_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value in (None, ""):
        return default

    if isinstance(value, (int, float, Decimal)):
        return bool(value)

    normalized = str(value).strip().lower()

    if normalized in {"1", "true", "yes", "y", "on", "reviewed", "resolved"}:
        return True

    if normalized in {"0", "false", "no", "n", "off", "unreviewed", "pending"}:
        return False

    return default


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

    match = _re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def _normalize_action(value: Any) -> str:
    return (
        str(value or "")
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        .strip()
    )


def _normalize_school_text(value: Any) -> str:
    text = str(value or "").upper()
    text = text.replace(".", " ")
    text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = _re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def _is_st_anthony_value(value: Any) -> bool:
    text = _normalize_school_text(value)

    return (
        "ST ANTHONY" in text
        or "SAINT ANTHONY" in text
    )


def _is_st_anthony_student_or_file(
    student: models.Students | None,
    source_file: Any | None = None,
) -> bool:
    values: list[Any] = []

    if student is not None:
        values.extend(
            [
                _get_attr(student, "hs_name", "school", "school_name"),
                _get_attr(student, "s_name"),
            ]
        )

    if source_file is not None:
        values.extend(
            [
                _get_attr(source_file, "file_name"),
                _get_attr(source_file, "transcript_format"),
                _get_attr(source_file, "school_name", "school"),
                _get_attr(source_file, "classifier_label", "classification_label"),
                _get_attr(source_file, "transcript_type"),
            ]
        )

    return any(_is_st_anthony_value(value) for value in values if value not in (None, ""))


def _is_st_anthony_course(course: Any) -> bool:
    return any(
        _is_st_anthony_value(value)
        for value in [
            _get_attr(course, "crs_hs", "school", "school_name"),
            _get_attr(course, "source_label", "source"),
            _get_attr(course, "final_source"),
        ]
        if value not in (None, "")
    )


def _normalize_final_source(value: Any) -> str:
    """
    DB-safe final_source normalizer.

    final_course_details.final_source has a check constraint, so frontend display
    labels like "Document AI + Gemini" must never be written directly.
    """

    text = str(value or "").strip().lower()

    if not text:
        return "merged"

    text = text.replace("-", "_").replace(" ", "_")

    if "document" in text and "gemini" in text:
        return "merged"

    if "doc_ai" in text and "gemini" in text:
        return "merged"

    if "both" in text or "merged" in text or "reconciled" in text:
        return "merged"

    if "manual" in text or "user" in text:
        return "manual"

    if "gemini" in text:
        return "gemini"

    if "document" in text or "doc_ai" in text or "docai" in text:
        return "document_ai"

    return "merged"


def _normalize_review_status(value: Any, *, needs_review: bool = False) -> str:
    """
    DB-safe review_status normalizer.

    final_course_details.review_status has a check constraint. Frontend/user
    labels like "reviewed", "resolved", or "keep" must not be written directly.
    The final table should use only:
    - "needs_review" while a row still blocks completion
    - "auto_resolved" once the row is resolved or user-reviewed
    """

    text = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    if needs_review:
        return "needs_review"

    if text in {"needs_review", "manual_review", "review_required", "unresolved"}:
        return "needs_review"

    return "auto_resolved"


def _is_resolved_review_status(value: Any) -> bool:
    text = _normalize_action(value)

    return text in {
        "reviewed",
        "resolved",
        "auto_resolved",
        "accept_final",
        "accepted",
        "keep",
    }


def _payload_is_remove_action(payload: dict | None) -> bool:
    payload = payload or {}

    values = [
        payload.get("action"),
        payload.get("resolution"),
        payload.get("resolution_reason"),
        payload.get("review_status"),
        payload.get("status"),
    ]

    return any("remove" in _normalize_action(value) for value in values)


def _payload_has_course_update_fields(payload: dict | None) -> bool:
    payload = payload or {}

    course_keys = {
        "name",
        "course_name",
        "crs_description",
        "grade",
        "letter_grade",
        "crs_letter_grade",
        "credits",
        "credits_completed",
        "credit_completed",
        "crs_credit_completed",
        "credits_attempted",
        "credit_attempted",
        "crs_credit_attempted",
        "crs_id",
        "course_id",
        "grade_level",
        "crs_grade",
        "month",
        "crs_month",
        "year",
        "crs_year",
        "school",
        "school_name",
        "crs_hs",
        "source",
        "final_source",
        "extraction_source",
        "reviewed_by_user",
        "mark_reviewed",
        "review_status",
        "needs_review",
    }

    return any(key in payload for key in course_keys)


def _safe_json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    return {}


def _filter_model_values(model_cls: Any, values: dict[str, Any]) -> dict[str, Any]:
    columns = set(model_cls.__table__.columns.keys())

    return {
        key: value
        for key, value in values.items()
        if key in columns
    }


def _has_column(model_cls: Any, column_name: str) -> bool:
    return column_name in set(model_cls.__table__.columns.keys())


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


def _student_column(model_cls: Any):
    columns = set(model_cls.__table__.columns.keys())

    if "s_id" in columns:
        return getattr(model_cls, "s_id")

    if "student_id" in columns:
        return getattr(model_cls, "student_id")

    return None


def _get_attr(row: Any, *names: str) -> Any:
    for name in names:
        if hasattr(row, name):
            value = getattr(row, name)
            if value not in (None, ""):
                return value
    return None


def _set_if_has(row: Any, field_name: str, value: Any) -> None:
    if hasattr(row, field_name):
        setattr(row, field_name, value)


def _apply_model_values(
    row: Any,
    values: dict[str, Any],
    *,
    skip_created_at: bool = True,
    skip_none: bool = True,
) -> None:
    for key, value in values.items():
        if skip_created_at and key == "created_at":
            continue

        if skip_none and value is None:
            continue

        if hasattr(row, key):
            setattr(row, key, value)


def _get_course_type(crs_id) -> str | None:
    if not crs_id:
        return None

    s = _re.sub(r"^[^A-Za-z]+", "", str(crs_id).strip())
    m = _re.match(r"^([A-Za-z]+)", s)

    if not m:
        return None

    prefix = m.group(1).upper()
    return _COURSE_TYPE_MAP.get(prefix, prefix)


def _get_course_category(crs_id, mapped_data: dict | None = None) -> str | None:
    if mapped_data:
        ag_desc = mapped_data.get("crs_ag_category_description")
        if ag_desc:
            return ag_desc

        ag_letter = (mapped_data.get("crs_ag_category_letter") or "").lower().strip()
        if ag_letter:
            return _AG_LETTER_MAP.get(ag_letter)

    return _get_course_type(crs_id)


def _grade_to_points(grade) -> float | None:
    if grade is None:
        return None

    g = str(grade).strip().upper()

    table = {
        "A+": 4.0,
        "A": 4.0,
        "A-": 3.7,
        "B+": 3.3,
        "B": 3.0,
        "B-": 2.7,
        "C+": 2.3,
        "C": 2.0,
        "C-": 1.7,
        "D+": 1.3,
        "D": 1.0,
        "D-": 0.7,
        "F": 0.0,
    }

    if g in table:
        return table[g]

    try:
        n = float(g)
        if n >= 90:
            return 4.0
        if n >= 80:
            return 3.0
        if n >= 70:
            return 2.0
        if n >= 60:
            return 1.0
        return 0.0
    except (ValueError, TypeError):
        return None


def _recalculate_gpa(serialized_courses: list[dict]) -> float | None:
    total_points = 0.0
    total_credits = 0.0

    for course in serialized_courses:
        try:
            credits = float(
                course.get("credits_completed")
                or course.get("credits")
                or 0
            )
        except (TypeError, ValueError):
            credits = 0.0

        points = _grade_to_points(course.get("grade"))

        if points is not None and credits > 0:
            total_points += points * credits
            total_credits += credits

    if total_credits == 0:
        return None

    return round(total_points / total_credits, 2)


def _recalculate_gpa_from_raw(final_courses: list[Any]) -> float | None:
    """Same GPA math as _recalculate_gpa but straight off the raw final_course
    rows — so the slim list response can include the GPA without serializing
    every course."""
    total_points = 0.0
    total_credits = 0.0

    for course in final_courses:
        try:
            credits = float(
                _get_attr(course, "crs_credit_completed", "credit_completed", "credits_completed")
                or _get_attr(course, "crs_credit_attempted", "credit_attempted", "credits_attempted")
                or 0
            )
        except (TypeError, ValueError):
            credits = 0.0

        points = _grade_to_points(
            _get_attr(course, "crs_letter_grade", "letter_grade", "grade")
        )

        if points is not None and credits > 0:
            total_points += points * credits
            total_credits += credits

    if total_credits == 0:
        return None

    return round(total_points / total_credits, 2)


def _course_has_required_fields(
    course: Any,
    *,
    st_anthony: bool = False,
) -> bool:
    course_id = _get_attr(course, "crs_id", "course_id")
    name = _get_attr(course, "crs_description", "course_name", "name")
    grade = _get_attr(course, "crs_letter_grade", "letter_grade", "grade")
    grade_level = _get_attr(course, "crs_grade", "grade_level")
    year = _get_attr(course, "crs_year", "year")
    credits = _first_non_empty(
        _get_attr(
            course,
            "crs_credit_completed",
            "credit_completed",
            "credits_completed",
        ),
        _get_attr(
            course,
            "crs_credit_attempted",
            "credit_attempted",
            "credits_attempted",
        ),
    )

    # Month is intentionally not required for completion.
    #
    # St. Anthony/Saint Anthony special rule:
    # - course_id is not required because the transcript does not consistently
    #   carry course IDs.
    # - credits ARE required. If credits are missing, the row should stay
    #   Needs Review.
    if st_anthony or _is_st_anthony_course(course):
        return bool(
            name
            and grade
            and grade_level is not None
            and year is not None
            and credits is not None
        )

    return bool(
        course_id
        and name
        and grade
        and grade_level is not None
        and year is not None
        and credits is not None
    )


def _is_student_complete(
    student: models.Students,
    final_courses: list[Any],
    source_file: Any | None = None,
) -> bool:
    if not student.s_name:
        return False

    if not final_courses:
        return False

    st_anthony = _is_st_anthony_student_or_file(student, source_file)

    return not any(
        not _course_has_required_fields(course, st_anthony=st_anthony)
        for course in final_courses
    )


def _get_file_status(source_file) -> str | None:
    if source_file is None:
        return None

    return getattr(source_file, "process_status", None)


def _final_course_model():
    return _require_model(
        "FinalCourseDetails",
        "FinalCourseDetail",
        "Final_course_details",
    )


def _gemini_course_model():
    return _require_model(
        "GeminiCourseDetails",
        "GeminiCourseDetail",
        "Gemini_course_details",
        "GeminiCourse_details",
    )


def _match_model():
    return _require_model(
        "CourseExtractionMatches",
        "CourseExtractionMatch",
        "Course_extraction_matches",
    )


def _new_transcript_student_model():
    return _require_model("NewTranscriptStudents")


def _new_transcript_course_model():
    return _require_model("NewTranscriptCourseDetails")


def _encode_new_record_id(value: Any) -> int | None:
    """
    Keep IDs from the isolated new-transcript tables from colliding with IDs
    from student_details/final_course_details in the existing frontend routes.
    Existing-table IDs remain positive; isolated-table IDs are exposed as
    negative integers and decoded by this router before database access.
    """
    parsed = _to_int(value)
    return -abs(parsed) if parsed is not None else None


def _decode_new_record_id(value: Any) -> int | None:
    parsed = _to_int(value)
    if parsed is None or parsed >= 0:
        return None
    return abs(parsed)


async def _is_new_transcript_file(
    session: AsyncSession,
    file_id: int,
) -> bool:
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    # A non-transcript/uncertain Gemini result intentionally creates no student
    # or course rows but is still routed to the isolated Audit workflow.
    file_status = (
        await session.execute(
            select(models.ExtractionFileDetails.process_status).where(
                models.ExtractionFileDetails.id == file_id
            )
        )
    ).scalar_one_or_none()
    if str(file_status or "").lower().strip() == "needs_review_audit":
        return True

    student_exists = (
        await session.execute(
            select(NewTranscriptStudents.id)
            .where(NewTranscriptStudents.source_file == file_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    if student_exists is not None:
        return True

    course_exists = (
        await session.execute(
            select(NewTranscriptCourseDetails.id)
            .where(NewTranscriptCourseDetails.source_file == file_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    return course_exists is not None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _field_decisions_from_final_row(row: Any) -> dict:
    value = _get_attr(row, "field_decisions", "field_sources", "source_summary")
    parsed = _safe_json_dict(value)

    if parsed:
        return parsed

    possible_sources = {
        "course_id": _get_attr(row, "crs_id_source"),
        "course_name": _get_attr(row, "crs_description_source"),
        "letter_grade": _get_attr(row, "crs_letter_grade_source"),
        "school": _get_attr(row, "crs_hs_source"),
        "grade_level": _get_attr(row, "crs_grade_source"),
        "month": _get_attr(row, "crs_month_source"),
        "year": _get_attr(row, "crs_year_source"),
        "credit_attempted": _get_attr(row, "crs_credit_attempted_source"),
        "credit_completed": _get_attr(row, "crs_credit_completed_source"),
        "term_gpa": _get_attr(row, "crs_term_gpa_source"),
    }

    return {
        key: value
        for key, value in possible_sources.items()
        if value not in (None, "")
    }


def _gemini_corrected_fields(field_decisions: dict) -> list[str]:
    corrected = []

    for field_name, source in field_decisions.items():
        source_text = str(source or "").lower()

        if "gemini" in source_text:
            corrected.append(field_name)

    return corrected


def _display_source_from_final_source(final_source: str | None) -> str:
    source = _normalize_final_source(final_source)

    if source == "merged":
        return "Document AI + Gemini"

    if source == "document_ai":
        return "Document AI"

    if source == "gemini":
        return "Gemini"

    if source == "manual":
        return "Manual"

    return "Document AI + Gemini"


def _serialize_final_course(
    course: Any,
    match_row: Any | None = None,
    uc_info: dict | None = None,
) -> dict:
    # UC mapping can be passed explicitly or attached to the row as `_uc_info`
    # by _final_rows_for_student (so every caller gets mapping with no extra work).
    _uc = uc_info if uc_info is not None else getattr(course, "_uc_info", None)
    course_id = _get_attr(course, "crs_id", "course_id")
    course_name = _get_attr(course, "crs_description", "course_name", "name")
    grade = _get_attr(course, "crs_letter_grade", "letter_grade", "grade")

    credits_attempted = _to_float(
        _get_attr(
            course,
            "crs_credit_attempted",
            "credit_attempted",
            "credits_attempted",
        )
    )
    credits_completed = _to_float(
        _get_attr(
            course,
            "crs_credit_completed",
            "credit_completed",
            "credits_completed",
        )
    )

    credits = (
        credits_completed
        if credits_completed is not None
        else credits_attempted
    )

    field_decisions = _field_decisions_from_final_row(course)
    gemini_fields = _gemini_corrected_fields(field_decisions)

    final_needs_review = bool(getattr(course, "needs_review", False))
    review_status = _get_attr(course, "review_status")

    final_source = _normalize_final_source(_get_attr(course, "final_source") or "merged")
    display_source = _display_source_from_final_source(final_source)

    match_id = getattr(match_row, "id", None) if match_row is not None else None

    match_confidence = None
    match_type = None
    match_reason = None
    match_needs_review = False
    match_reviewed_by_user = False

    field_differences: dict[str, Any] = {}

    course_id_match = None
    course_name_match = None
    letter_grade_match = None
    grade_level_match = None
    year_match = None
    credit_attempted_match = None
    credit_completed_match = None

    selected_course_id_source = None
    selected_course_name_source = None
    selected_letter_grade_source = None
    selected_grade_level_source = None
    selected_year_source = None
    selected_credit_attempted_source = None
    selected_credit_completed_source = None

    if match_row is not None:
        match_confidence = _to_float(
            _get_attr(
                match_row,
                "match_confidence",
                "overall_match_score",
                "course_name_score",
                "course_id_score",
            )
        )
        match_type = _get_attr(match_row, "match_type")
        match_reason = _get_attr(
            match_row,
            "review_reason",
            "resolution_reason",
        )

        match_needs_review = bool(getattr(match_row, "needs_review", False))
        match_reviewed_by_user = bool(getattr(match_row, "reviewed_by_user", False))

        field_differences = _safe_json_dict(_get_attr(match_row, "field_differences"))

        course_id_match = _get_attr(match_row, "course_id_match")
        course_name_match = _get_attr(match_row, "course_name_match")
        letter_grade_match = _get_attr(match_row, "letter_grade_match")
        grade_level_match = _get_attr(match_row, "grade_level_match")
        year_match = _get_attr(match_row, "year_match")
        credit_attempted_match = _get_attr(match_row, "credit_attempted_match")
        credit_completed_match = _get_attr(match_row, "credit_completed_match")

        selected_course_id_source = _get_attr(match_row, "selected_course_id_source")
        selected_course_name_source = _get_attr(match_row, "selected_course_name_source")
        selected_letter_grade_source = _get_attr(match_row, "selected_letter_grade_source")
        selected_grade_level_source = _get_attr(match_row, "selected_grade_level_source")
        selected_year_source = _get_attr(match_row, "selected_year_source")
        selected_credit_attempted_source = _get_attr(
            match_row,
            "selected_credit_attempted_source",
        )
        selected_credit_completed_source = _get_attr(
            match_row,
            "selected_credit_completed_source",
        )

    open_match_review = bool(match_needs_review and not match_reviewed_by_user)
    needs_review = bool(final_needs_review or open_match_review)

    if needs_review:
        review_status = "needs_review"
    else:
        review_status = _normalize_review_status(review_status)

    review_reason = _get_attr(course, "review_reason") or match_reason

    return {
        "id": getattr(course, "id", None),
        "final_course_id": getattr(course, "id", None),
        "final_course_detail_id": getattr(course, "id", None),

        "source_file": _get_attr(course, "source_file", "extraction_file_id"),

        "source": display_source,
        "source_label": display_source,
        "final_source": final_source,
        "extraction_source": display_source,

        "crs_id": course_id,
        "course_id": course_id,

        "name": course_name,
        "course_name": course_name,
        "crs_description": course_name,

        "grade": grade,
        "letter_grade": grade,
        "crs_letter_grade": grade,

        "credits": credits,
        "credits_attempted": credits_attempted,
        "credits_completed": credits_completed,
        "credit_attempted": credits_attempted,
        "credit_completed": credits_completed,

        "year": _to_int(_get_attr(course, "crs_year", "year")),
        "month": _to_int(_get_attr(course, "crs_month", "month")),
        "grade_level": _to_int(_get_attr(course, "crs_grade", "grade_level")),
        "school": _get_attr(course, "crs_hs", "school", "school_name"),

        "course_type": _get_course_type(course_id),
        "course_category": _get_course_category(course_id),

        "mapping_status": (_uc or {}).get("mapping_status") or _get_attr(course, "mapping_status"),
        "uc_doorway_course_id": (_uc or {}).get("uc_doorway_course_id"),
        "mapped_uc_course": (_uc or {}).get("mapped_uc_course"),

        "needs_review": needs_review,
        "review_status": review_status,
        "review_reason": review_reason,
        "resolution_reason": _get_attr(course, "resolution_reason"),

        "field_decisions": field_decisions,
        "field_sources": field_decisions,
        "field_differences": field_differences,

        # document_ai_snapshot / gemini_snapshot were ~half the payload and are
        # not read anywhere in the frontend — omitted to keep the dialog light.

        "changed_by_gemini": bool(gemini_fields),
        "gemini_corrected_fields": gemini_fields,
        "gemini_fields_used": gemini_fields,

        "document_ai_course_detail_id": _get_attr(
            course,
            "document_ai_course_detail_id",
            "doc_ai_course_detail_id",
            "document_ai_course_id",
        ),
        "gemini_course_detail_id": _get_attr(
            course,
            "gemini_course_detail_id",
            "gemini_course_id",
        ),

        "course_extraction_match_id": match_id,
        "match_id": match_id,
        "reconciliation_match_id": match_id,

        "match_type": match_type,
        "match_status": match_type,
        "match_confidence": match_confidence,
        "match_score": match_confidence,

        "course_id_match": course_id_match,
        "course_id_mismatch": bool(course_id_match is False or str(course_id_match).lower() == "false"),
        "course_name_match": course_name_match,
        "letter_grade_match": letter_grade_match,
        "grade_level_match": grade_level_match,
        "year_match": year_match,
        "credit_attempted_match": credit_attempted_match,
        "credit_completed_match": credit_completed_match,

        "selected_course_id_source": selected_course_id_source,
        "selected_course_name_source": selected_course_name_source,
        "selected_letter_grade_source": selected_letter_grade_source,
        "selected_grade_level_source": selected_grade_level_source,
        "selected_year_source": selected_year_source,
        "selected_credit_attempted_source": selected_credit_attempted_source,
        "selected_credit_completed_source": selected_credit_completed_source,
    }

def _serialize_match(row: Any) -> dict:
    match_confidence = _to_float(
        _get_attr(
            row,
            "match_confidence",
            "overall_match_score",
            "course_name_score",
            "course_id_score",
        )
    )

    field_decisions = _safe_json_dict(_get_attr(row, "field_decisions"))
    field_differences = _safe_json_dict(_get_attr(row, "field_differences"))

    return {
        "id": getattr(row, "id", None),
        "match_id": getattr(row, "id", None),
        "course_extraction_match_id": getattr(row, "id", None),

        "extraction_file_id": _get_attr(row, "extraction_file_id", "source_file"),
        "source_file": _get_attr(row, "source_file", "extraction_file_id"),

        "student_id": _get_attr(row, "student_id", "s_id"),
        "s_id": _get_attr(row, "s_id", "student_id"),

        "document_ai_course_detail_id": _get_attr(
            row,
            "document_ai_course_detail_id",
            "doc_ai_course_detail_id",
            "document_ai_course_id",
        ),
        "gemini_course_detail_id": _get_attr(
            row,
            "gemini_course_detail_id",
            "gemini_course_id",
        ),
        "final_course_detail_id": _get_attr(
            row,
            "final_course_detail_id",
            "applied_final_course_detail_id",
        ),

        "match_type": _get_attr(row, "match_type"),
        "match_confidence": match_confidence,
        "match_score": match_confidence,
        "overall_match_score": _to_float(_get_attr(row, "overall_match_score")),

        "course_id_match": _get_attr(row, "course_id_match"),
        "course_name_match": _get_attr(row, "course_name_match"),
        "letter_grade_match": _get_attr(row, "letter_grade_match"),
        "grade_level_match": _get_attr(row, "grade_level_match"),
        "month_match": _get_attr(row, "month_match"),
        "year_match": _get_attr(row, "year_match"),
        "credit_attempted_match": _get_attr(row, "credit_attempted_match"),
        "credit_completed_match": _get_attr(row, "credit_completed_match"),

        "course_name_score": _to_float(_get_attr(row, "course_name_score")),
        "course_id_score": _to_float(_get_attr(row, "course_id_score")),

        "needs_review": bool(getattr(row, "needs_review", False)),
        "review_reason": _get_attr(row, "review_reason"),
        "resolution_reason": _get_attr(row, "resolution_reason"),

        "reviewed_by_user": bool(getattr(row, "reviewed_by_user", False)),
        "reviewed_at": _get_attr(row, "reviewed_at"),

        "field_decisions": field_decisions,
        "field_sources": field_decisions,
        "field_differences": field_differences,

        "document_ai_snapshot": _safe_json_dict(_get_attr(row, "document_ai_snapshot")),
        "gemini_snapshot": _safe_json_dict(_get_attr(row, "gemini_snapshot")),

        "selected_course_id_source": _get_attr(row, "selected_course_id_source"),
        "selected_course_name_source": _get_attr(row, "selected_course_name_source"),
        "selected_letter_grade_source": _get_attr(row, "selected_letter_grade_source"),
        "selected_grade_level_source": _get_attr(row, "selected_grade_level_source"),
        "selected_month_source": _get_attr(row, "selected_month_source"),
        "selected_year_source": _get_attr(row, "selected_year_source"),
        "selected_credit_attempted_source": _get_attr(
            row,
            "selected_credit_attempted_source",
        ),
        "selected_credit_completed_source": _get_attr(
            row,
            "selected_credit_completed_source",
        ),
    }

async def _count_rows_for_file(
    session: AsyncSession,
    model_cls: Any,
    file_id: int,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(model_cls)
        .where(_file_column(model_cls) == file_id)
    )

    return int(result.scalar_one() or 0)


async def _count_final_needs_review(
    session: AsyncSession,
    file_id: int,
) -> int:
    FinalCourseDetails = _final_course_model()

    if not _has_column(FinalCourseDetails, "needs_review"):
        return 0

    result = await session.execute(
        select(func.count())
        .select_from(FinalCourseDetails)
        .where(
            _file_column(FinalCourseDetails) == file_id,
            getattr(FinalCourseDetails, "needs_review").is_(True),
        )
    )

    return int(result.scalar_one() or 0)


async def _load_matches_for_file(
    session: AsyncSession,
    file_id: int,
) -> list[Any]:
    CourseExtractionMatches = _match_model()

    stmt = (
        select(CourseExtractionMatches)
        .where(_file_column(CourseExtractionMatches) == file_id)
        .order_by(CourseExtractionMatches.id.asc())
    )

    return (await session.execute(stmt)).scalars().all()


def _match_lookup_from_matches(matches: list[Any]) -> dict[int, Any]:
    """Build {final_course_detail_id: match_row} from already-loaded matches."""
    lookup: dict[int, Any] = {}
    for row in matches:
        final_course_id = _to_int(
            _get_attr(row, "final_course_detail_id", "applied_final_course_detail_id")
        )
        if final_course_id is not None:
            lookup[final_course_id] = row
    return lookup


async def _match_lookup_by_final_course_id(
    session: AsyncSession,
    file_id: int,
) -> dict[int, Any]:
    matches = await _load_matches_for_file(session, file_id)
    return _match_lookup_from_matches(matches)


async def _uc_mapping_lookup_by_final_course_id(
    session: AsyncSession,
    file_id: int,
) -> dict[int, dict]:
    """Return {final_course_detail_id: mapped_uc_course dict} for a file.

    Joins the UC doorway mapping (linked via final_course_details_id, with a
    fallback to the legacy course_details_id <-> document_ai_course_detail_id
    link) so the A-G / GPA / Standardization tabs can show the mapped UC course.
    """
    FinalCourseDetails = _final_course_model()

    stmt = (
        select(FinalCourseDetails.id, models.CourseDetailMappingUcDoorwayCourses, models.UCDoorwayCourses)
        .outerjoin(
            models.CourseDetailMappingUcDoorwayCourses,
            or_(
                models.CourseDetailMappingUcDoorwayCourses.final_course_details_id == FinalCourseDetails.id,
                models.CourseDetailMappingUcDoorwayCourses.course_details_id
                == FinalCourseDetails.document_ai_course_detail_id,
            ),
        )
        .outerjoin(
            models.UCDoorwayCourses,
            models.CourseDetailMappingUcDoorwayCourses.uc_doorway_courses_id == models.UCDoorwayCourses.id,
        )
        .where(_file_column(FinalCourseDetails) == file_id)
    )

    lookup: dict[int, dict] = {}
    for final_id, mapping, uc in (await session.execute(stmt)).all():
        if final_id in lookup and lookup[final_id].get("mapped_uc_course"):
            continue
        mapped_uc_course = None
        if uc is not None:
            mapped_uc_course = {
                "id": getattr(uc, "id", None),
                "crs_ag_category_letter": getattr(uc, "crs_ag_category_letter", None),
                "crs_ag_category_description": getattr(uc, "crs_ag_category_description", None),
                "crs_discipline": getattr(uc, "crs_discipline", None),
                "crs_environment": getattr(uc, "crs_environment", None),
                "crs_honors": getattr(uc, "crs_honors", None),
                "crs_local_codes": getattr(uc, "crs_local_codes", None),
                "crs_academic_year": getattr(uc, "crs_academic_year", None),
                "hs_id": getattr(uc, "hs_id", None),
                "crs_hs": getattr(uc, "crs_hs", None),
                "crs_transcript_abbrevs": getattr(uc, "crs_transcript_abbrevs", None),
                "standardizedCode": getattr(uc, "crs_ag_category_letter", None),
                "standardizedDescription": getattr(uc, "crs_ag_category_description", None),
            }
        lookup[final_id] = {
            "mapping_status": getattr(mapping, "mapping_status", None) if mapping else None,
            "uc_doorway_course_id": getattr(mapping, "uc_doorway_courses_id", None) if mapping else None,
            "mapped_uc_course": mapped_uc_course,
        }

    return lookup


def _match_is_removed(row: Any) -> bool:
    reason = _normalize_action(_get_attr(row, "resolution_reason", "review_reason"))
    reviewed = bool(getattr(row, "reviewed_by_user", False))
    final_course_id = _get_attr(row, "final_course_detail_id")

    return (
        reviewed
        and final_course_id in (None, "")
        and "remove" in reason
    )


# ---------------------------------------------------------------------------
# Batch loaders — fetch data for MANY files/students in one query each so the
# list endpoints (completed / needs-review / not-processed) avoid N+1.
# ---------------------------------------------------------------------------
async def _batch_count_by_file(
    session: AsyncSession,
    model_cls: Any,
    file_ids: list[int],
) -> dict[int, int]:
    if not file_ids:
        return {}
    col = _file_column(model_cls)
    result = await session.execute(
        select(col, func.count()).where(col.in_(file_ids)).group_by(col)
    )
    return {int(fid): int(n) for fid, n in result.all()}


async def _batch_final_needs_review_by_file(
    session: AsyncSession,
    file_ids: list[int],
) -> dict[int, int]:
    FinalCourseDetails = _final_course_model()
    if not file_ids or not _has_column(FinalCourseDetails, "needs_review"):
        return {}
    col = _file_column(FinalCourseDetails)
    result = await session.execute(
        select(col, func.count())
        .where(col.in_(file_ids), getattr(FinalCourseDetails, "needs_review").is_(True))
        .group_by(col)
    )
    return {int(fid): int(n) for fid, n in result.all()}


async def _batch_matches_by_file(
    session: AsyncSession,
    file_ids: list[int],
) -> dict[int, list[Any]]:
    if not file_ids:
        return {}
    CourseExtractionMatches = _match_model()
    col = _file_column(CourseExtractionMatches)
    rows = (await session.execute(
        select(CourseExtractionMatches)
        .where(col.in_(file_ids))
        .order_by(CourseExtractionMatches.id.asc())
        .options(noload("*"))  # columns only — don't eager-load the relationship graph
    )).scalars().all()
    out: dict[int, list[Any]] = {}
    for r in rows:
        fid = _to_int(getattr(r, col.key, None))
        if fid is not None:
            out.setdefault(fid, []).append(r)
    return out


async def _batch_final_rows_by_file(
    session: AsyncSession,
    file_ids: list[int],
    with_uc: bool = True,
) -> dict[int, list[Any]]:
    """All final rows for the given files, grouped by file_id.

    One query for the rows. When `with_uc` is True a second query attaches the
    UC-doorway mapping (`_uc_info`) needed to serialize courses. The slim list
    endpoints pass `with_uc=False`: they only need rows for the completeness
    check + GPA recompute, so the 3-table UC join (the dominant cost across
    every course of every student) is skipped entirely."""
    if not file_ids:
        return {}
    FinalCourseDetails = _final_course_model()
    file_col = _file_column(FinalCourseDetails)

    order_columns = [
        getattr(FinalCourseDetails, c)
        for c in ("crs_year", "crs_grade", "crs_month", "id")
        if _has_column(FinalCourseDetails, c)
    ] or [FinalCourseDetails.id]

    rows = (await session.execute(
        select(FinalCourseDetails)
        .where(file_col.in_(file_ids))
        .order_by(*order_columns)
        .options(noload("*"))  # columns only — UC info is attached explicitly below
    )).scalars().all()

    # One UC-mapping query covering every final row across all files.
    uc_by_final: dict[int, dict] = {}
    final_ids = [getattr(r, "id", None) for r in rows if getattr(r, "id", None) is not None]
    if with_uc and final_ids:
        stmt = (
            select(FinalCourseDetails.id, models.CourseDetailMappingUcDoorwayCourses, models.UCDoorwayCourses)
            .outerjoin(
                models.CourseDetailMappingUcDoorwayCourses,
                or_(
                    models.CourseDetailMappingUcDoorwayCourses.final_course_details_id == FinalCourseDetails.id,
                    models.CourseDetailMappingUcDoorwayCourses.course_details_id
                    == FinalCourseDetails.document_ai_course_detail_id,
                ),
            )
            .outerjoin(
                models.UCDoorwayCourses,
                models.CourseDetailMappingUcDoorwayCourses.uc_doorway_courses_id == models.UCDoorwayCourses.id,
            )
            .where(FinalCourseDetails.id.in_(final_ids))
        )
        for final_id, mapping, uc in (await session.execute(stmt)).all():
            if final_id in uc_by_final and uc_by_final[final_id].get("mapped_uc_course"):
                continue
            mapped_uc_course = None
            if uc is not None:
                mapped_uc_course = {
                    "id": getattr(uc, "id", None),
                    "crs_ag_category_letter": getattr(uc, "crs_ag_category_letter", None),
                    "crs_ag_category_description": getattr(uc, "crs_ag_category_description", None),
                    "crs_discipline": getattr(uc, "crs_discipline", None),
                    "crs_environment": getattr(uc, "crs_environment", None),
                    "crs_honors": getattr(uc, "crs_honors", None),
                    "crs_local_codes": getattr(uc, "crs_local_codes", None),
                    "crs_academic_year": getattr(uc, "crs_academic_year", None),
                    "hs_id": getattr(uc, "hs_id", None),
                    "crs_hs": getattr(uc, "crs_hs", None),
                    "crs_transcript_abbrevs": getattr(uc, "crs_transcript_abbrevs", None),
                    "standardizedCode": getattr(uc, "crs_ag_category_letter", None),
                    "standardizedDescription": getattr(uc, "crs_ag_category_description", None),
                }
            uc_by_final[final_id] = {
                "mapping_status": getattr(mapping, "mapping_status", None) if mapping else None,
                "uc_doorway_course_id": getattr(mapping, "uc_doorway_courses_id", None) if mapping else None,
                "mapped_uc_course": mapped_uc_course,
            }

    out: dict[int, list[Any]] = {}
    for r in rows:
        r._uc_info = uc_by_final.get(getattr(r, "id", None))
        fid = _to_int(getattr(r, file_col.key, None))
        if fid is not None:
            out.setdefault(fid, []).append(r)
    return out


async def _prefetch_reconciliation(
    session: AsyncSession,
    file_ids: list[int],
    with_uc: bool = True,
) -> tuple[dict[int, dict], dict[int, list[Any]], dict[int, list[Any]]]:
    """Batch everything the list endpoints need, keyed by file_id:
    (reconciliation prefetch per file, matches per file, final rows per file).

    `with_uc=False` skips the UC-doorway join on the final rows — the slim list
    endpoints don't serialize courses, so they don't need it."""
    GeminiCourseDetails = _gemini_course_model()
    FinalCourseDetails = _final_course_model()

    doc_counts = await _batch_count_by_file(session, models.Course_details, file_ids)
    gem_counts = await _batch_count_by_file(session, GeminiCourseDetails, file_ids)
    fin_counts = await _batch_count_by_file(session, FinalCourseDetails, file_ids)
    nr_counts = await _batch_final_needs_review_by_file(session, file_ids)
    matches_by_file = await _batch_matches_by_file(session, file_ids)
    final_rows_by_file = await _batch_final_rows_by_file(session, file_ids, with_uc=with_uc)

    prefetch_by_file: dict[int, dict] = {}
    for fid in file_ids:
        prefetch_by_file[fid] = {
            "document_ai_count": doc_counts.get(fid, 0),
            "gemini_count": gem_counts.get(fid, 0),
            "final_count": fin_counts.get(fid, 0),
            "final_needs_review_count": nr_counts.get(fid, 0),
            "matches": matches_by_file.get(fid, []),
        }
    return prefetch_by_file, matches_by_file, final_rows_by_file


async def _build_reconciliation_summary(
    session: AsyncSession,
    file_id: int,
    prefetch: dict | None = None,
) -> dict:
    """Build a reconciliation summary for one file.

    Pass `prefetch` (with document_ai_count / gemini_count / final_count /
    final_needs_review_count / matches already loaded in batch) to avoid the
    5 per-file queries — used by the list endpoints to eliminate N+1.
    """
    if prefetch is not None:
        document_ai_count = prefetch.get("document_ai_count", 0)
        gemini_count = prefetch.get("gemini_count", 0)
        final_count = prefetch.get("final_count", 0)
        final_needs_review_count = prefetch.get("final_needs_review_count", 0)
        matches = prefetch.get("matches", [])
    else:
        GeminiCourseDetails = _gemini_course_model()
        FinalCourseDetails = _final_course_model()

        document_ai_count = await _count_rows_for_file(
            session,
            models.Course_details,
            file_id,
        )
        gemini_count = await _count_rows_for_file(
            session,
            GeminiCourseDetails,
            file_id,
        )
        final_count = await _count_rows_for_file(
            session,
            FinalCourseDetails,
            file_id,
        )
        final_needs_review_count = await _count_final_needs_review(session, file_id)

        matches = await _load_matches_for_file(session, file_id)

    match_counts: dict[str, int] = {}
    auto_fixed_count = 0
    removed_count = 0
    unresolved_match_count = 0
    course_id_mismatch_count = 0
    field_difference_count = 0

    for row in matches:
        match_type = str(_get_attr(row, "match_type") or "unknown")
        match_counts[match_type] = match_counts.get(match_type, 0) + 1

        if _match_is_removed(row):
            removed_count += 1

        reviewed_by_user = bool(getattr(row, "reviewed_by_user", False))
        match_needs_review = bool(getattr(row, "needs_review", False))

        if match_needs_review and not reviewed_by_user:
            unresolved_match_count += 1

        field_decisions = _safe_json_dict(_get_attr(row, "field_decisions"))
        field_differences = _safe_json_dict(_get_attr(row, "field_differences"))

        if field_differences:
            field_difference_count += 1

        course_id_diff = (
            field_differences.get("course_id")
            or field_differences.get("crs_id")
            or field_differences.get("course_number")
        )

        course_id_match = _get_attr(row, "course_id_match")

        if (
            not reviewed_by_user
            and (
                course_id_match is False
                or str(course_id_match).lower() == "false"
                or course_id_diff is not None
            )
        ):
            course_id_mismatch_count += 1

        selected_sources = [
            _get_attr(row, "selected_course_id_source"),
            _get_attr(row, "selected_course_name_source"),
            _get_attr(row, "selected_letter_grade_source"),
            _get_attr(row, "selected_grade_level_source"),
            _get_attr(row, "selected_month_source"),
            _get_attr(row, "selected_year_source"),
            _get_attr(row, "selected_credit_attempted_source"),
            _get_attr(row, "selected_credit_completed_source"),
        ]

        row_auto_fixed = any(
            "gemini" in str(value).lower()
            for value in field_decisions.values()
        ) or any(
            "gemini" in str(value).lower()
            for value in selected_sources
            if value not in (None, "")
        )

        if row_auto_fixed:
            auto_fixed_count += 1

    raw_max_source_count = max(document_ai_count, gemini_count)

    # Important:
    # If raw extractors saw more visual rows than final_course_details keeps,
    # the file should remain Needs Review. This catches real duplicate rows
    # accidentally suppressed during reconciliation.
    expected_final_count = max(raw_max_source_count - removed_count, 0)
    potential_missing_course_count = max(expected_final_count - final_count, 0)
    final_count_shortfall = bool(potential_missing_course_count > 0)

    course_count_difference = final_count - expected_final_count
    raw_count_difference_from_max = final_count - raw_max_source_count
    counts_match = document_ai_count == gemini_count

    review_reasons = []
    warnings = []

    if final_count_shortfall:
        review_reasons.append(
            f"Final rows are short by {potential_missing_course_count} course row(s): "
            f"raw max source rows={raw_max_source_count}, removed rows={removed_count}, "
            f"final_course_details rows={final_count}."
        )

    if final_needs_review_count > 0:
        review_reasons.append(
            f"{final_needs_review_count} final course row(s) need manual review."
        )

    if unresolved_match_count > 0:
        review_reasons.append(
            f"{unresolved_match_count} reconciliation match row(s) still need review."
        )

    if course_id_mismatch_count > 0:
        review_reasons.append(
            f"{course_id_mismatch_count} unresolved course ID mismatch row(s) need review."
        )

    if gemini_count == 0 and document_ai_count > 0:
        warnings.append(
            "Gemini raw extraction returned zero rows while Document AI had course rows."
        )

    if document_ai_count == 0 and gemini_count > 0:
        warnings.append(
            "Document AI raw extraction returned zero rows while Gemini had course rows."
        )

    if document_ai_count != gemini_count:
        warnings.append(
            f"Raw extractor row counts differ: Document AI={document_ai_count}, "
            f"Gemini={gemini_count}. Completion is based on final rows and review flags."
        )

    blocking_review_count = (
        final_needs_review_count
        + unresolved_match_count
        + course_id_mismatch_count
        + (1 if final_count_shortfall else 0)
    )

    return {
        "status": "needs_review" if blocking_review_count > 0 else "validated",
        "validation_type": "course_reconciliation",

        "document_ai_course_count": document_ai_count,
        "raw_document_ai_course_count": document_ai_count,
        "course_details_count": document_ai_count,

        "gemini_course_count": gemini_count,
        "raw_gemini_course_count": gemini_count,
        "gemini_course_details_count": gemini_count,

        "final_course_count": final_count,
        "actual_final_course_count": final_count,
        "final_course_details_count": final_count,

        "raw_max_source_course_count": raw_max_source_count,
        "raw_expected_final_course_count": raw_max_source_count,
        "expected_final_course_count": expected_final_count,

        "removed_course_count": removed_count,
        "potential_missing_course_count": potential_missing_course_count,
        "course_count_difference": course_count_difference,
        "raw_count_difference_from_max": raw_count_difference_from_max,
        "final_count_shortfall": final_count_shortfall,
        "counts_match": counts_match,

        "needs_review_count": final_needs_review_count,
        "final_needs_review_count": final_needs_review_count,
        "unresolved_match_count": unresolved_match_count,
        "course_id_mismatch_count": course_id_mismatch_count,
        "field_difference_count": field_difference_count,
        "open_review_count": blocking_review_count,

        "matched_count": match_counts.get("matched", 0),
        "document_ai_only_count": match_counts.get("document_ai_only", 0),
        "gemini_only_count": match_counts.get("gemini_only", 0),
        "match_counts": match_counts,
        "auto_fixed_count": auto_fixed_count,

        "review_reason_text": "; ".join(review_reasons) or None,
        "review_reasons": review_reasons,
        "warnings": warnings,

        "course_math_explanation": (
            f"Document AI raw rows: {document_ai_count}; "
            f"Gemini raw rows: {gemini_count}; "
            f"Final displayed rows: {final_count}; "
            f"Removed rows: {removed_count}; "
            f"Expected final rows after removals: {expected_final_count}; "
            f"Potential missing rows: {potential_missing_course_count}; "
            f"Open final row reviews: {final_needs_review_count}; "
            f"Open match reviews: {unresolved_match_count}; "
            f"Open course ID mismatches: {course_id_mismatch_count}. "
            "Completion is blocked by unresolved final rows, unresolved match rows, "
            "unresolved course ID mismatches, or final-count shortfalls."
        ),
    }

async def _final_rows_for_student(
    session: AsyncSession,
    *,
    student_db_id: int,
    file_id: int | None = None,
) -> list[Any]:
    FinalCourseDetails = _final_course_model()
    student_col = _student_column(FinalCourseDetails)

    conditions = []

    if student_col is not None:
        conditions.append(student_col == student_db_id)

    if file_id is not None:
        conditions.append(_file_column(FinalCourseDetails) == file_id)

    stmt = select(FinalCourseDetails)

    if conditions:
        stmt = stmt.where(*conditions)

    order_columns = []

    for column_name in (
        "crs_year",
        "crs_grade",
        "crs_month",
        "id",
    ):
        if _has_column(FinalCourseDetails, column_name):
            order_columns.append(getattr(FinalCourseDetails, column_name))

    if not order_columns:
        order_columns.append(FinalCourseDetails.id)

    stmt = stmt.order_by(*order_columns)

    rows = (await session.execute(stmt)).scalars().all()

    # Attach UC doorway mapping to each final row so the A-G / GPA /
    # Standardization tabs show the mapped course. One batch query per file.
    if rows and file_id is not None:
        try:
            uc_lookup = await _uc_mapping_lookup_by_final_course_id(session, file_id)
            for row in rows:
                row._uc_info = uc_lookup.get(getattr(row, "id", None))
        except Exception as exc:  # noqa: BLE001
            print(f"[UC_MAPPING] attach lookup failed for file {file_id}: {exc}", flush=True)

    return rows


async def _classifier_names_for(session, source_files) -> dict[int, str]:
    """Map classifier_type id → classifier_name for the given files (one query).
    Used to label a transcript's FORMAT by the extractor that actually handled
    it, instead of the school name."""
    ids = {
        int(getattr(sf, "classifier_type", None))
        for sf in source_files
        if sf is not None and getattr(sf, "classifier_type", None)
    }
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(models.ClassifiersType.id, models.ClassifiersType.classifier_name)
            .where(models.ClassifiersType.id.in_(ids))
        )
    ).all()
    return {int(cid): name for cid, name in rows}


def _format_label(source_file, names_by_id: dict[int, str] | None = None) -> str | None:
    """A transcript's FORMAT = the extractor/classifier that handled it (LBUSD,
    Mayfair, St. Anthony, a trained type…), NOT its high school. Prefer the stored
    classifier_type; fall back to the filename detection the backend routes on.
    The frontend collapses this to a display label and, when there's no extractor
    ("others"), shows the school name instead."""
    if source_file is None:
        return None
    names_by_id = names_by_id or {}
    ctype = getattr(source_file, "classifier_type", None)
    if ctype and int(ctype) in names_by_id:
        return names_by_id[int(ctype)]
    from app.routers.cloud_folder_locations import _detect_classifier_name

    return _detect_classifier_name(getattr(source_file, "file_name", "") or "")


def _serialize_student(
    student: models.Students,
    final_courses: list[Any],
    source_file=None,
    reconciliation_summary: dict | None = None,
    match_lookup: dict[int, Any] | None = None,
    uc_lookup: dict[int, dict] | None = None,
    include_courses: bool = True,
    format_label: str | None = None,
) -> dict:
    reconciliation_summary = reconciliation_summary or {}
    match_lookup = match_lookup or {}
    uc_lookup = uc_lookup or {}

    processed_at = None

    if source_file is not None:
        processed_at = getattr(source_file, "processed_date", None) or getattr(
            source_file,
            "upload_date",
            None,
        )

    file_status = _get_file_status(source_file)

    # Serializing every course is the bulk of the payload + server time. List
    # endpoints pass include_courses=False (the row only needs the count + GPA)
    # and the detail dialog fetches the full courses on open via
    # GET /extractor/students/{id}/courses.
    if include_courses:
        serialized_courses = [
            _serialize_final_course(
                course,
                match_lookup.get(getattr(course, "id", None)),
                uc_lookup.get(getattr(course, "id", None)),
            )
            for course in final_courses
        ]
        recalculated_gpa = _recalculate_gpa(serialized_courses)
    else:
        serialized_courses = None
        recalculated_gpa = _recalculate_gpa_from_raw(final_courses)

    student_complete = _is_student_complete(student, final_courses, source_file)

    return {
        "id": (
            student.s_id
            if getattr(student, "s_id", None) is not None
            else student.id
        ),
        "student_id": student.s_id,
        "db_id": student.id,
        "student_name": student.s_name,
        "file_name": getattr(source_file, "file_name", None) if source_file else None,
        "email": None,
        # FORMAT is the extractor/classifier that handled the file (LBUSD/Mayfair/
        # St. Anthony/…); the SCHOOL is the actual high school. They are different.
        "format": format_label if format_label is not None else student.hs_name,
        "school_name": student.hs_name,
        "birth_date": student.s_date_of_birth,
        "graduation_date": student.hs_graduation_date,
        "address": student.s_address,
        "gpa": (
            student.hs_total_gpa_course
            or student.hs_aca_gpa_course
            or student.hs_university_gpa
        ),
        "recalculated_gpa": recalculated_gpa,
        "marks": None,
        "source_file": student.source_file,
        "file_status": file_status,
        "process_status": file_status,
        "effective_status": file_status,
        "student_data_complete": student_complete,
        "processed_at": processed_at,

        # `courses` is null in the slim (list) response; the detail dialog fetches
        # the full courses on open. `course_count` always reflects the real count.
        "courses": serialized_courses,
        "course_count": len(final_courses),

        "validation_result": reconciliation_summary,
        "course_validation": reconciliation_summary,
        "course_reconciliation": reconciliation_summary,
        "reconciliation_summary": reconciliation_summary,
        "validation_status": reconciliation_summary.get("status") or file_status,
        "validation_result_id": None,
        "validation_type": "course_reconciliation",
        "model": reconciliation_summary.get("model"),

        "document_ai_course_count": reconciliation_summary.get(
            "document_ai_course_count"
        ),
        "raw_document_ai_course_count": reconciliation_summary.get(
            "raw_document_ai_course_count"
        ),
        "gemini_course_count": reconciliation_summary.get("gemini_course_count"),
        "raw_gemini_course_count": reconciliation_summary.get(
            "raw_gemini_course_count"
        ),
        "final_course_count": reconciliation_summary.get("final_course_count"),
        "final_course_details_count": reconciliation_summary.get(
            "final_course_details_count"
        ),
        "counts_match": reconciliation_summary.get("counts_match"),
        "matched_course_count": reconciliation_summary.get("matched_count"),
        "missing_from_document_ai_count": reconciliation_summary.get(
            "gemini_only_count"
        ),
        "extra_in_document_ai_count": reconciliation_summary.get(
            "document_ai_only_count"
        ),
        "needs_review_count": reconciliation_summary.get("needs_review_count"),
        "open_review_count": reconciliation_summary.get("open_review_count"),
        "unresolved_match_count": reconciliation_summary.get("unresolved_match_count"),
        "course_id_mismatch_count": reconciliation_summary.get("course_id_mismatch_count"),
        "potential_missing_course_count": reconciliation_summary.get("potential_missing_course_count"),
        "auto_fixed_count": reconciliation_summary.get("auto_fixed_count"),
        "review_reason_text": reconciliation_summary.get("review_reason_text"),
        "review_reasons": reconciliation_summary.get("review_reasons") or [],
        "warnings": reconciliation_summary.get("warnings") or [],

        "missing_from_extraction": [],
        "extra_in_extraction": [],
        "suggested_courses_to_add": [],
        "suggested_courses_to_remove": [],
        "missing_course_details": [],
        "extra_course_details": [],
        "auto_add_candidates": [],
        "auto_applied_courses": [],
        "matched_courses": [],
        "gemini_course_items": [],
        "validation_matches": [],

        **reconciliation_summary,
    }


_NEW_TRANSCRIPT_PLACEHOLDERS = {
    "unknown",
    "unknown student",
    "student unknown",
    "unknown school",
    "school unknown",
    "unknown course",
    "course unknown",
    "not available",
    "unavailable",
    "n/a",
    "na",
    "none",
    "-",
    "--",
}


def _is_real_new_transcript_text(value: Any) -> bool:
    text_value = str(value or "").strip()
    if not text_value:
        return False
    return text_value.casefold() not in _NEW_TRANSCRIPT_PLACEHOLDERS


def _new_course_missing_required_fields(course: Any) -> list[str]:
    """Return the human-facing fields still needed before a row can be reviewed."""
    name = _get_attr(course, "crs_description", "course_name", "name")
    grade = _get_attr(course, "crs_letter_grade", "letter_grade", "grade")
    school = _get_attr(course, "crs_hs", "school", "school_name")
    grade_level = _get_attr(course, "crs_grade", "grade_level")
    year = _get_attr(course, "crs_year", "year")
    credits = _first_non_empty(
        _get_attr(
            course,
            "crs_credit_completed",
            "credit_completed",
            "credits_completed",
        ),
        _get_attr(
            course,
            "crs_credit_attempted",
            "credit_attempted",
            "credits_attempted",
        ),
    )

    missing: list[str] = []

    if not _is_real_new_transcript_text(name):
        missing.append("Course Name")
    if not _is_real_new_transcript_text(grade):
        missing.append("Grade")
    if not _is_real_new_transcript_text(school):
        missing.append("School")
    if grade_level is None:
        missing.append("Grade Yr")
    if year is None:
        missing.append("Year")
    if credits is None:
        missing.append("Credits")

    # New transcript layouts may legitimately have no Course ID or Month.
    return missing


def _new_course_has_required_fields(course: Any) -> bool:
    return not _new_course_missing_required_fields(course)


def _format_new_course_missing_fields(fields: list[str]) -> str:
    if not fields:
        return ""
    if len(fields) == 1:
        return fields[0]
    if len(fields) == 2:
        return f"{fields[0]} and {fields[1]}"
    return ", ".join(fields[:-1]) + f", and {fields[-1]}"


def _new_course_review_requested(payload: dict | None) -> bool:
    payload = payload or {}

    if "reviewed_by_user" in payload or "mark_reviewed" in payload:
        raw_reviewed = (
            payload.get("reviewed_by_user")
            if "reviewed_by_user" in payload
            else payload.get("mark_reviewed")
        )
        return _to_bool(raw_reviewed)

    return bool(
        _is_resolved_review_status(payload.get("review_status"))
        or _normalize_action(payload.get("resolution"))
        in {"accept_final", "reviewed", "keep"}
    )


def _is_new_transcript_student_complete(
    student: Any,
    courses: list[Any],
) -> bool:
    if not _is_real_new_transcript_text(_get_attr(student, "s_name")):
        return False

    if not _is_real_new_transcript_text(_get_attr(student, "hs_name")):
        return False

    if not courses:
        return False

    return all(_new_course_has_required_fields(course) for course in courses)


def _serialize_new_transcript_course(
    course: Any,
    *,
    file_status: str | None,
) -> dict:
    course_id = _get_attr(course, "crs_id", "course_id")
    course_name = _get_attr(course, "crs_description", "course_name", "name")
    grade = _get_attr(course, "crs_letter_grade", "letter_grade", "grade")

    credits_attempted = _to_float(
        _get_attr(
            course,
            "crs_credit_attempted",
            "credit_attempted",
            "credits_attempted",
        )
    )
    credits_completed = _to_float(
        _get_attr(
            course,
            "crs_credit_completed",
            "credit_completed",
            "credits_completed",
        )
    )
    credits = (
        credits_completed
        if credits_completed is not None
        else credits_attempted
    )

    encoded_id = _encode_new_record_id(getattr(course, "id", None))
    file_completed = str(file_status or "").lower().strip() == "completed"
    missing_required_fields = _new_course_missing_required_fields(course)
    course_complete = not missing_required_fields

    # An Audit row is only truly Reviewed when it is complete AND the user
    # explicitly reviewed it. Existing Completed files remain protected for
    # backward compatibility, but incomplete Audit rows are always shown as
    # needing review even if an older build stored reviewed_by_user=true.
    reviewed_by_user = bool(
        file_completed
        or (
            course_complete
            and getattr(course, "reviewed_by_user", False)
        )
    )
    needs_review = bool(not file_completed and not reviewed_by_user)
    review_block_reason = (
        None
        if course_complete
        else (
            "Add "
            + _format_new_course_missing_fields(missing_required_fields)
            + " before marking reviewed."
        )
    )

    return {
        "id": encoded_id,
        "final_course_id": encoded_id,
        "final_course_detail_id": encoded_id,
        "new_transcript_course_id": getattr(course, "id", None),

        "source_file": _get_attr(course, "source_file", "extraction_file_id"),
        "is_new_transcript_type": True,
        "storage_source": "new_transcript_course_details",

        "source": "Gemini",
        "source_label": "Gemini",
        "final_source": "gemini",
        "extraction_source": "Gemini",

        "crs_id": course_id,
        "course_id": course_id,

        "name": course_name,
        "course_name": course_name,
        "crs_description": course_name,

        "grade": grade,
        "letter_grade": grade,
        "crs_letter_grade": grade,

        "credits": credits,
        "credits_attempted": credits_attempted,
        "credits_completed": credits_completed,
        "credit_attempted": credits_attempted,
        "credit_completed": credits_completed,

        "year": _to_int(_get_attr(course, "crs_year", "year")),
        "month": _to_int(_get_attr(course, "crs_month", "month")),
        "grade_level": _to_int(_get_attr(course, "crs_grade", "grade_level")),
        "school": _get_attr(course, "crs_hs", "school", "school_name"),
        "term_gpa": _to_float(_get_attr(course, "crs_term_gpa", "term_gpa")),

        "course_type": _get_course_type(course_id),
        "course_category": _get_course_category(course_id),

        "mapping_status": None,
        "uc_doorway_course_id": None,
        "mapped_uc_course": None,

        "needs_review": needs_review,
        "reviewed_by_user": reviewed_by_user,
        "reviewed": reviewed_by_user,
        "mark_reviewed": reviewed_by_user,
        "missing_required_fields": missing_required_fields,
        "review_block_reason": review_block_reason,
        "review_status": (
            "reviewed"
            if reviewed_by_user
            else ("needs_review" if needs_review else "auto_resolved")
        ),
        "review_reason": (
            "Gemini-only new transcript awaiting human review"
            if needs_review
            else None
        ),
        "resolution_reason": (
            "Reviewed by user"
            if reviewed_by_user and not file_completed
            else None
        ),

        "field_decisions": {},
        "field_sources": {},
        "field_differences": {},

        "changed_by_gemini": True,
        "gemini_corrected_fields": [],
        "gemini_fields_used": [],

        "document_ai_course_detail_id": None,
        "gemini_course_detail_id": None,

        "course_extraction_match_id": None,
        "match_id": None,
        "reconciliation_match_id": None,
        "match_type": "gemini_only_new_transcript",
        "match_status": "gemini_only_new_transcript",
        "match_confidence": None,
        "match_score": None,

        "course_id_match": None,
        "course_id_mismatch": False,
        "course_name_match": None,
        "letter_grade_match": None,
        "grade_level_match": None,
        "year_match": None,
        "credit_attempted_match": None,
        "credit_completed_match": None,

        "selected_course_id_source": "gemini",
        "selected_course_name_source": "gemini",
        "selected_letter_grade_source": "gemini",
        "selected_grade_level_source": "gemini",
        "selected_year_source": "gemini",
        "selected_credit_attempted_source": "gemini",
        "selected_credit_completed_source": "gemini",
    }


def _build_new_transcript_summary_from_rows(
    *,
    source_file: Any,
    students: list[Any],
    courses: list[Any],
) -> dict:
    course_count = len(courses)
    incomplete_course_count = sum(
        1 for course in courses if not _new_course_has_required_fields(course)
    )

    file_status = str(_get_file_status(source_file) or "").lower().strip()
    file_completed = file_status == "completed"

    # Existing completed data predates the reviewed_by_user column. Preserve it
    # as completed instead of retroactively reopening those files. For Audit
    # rows, incomplete automatically means not reviewed.
    unreviewed_course_count = (
        0
        if file_completed
        else sum(
            1
            for course in courses
            if (
                not _new_course_has_required_fields(course)
                or not bool(getattr(course, "reviewed_by_user", False))
            )
        )
    )
    blocking_course_count = unreviewed_course_count

    student_complete = bool(students) and all(
        _is_new_transcript_student_complete(
            student,
            [
                course
                for course in courses
                if _to_int(_get_attr(course, "s_id", "student_id"))
                == _to_int(getattr(student, "id", None))
            ],
        )
        for student in students
    )

    pending_human_review = file_status in {
        "needs_review",
        "needs_review_audit",
    }
    audit_review = file_status == "needs_review_audit"

    blocking_review_count = blocking_course_count
    review_reasons: list[str] = []

    if not students:
        blocking_review_count += 1
        review_reasons.append("No extracted student row is available.")

    if course_count == 0:
        blocking_review_count += 1
        review_reasons.append("No extracted course rows are available.")

    if students and not student_complete:
        review_reasons.append(
            "Some transcript information still needs to be filled in before review can finish."
        )

    if incomplete_course_count > 0:
        review_reasons.append(
            f"{incomplete_course_count} course row(s) need more information before they can be reviewed."
        )

    if unreviewed_course_count > 0:
        review_reasons.append(
            f"{unreviewed_course_count} course row(s) still require human review."
        )

    # Once every row is explicitly reviewed, the file intentionally remains in
    # the Audit tab until the user clicks Move to Auto Complete. That pending file
    # state is informational, not an extra blocking course row.
    if pending_human_review and blocking_review_count == 0:
        review_reasons.append(
            "All course rows are reviewed. Use Move to Auto Complete when ready."
        )

    validated = bool(
        file_status == "completed"
        and students
        and course_count > 0
        and student_complete
        and incomplete_course_count == 0
        and unreviewed_course_count == 0
    )

    return {
        "status": "validated" if validated else "needs_review",
        "validation_type": "gemini_only_new_transcript",
        "is_new_transcript_type": True,
        "storage_source": "new_transcript_tables",
        "review_bucket": (
            "human_review_with_audit"
            if audit_review
            else (
                "human_review"
                if pending_human_review
                else "auto_complete"
            )
        ),

        "document_ai_course_count": 0,
        "raw_document_ai_course_count": 0,
        "course_details_count": 0,

        "gemini_course_count": course_count,
        "raw_gemini_course_count": course_count,
        "gemini_course_details_count": course_count,

        "final_course_count": course_count,
        "actual_final_course_count": course_count,
        "final_course_details_count": course_count,

        "raw_max_source_course_count": course_count,
        "raw_expected_final_course_count": course_count,
        "expected_final_course_count": course_count,

        "removed_course_count": 0,
        "potential_missing_course_count": 0,
        "course_count_difference": 0,
        "raw_count_difference_from_max": 0,
        "final_count_shortfall": False,
        "counts_match": True,

        "needs_review_count": blocking_review_count,
        "final_needs_review_count": blocking_review_count,
        "reviewed_course_count": max(course_count - unreviewed_course_count, 0),
        "unreviewed_course_count": unreviewed_course_count,
        "unresolved_match_count": 0,
        "course_id_mismatch_count": 0,
        "field_difference_count": 0,
        "open_review_count": blocking_review_count,

        "matched_count": 0,
        "document_ai_only_count": 0,
        "gemini_only_count": course_count,
        "match_counts": {"gemini_only_new_transcript": course_count},
        "auto_fixed_count": 0,
        "clean_count": max(course_count - incomplete_course_count, 0),

        "review_reason_text": "; ".join(review_reasons) or None,
        "review_reasons": review_reasons,
        "warnings": [],

        "course_math_explanation": (
            f"Gemini-only new transcript rows: {course_count}; "
            f"incomplete course rows: {incomplete_course_count}; "
            f"unreviewed course rows: {unreviewed_course_count}; "
            f"file status: {file_status or 'unknown'}. "
            "This isolated workflow does not use Document AI reconciliation."
        ),
    }


async def _new_transcript_rows_for_file(
    session: AsyncSession,
    file_id: int,
) -> tuple[list[Any], list[Any]]:
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    students = (
        await session.execute(
            select(NewTranscriptStudents)
            .where(NewTranscriptStudents.source_file == file_id)
            .order_by(NewTranscriptStudents.id.asc())
            .options(noload("*"))
        )
    ).scalars().all()

    courses = (
        await session.execute(
            select(NewTranscriptCourseDetails)
            .where(NewTranscriptCourseDetails.source_file == file_id)
            .order_by(
                NewTranscriptCourseDetails.crs_year.asc(),
                NewTranscriptCourseDetails.crs_grade.asc(),
                NewTranscriptCourseDetails.crs_month.asc(),
                NewTranscriptCourseDetails.id.asc(),
            )
            .options(noload("*"))
        )
    ).scalars().all()

    return students, courses


async def _new_transcript_courses_for_student(
    session: AsyncSession,
    *,
    student_db_id: int,
    file_id: int | None = None,
) -> list[Any]:
    NewTranscriptCourseDetails = _new_transcript_course_model()

    stmt = select(NewTranscriptCourseDetails).where(
        NewTranscriptCourseDetails.s_id == student_db_id
    )

    if file_id is not None:
        stmt = stmt.where(NewTranscriptCourseDetails.source_file == file_id)

    stmt = stmt.order_by(
        NewTranscriptCourseDetails.crs_year.asc(),
        NewTranscriptCourseDetails.crs_grade.asc(),
        NewTranscriptCourseDetails.crs_month.asc(),
        NewTranscriptCourseDetails.id.asc(),
    )

    return (await session.execute(stmt.options(noload("*")))).scalars().all()


async def _build_summary_for_file(
    session: AsyncSession,
    source_file: Any,
) -> dict:
    if await _is_new_transcript_file(session, int(source_file.id)):
        students, courses = await _new_transcript_rows_for_file(
            session,
            int(source_file.id),
        )
        return _build_new_transcript_summary_from_rows(
            source_file=source_file,
            students=students,
            courses=courses,
        )

    return await _build_reconciliation_summary(session, int(source_file.id))


def _serialize_new_transcript_student(
    student: Any,
    courses: list[Any],
    source_file: Any,
    summary: dict,
    *,
    include_courses: bool = True,
) -> dict:
    file_status = _get_file_status(source_file)

    if include_courses:
        serialized_courses = [
            _serialize_new_transcript_course(
                course,
                file_status=file_status,
            )
            for course in courses
        ]
        recalculated_gpa = _recalculate_gpa(serialized_courses)
    else:
        serialized_courses = None
        recalculated_gpa = _recalculate_gpa_from_raw(courses)

    encoded_db_id = _encode_new_record_id(getattr(student, "id", None))
    processed_at = (
        getattr(source_file, "processed_date", None)
        or getattr(source_file, "upload_date", None)
    )

    return {
        "id": encoded_db_id,
        "student_id": getattr(student, "s_id", None),
        "db_id": encoded_db_id,
        "new_transcript_student_id": getattr(student, "id", None),
        "student_name": _get_attr(student, "s_name"),
        "file_name": getattr(source_file, "file_name", None),
        "email": None,
        "format": _get_attr(student, "hs_name"),
        "school_name": _get_attr(student, "hs_name"),
        "birth_date": _get_attr(student, "s_date_of_birth"),
        "graduation_date": _get_attr(student, "hs_graduation_date"),
        "address": _get_attr(student, "s_address"),
        "gpa": _first_non_empty(
            _get_attr(student, "hs_total_gpa_course"),
            _get_attr(student, "hs_aca_gpa_course"),
            _get_attr(student, "hs_university_gpa"),
        ),
        "recalculated_gpa": recalculated_gpa,
        "marks": None,
        "source_file": _get_attr(student, "source_file"),
        "file_status": file_status,
        "process_status": file_status,
        "effective_status": file_status,
        "student_data_complete": _is_new_transcript_student_complete(
            student,
            courses,
        ),
        "processed_at": processed_at,

        "is_new_transcript_type": True,
        "storage_source": "new_transcript_tables",

        "courses": serialized_courses,
        "course_count": len(courses),

        "validation_result": summary,
        "course_validation": summary,
        "course_reconciliation": summary,
        "reconciliation_summary": summary,
        "validation_status": summary.get("status") or file_status,
        "validation_result_id": None,
        "validation_type": "gemini_only_new_transcript",
        "model": None,

        "document_ai_course_count": 0,
        "raw_document_ai_course_count": 0,
        "gemini_course_count": len(courses),
        "raw_gemini_course_count": len(courses),
        "final_course_count": len(courses),
        "final_course_details_count": len(courses),
        "counts_match": True,
        "matched_course_count": 0,
        "missing_from_document_ai_count": len(courses),
        "extra_in_document_ai_count": 0,
        "needs_review_count": summary.get("needs_review_count"),
        "open_review_count": summary.get("open_review_count"),
        "unresolved_match_count": 0,
        "course_id_mismatch_count": 0,
        "potential_missing_course_count": 0,
        "auto_fixed_count": 0,
        "review_reason_text": summary.get("review_reason_text"),
        "review_reasons": summary.get("review_reasons") or [],
        "warnings": summary.get("warnings") or [],

        "missing_from_extraction": [],
        "extra_in_extraction": [],
        "suggested_courses_to_add": [],
        "suggested_courses_to_remove": [],
        "missing_course_details": [],
        "extra_course_details": [],
        "auto_add_candidates": [],
        "auto_applied_courses": [],
        "matched_courses": [],
        "gemini_course_items": [],
        "validation_matches": [],

        **summary,
    }


def _new_course_values(
    *,
    student_db_id: int,
    file_id: int,
    payload: dict,
) -> dict:
    credits_completed = _to_float(
        _first_non_empty(
            payload.get("credits_completed"),
            payload.get("credit_completed"),
            payload.get("credits"),
        )
    )
    credits_attempted = _to_float(
        _first_non_empty(
            payload.get("credits_attempted"),
            payload.get("credit_attempted"),
            credits_completed,
        )
    )

    values: dict[str, Any] = {
        "s_id": student_db_id,
        "source_file": file_id,
        "crs_id": _first_non_empty(
            payload.get("crs_id"),
            payload.get("course_id"),
        ),
        "crs_description": _first_non_empty(
            payload.get("name"),
            payload.get("course_name"),
            payload.get("crs_description"),
        ),
        "crs_letter_grade": _first_non_empty(
            payload.get("grade"),
            payload.get("letter_grade"),
            payload.get("crs_letter_grade"),
        ),
        "crs_hs": _first_non_empty(
            payload.get("school"),
            payload.get("school_name"),
            payload.get("crs_hs"),
        ),
        "crs_grade": _to_int(
            _first_non_empty(
                payload.get("grade_level"),
                payload.get("crs_grade"),
            )
        ),
        "crs_month": _month_to_int(
            _first_non_empty(
                payload.get("month"),
                payload.get("crs_month"),
            )
        ),
        "crs_year": _year_to_int(
            _first_non_empty(
                payload.get("year"),
                payload.get("crs_year"),
            )
        ),
        "crs_credit_attempted": credits_attempted,
        "crs_credit_completed": credits_completed,
        "crs_term_gpa": _to_float(
            _first_non_empty(
                payload.get("term_gpa"),
                payload.get("crs_term_gpa"),
            )
        ),
    }

    # Preserve false as well as true. `_first_non_empty` intentionally skips
    # False, so review state must be handled explicitly.
    if "reviewed_by_user" in payload or "mark_reviewed" in payload:
        raw_reviewed = (
            payload.get("reviewed_by_user")
            if "reviewed_by_user" in payload
            else payload.get("mark_reviewed")
        )
        values["reviewed_by_user"] = _to_bool(raw_reviewed)
    elif (
        _is_resolved_review_status(payload.get("review_status"))
        or _normalize_action(payload.get("resolution")) in {
            "accept_final",
            "reviewed",
            "keep",
        }
    ):
        values["reviewed_by_user"] = True

    return values


async def _refresh_new_transcript_file_status(
    session: AsyncSession,
    file_id: int,
    *,
    allow_complete: bool = False,
    source_file: Any | None = None,
    students: list[Any] | None = None,
    courses: list[Any] | None = None,
) -> str:
    if source_file is None:
        source_file = (
            await session.execute(
                select(models.ExtractionFileDetails).where(
                    models.ExtractionFileDetails.id == file_id
                )
            )
        ).scalar_one_or_none()

    if source_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    if students is None or courses is None:
        students, courses = await _new_transcript_rows_for_file(session, file_id)

    all_complete = bool(students) and bool(courses)
    if all_complete:
        courses_by_student: dict[int, list[Any]] = {}
        for course in courses:
            sid = _to_int(_get_attr(course, "s_id", "student_id"))
            if sid is not None:
                courses_by_student.setdefault(sid, []).append(course)

        all_complete = all(
            _is_new_transcript_student_complete(
                student,
                courses_by_student.get(int(student.id), []),
            )
            for student in students
        )

    all_reviewed = bool(courses) and all(
        _new_course_has_required_fields(course)
        and bool(getattr(course, "reviewed_by_user", False))
        for course in courses
    )

    current_status = str(source_file.process_status or "").lower().strip()

    # Never reopen existing Completed files merely because reviewed_by_user was
    # added later with a default of false.
    if current_status == "completed":
        final_status = "completed"
    elif all_complete and all_reviewed and allow_complete:
        final_status = "completed"
    elif current_status == "needs_review_audit":
        # Save Review / Mark as reviewed keeps the transcript in Audit.
        # Only the explicit Move to Auto Complete action may complete it.
        final_status = "needs_review_audit"
    else:
        final_status = "needs_review"

    source_file.process_status = final_status
    source_file.processed_date = _now()
    await session.flush()
    return final_status


async def _create_new_transcript_student_for_file(
    *,
    session: AsyncSession,
    extraction_row: Any,
    payload: dict,
) -> dict:
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    existing_student_id = (
        await session.execute(
            select(NewTranscriptStudents.id)
            .where(
                NewTranscriptStudents.source_file == int(extraction_row.id)
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_student_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This new-transcript file already has a student record. "
                "Refresh the page and edit the existing record instead of "
                "creating a duplicate."
            ),
        )

    submitted_student_id = _parse_new_transcript_identifier(
        payload.get("student_id"),
        field_name="student_id",
    )
    student_id = (
        submitted_student_id
        if submitted_student_id is not None
        else int(extraction_row.id)
    )
    submitted_state_id = _parse_new_transcript_identifier(
        payload.get("state_id"),
        field_name="state_id",
    )

    student = NewTranscriptStudents(
        s_id=student_id,
        s_name=(
            payload.get("student_name")
            or payload.get("name")
            or "Unknown Student"
        ),
        hs_name=(
            payload.get("format")
            or payload.get("school")
            or payload.get("school_name")
            or "Unknown School"
        ),
        s_address=payload.get("address"),
        s_phone_number=payload.get("phone_number"),
        s_gender=payload.get("gender"),
        s_date_of_birth=_parse_iso_date(payload.get("birth_date")),
        s_state_id=submitted_state_id,
        hs_counselor_name=payload.get("counselor_name"),
        hs_grade=_to_int(payload.get("grade_level")),
        hs_total_units_earned=_to_float(payload.get("total_units_earned")),
        hs_total_gpa_course=_to_float(payload.get("gpa")),
        hs_aca_gpa_course=_to_float(payload.get("academic_gpa")),
        hs_university_gpa=_to_float(payload.get("university_gpa")),
        hs_enter_date=_parse_iso_date(payload.get("enter_date")),
        hs_graduation_date=_parse_iso_date(payload.get("graduation_date")),
        source_file=int(extraction_row.id),
    )
    session.add(student)
    await session.flush()

    for course_payload in payload.get("courses") or []:
        values = _new_course_values(
            student_db_id=int(student.id),
            file_id=int(extraction_row.id),
            payload=course_payload,
        )
        if not any(
            values.get(key) not in (None, "")
            for key in (
                "crs_id",
                "crs_description",
                "crs_letter_grade",
                "crs_credit_completed",
                "crs_credit_attempted",
            )
        ):
            continue
        new_course = NewTranscriptCourseDetails(**values)
        if not _new_course_has_required_fields(new_course) and hasattr(
            new_course, "reviewed_by_user"
        ):
            new_course.reviewed_by_user = False
        session.add(new_course)

    await session.flush()
    await _refresh_new_transcript_file_status(
        session,
        int(extraction_row.id),
        allow_complete=False,
    )
    await session.commit()
    await session.refresh(student)

    courses = await _new_transcript_courses_for_student(
        session,
        student_db_id=int(student.id),
        file_id=int(extraction_row.id),
    )
    summary = await _build_summary_for_file(session, extraction_row)

    return _serialize_new_transcript_student(
        student,
        courses,
        extraction_row,
        summary,
        include_courses=True,
    )


def _parse_iso_date(value: Any):
    from datetime import date as _date

    if value in (None, ""):
        return None
    if isinstance(value, _date):
        return value
    try:
        return _date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


async def _update_new_transcript_student_and_courses(
    *,
    session: AsyncSession,
    encoded_student_id: int,
    payload: dict,
    light: bool = False,
) -> dict:
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    student_db_id = _decode_new_record_id(encoded_student_id)
    if student_db_id is None:
        raise HTTPException(status_code=400, detail="Invalid new transcript student ID")

    student = (
        await session.execute(
            select(NewTranscriptStudents).where(
                NewTranscriptStudents.id == student_db_id
            )
        )
    ).scalar_one_or_none()

    if student is None:
        raise HTTPException(status_code=404, detail="New transcript student not found")

    submitted_student_id = (
        _parse_new_transcript_identifier(
            payload.get("student_id"),
            field_name="student_id",
        )
        if "student_id" in payload
        else None
    )
    submitted_state_id = (
        _parse_new_transcript_identifier(
            payload.get("state_id"),
            field_name="state_id",
        )
        if "state_id" in payload
        else None
    )

    updates = {
        "s_id": submitted_student_id,
        "s_name": _first_non_empty(
            payload.get("student_name"),
            payload.get("name"),
        ),
        "hs_name": _first_non_empty(
            payload.get("format"),
            payload.get("school"),
            payload.get("school_name"),
        ),
        "s_address": payload.get("address"),
        "s_phone_number": payload.get("phone_number"),
        "s_gender": payload.get("gender"),
        "s_date_of_birth": _parse_iso_date(payload.get("birth_date")),
        "s_state_id": submitted_state_id,
        "hs_counselor_name": payload.get("counselor_name"),
        "hs_grade": _to_int(payload.get("grade_level")),
        "hs_total_units_earned": _to_float(payload.get("total_units_earned")),
        "hs_total_gpa_course": _to_float(payload.get("gpa")),
        "hs_aca_gpa_course": _to_float(payload.get("academic_gpa")),
        "hs_university_gpa": _to_float(payload.get("university_gpa")),
        "hs_enter_date": _parse_iso_date(payload.get("enter_date")),
        "hs_graduation_date": _parse_iso_date(payload.get("graduation_date")),
    }

    for field_name, value in updates.items():
        if value is not None:
            setattr(student, field_name, value)

    incoming_courses = payload.get("courses") or []
    existing_courses = await _new_transcript_courses_for_student(
        session,
        student_db_id=int(student.id),
        file_id=int(student.source_file),
    )
    existing_by_id = {
        int(course.id): course
        for course in existing_courses
        if getattr(course, "id", None) is not None
    }

    for course_payload in incoming_courses:
        encoded_course_id = _to_int(course_payload.get("id"))
        actual_course_id = (
            _decode_new_record_id(encoded_course_id)
            if encoded_course_id is not None
            else None
        )

        if actual_course_id is not None and actual_course_id in existing_by_id:
            target = existing_by_id[actual_course_id]

            if _payload_is_remove_action(course_payload):
                await session.delete(target)
                continue

            values = _new_course_values(
                student_db_id=int(student.id),
                file_id=int(student.source_file),
                payload=course_payload,
            )
            for field_name, value in values.items():
                if value is not None:
                    setattr(target, field_name, value)

            if not _new_course_has_required_fields(target) and hasattr(
                target, "reviewed_by_user"
            ):
                target.reviewed_by_user = False

        elif encoded_course_id in (None, 0):
            values = _new_course_values(
                student_db_id=int(student.id),
                file_id=int(student.source_file),
                payload=course_payload,
            )
            if any(
                values.get(key) not in (None, "")
                for key in (
                    "crs_id",
                    "crs_description",
                    "crs_letter_grade",
                    "crs_credit_completed",
                    "crs_credit_attempted",
                )
            ):
                new_course = NewTranscriptCourseDetails(**values)
                if not _new_course_has_required_fields(new_course) and hasattr(
                    new_course, "reviewed_by_user"
                ):
                    new_course.reviewed_by_user = False
                session.add(new_course)

    await session.flush()

    # Audit Save Review never auto-completes a file. With light=true, commit
    # immediately and let the explicit Move to Auto Complete endpoint do the full
    # validation. This avoids re-reading and re-serializing dozens of courses.
    current_file_status = (
        await session.execute(
            select(models.ExtractionFileDetails.process_status).where(
                models.ExtractionFileDetails.id == int(student.source_file)
            )
        )
    ).scalar_one_or_none()

    if light and str(current_file_status or "").lower().strip() == "needs_review_audit":
        process_status = "needs_review_audit"
    else:
        process_status = await _refresh_new_transcript_file_status(
            session,
            int(student.source_file),
            allow_complete=False,
        )

    await session.commit()

    if light:
        return {
            "ok": True,
            "student_id": encoded_student_id,
            "source_file": int(student.source_file),
            "is_new_transcript_type": True,
            "process_status": process_status,
        }

    source_file = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == int(student.source_file)
            )
        )
    ).scalar_one_or_none()
    courses = await _new_transcript_courses_for_student(
        session,
        student_db_id=int(student.id),
        file_id=int(student.source_file),
    )
    summary = await _build_summary_for_file(session, source_file)
    response = _serialize_new_transcript_student(
        student,
        courses,
        source_file,
        summary,
        include_courses=True,
    )
    response["ok"] = True
    response["process_status"] = process_status
    return response


async def _update_new_transcript_course_review(
    *,
    session: AsyncSession,
    encoded_course_id: int,
    payload: dict,
    light: bool,
) -> dict:
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    course_db_id = _decode_new_record_id(encoded_course_id)
    if course_db_id is None:
        raise HTTPException(status_code=400, detail="Invalid new transcript course ID")

    course = (
        await session.execute(
            select(NewTranscriptCourseDetails).where(
                NewTranscriptCourseDetails.id == course_db_id
            )
        )
    ).scalar_one_or_none()

    if course is None:
        raise HTTPException(status_code=404, detail="New transcript course not found")

    file_id = int(course.source_file)
    student_db_id = int(course.s_id) if course.s_id is not None else None

    if _payload_is_remove_action(payload):
        await session.delete(course)
        await session.flush()

        if light:
            process_status = (
                await session.execute(
                    select(models.ExtractionFileDetails.process_status).where(
                        models.ExtractionFileDetails.id == file_id
                    )
                )
            ).scalar_one_or_none()
        else:
            process_status = await _refresh_new_transcript_file_status(
                session,
                file_id,
                allow_complete=False,
            )

        await session.commit()

        if light:
            return {
                "ok": True,
                "removed_course_id": encoded_course_id,
                "is_new_transcript_type": True,
                "process_status": process_status,
            }
    else:
        if _payload_has_course_update_fields(payload):
            values = _new_course_values(
                student_db_id=student_db_id or 0,
                file_id=file_id,
                payload=payload,
            )
            for field_name, value in values.items():
                if field_name == "s_id" and student_db_id is None:
                    continue
                if value is not None:
                    setattr(course, field_name, value)

        missing_required_fields = _new_course_missing_required_fields(course)
        requested_reviewed = _new_course_review_requested(payload)

        if missing_required_fields and hasattr(course, "reviewed_by_user"):
            # Any incomplete row must remain unreviewed, including rows that may
            # have been incorrectly marked by an older frontend/backend build.
            course.reviewed_by_user = False

        if requested_reviewed and missing_required_fields:
            # Keep field corrections the user just entered, but do not allow the
            # row to turn green. The client receives a short, non-technical reason.
            await session.flush()
            await session.commit()
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        "This course is not ready to be marked reviewed yet. "
                        "Please add "
                        + _format_new_course_missing_fields(
                            missing_required_fields
                        )
                        + "."
                    ),
                    "missing_fields": missing_required_fields,
                },
            )

        await session.flush()

        if light:
            process_status = (
                await session.execute(
                    select(models.ExtractionFileDetails.process_status).where(
                        models.ExtractionFileDetails.id == file_id
                    )
                )
            ).scalar_one_or_none()
        else:
            process_status = await _refresh_new_transcript_file_status(
                session,
                file_id,
                allow_complete=False,
            )

        await session.commit()

        if light:
            return {
                "ok": True,
                "course_id": encoded_course_id,
                "is_new_transcript_type": True,
                "reviewed_by_user": bool(
                    getattr(course, "reviewed_by_user", False)
                ),
                "process_status": process_status,
            }

    source_file = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == file_id
            )
        )
    ).scalar_one_or_none()

    student = None
    if student_db_id is not None:
        student = (
            await session.execute(
                select(NewTranscriptStudents).where(
                    NewTranscriptStudents.id == student_db_id
                )
            )
        ).scalar_one_or_none()

    if student is None:
        raise HTTPException(
            status_code=404,
            detail="New transcript student not found for course",
        )

    courses = await _new_transcript_courses_for_student(
        session,
        student_db_id=int(student.id),
        file_id=file_id,
    )
    summary = await _build_summary_for_file(session, source_file)
    response = _serialize_new_transcript_student(
        student,
        courses,
        source_file,
        summary,
        include_courses=True,
    )
    response["ok"] = True
    response["process_status"] = process_status

    if _payload_is_remove_action(payload):
        response["removed_course_id"] = encoded_course_id

    return response


async def _refresh_file_status_from_final_courses(
    session: AsyncSession,
    file_id: int,
) -> str:
    students = (
        await session.execute(
            select(models.Students).where(models.Students.source_file == file_id)
        )
    ).scalars().all()

    all_students_complete = bool(students)

    for student in students:
        final_courses = await _final_rows_for_student(
            session,
            student_db_id=student.id,
            file_id=file_id,
        )

        source_file = (
            await session.execute(
                select(models.ExtractionFileDetails).where(
                    models.ExtractionFileDetails.id == file_id
                )
            )
        ).scalar_one_or_none()

        if not _is_student_complete(student, final_courses, source_file):
            all_students_complete = False
            break

    summary = await _build_reconciliation_summary(session, file_id)

    final_status = (
        "completed"
        if (
            all_students_complete
            and summary.get("final_course_count", 0) > 0
            and summary.get("open_review_count", 0) == 0
            and not summary.get("final_count_shortfall", False)
        )
        else "needs_review"
    )

    await session.execute(
        update(models.ExtractionFileDetails)
        .where(models.ExtractionFileDetails.id == file_id)
        .values(
            process_status=final_status,
            processed_date=_now(),
        )
    )

    return final_status


def _course_values_for_final_table(
    *,
    model_cls: Any,
    student: models.Students,
    file_id: int,
    payload: dict,
) -> dict:
    course_name = str(payload.get("name") or payload.get("course_name") or "").strip()
    course_grade = str(payload.get("grade") or payload.get("letter_grade") or "").strip()

    credits_completed = _to_float(
        _first_non_empty(
            payload.get("credits_completed"),
            payload.get("credit_completed"),
            payload.get("credits"),
        )
    )

    credits_attempted = _to_float(
        _first_non_empty(
            payload.get("credits_attempted"),
            payload.get("credit_attempted"),
            credits_completed,
        )
    )

    course_id = _first_non_empty(
        payload.get("crs_id"),
        payload.get("course_id"),
    )

    field_decisions = _safe_json_dict(
        payload.get("field_decisions") or payload.get("field_sources")
    )

    if not field_decisions:
        field_decisions = {"manual": "user"}

    incoming_source = _first_non_empty(
        payload.get("final_source"),
        payload.get("source"),
        payload.get("extraction_source"),
        "manual",
    )

    final_source = _normalize_final_source(incoming_source)

    values = {
        "s_id": student.id,
        "student_id": student.id,
        "source_file": file_id,
        "extraction_file_id": file_id,

        "crs_id": course_id,
        "course_id": course_id,

        "crs_description": course_name or None,
        "course_name": course_name or None,
        "name": course_name or None,

        "crs_letter_grade": course_grade or None,
        "letter_grade": course_grade or None,
        "grade": course_grade or None,

        "crs_credit_completed": credits_completed,
        "credit_completed": credits_completed,
        "credits_completed": credits_completed,

        "crs_credit_attempted": credits_attempted,
        "credit_attempted": credits_attempted,
        "credits_attempted": credits_attempted,

        "crs_grade": _to_int(payload.get("grade_level")),
        "grade_level": _to_int(payload.get("grade_level")),

        "crs_month": _month_to_int(payload.get("month")),
        "month": _month_to_int(payload.get("month")),

        "crs_year": _year_to_int(payload.get("year")),
        "year": _year_to_int(payload.get("year")),

        "crs_hs": payload.get("school") or payload.get("school_name"),
        "school": payload.get("school") or payload.get("school_name"),
        "school_name": payload.get("school") or payload.get("school_name"),

        "final_source": final_source,
        "review_status": _normalize_review_status(
            payload.get("review_status"),
            needs_review=bool(payload.get("needs_review", False)),
        ),
        "needs_review": bool(payload.get("needs_review", False)),
        "review_reason": payload.get("review_reason"),
        "resolution_reason": (
            payload.get("resolution_reason")
            or payload.get("resolution")
            or "Manual review update"
        ),
        "field_decisions": field_decisions,

        "updated_at": _now(),
    }

    if _has_column(model_cls, "created_at"):
        values["created_at"] = _now()

    return _filter_model_values(model_cls, values)


async def _null_out_cross_table_links(
    session: AsyncSession,
    *,
    file_id: int,
    FinalCourseDetails: Any,
    CourseExtractionMatches: Any,
) -> None:
    match_null_values = {}

    if _has_column(CourseExtractionMatches, "final_course_detail_id"):
        match_null_values["final_course_detail_id"] = None

    if match_null_values:
        await session.execute(
            update(CourseExtractionMatches)
            .where(_file_column(CourseExtractionMatches) == file_id)
            .values(**match_null_values)
        )

    await session.flush()


async def _find_match_rows_for_final_course(
    session: AsyncSession,
    *,
    CourseExtractionMatches: Any,
    final_course: Any,
) -> list[Any]:
    final_course_id = getattr(final_course, "id", None)

    if final_course_id is None:
        return []

    rows_by_id: dict[int, Any] = {}

    if _has_column(CourseExtractionMatches, "final_course_detail_id"):
        linked_rows = (
            await session.execute(
                select(CourseExtractionMatches).where(
                    CourseExtractionMatches.final_course_detail_id
                    == int(final_course_id)
                )
            )
        ).scalars().all()

        for row in linked_rows:
            if getattr(row, "id", None) is not None:
                rows_by_id[int(row.id)] = row

    return list(rows_by_id.values())


def _mark_match_resolved(
    match_row: Any,
    *,
    resolution_reason: str,
) -> None:
    _set_if_has(match_row, "needs_review", False)
    _set_if_has(match_row, "review_reason", None)
    _set_if_has(match_row, "resolution_reason", resolution_reason)
    _set_if_has(match_row, "reviewed_by_user", True)
    _set_if_has(match_row, "reviewed_at", _now())
    _set_if_has(match_row, "updated_at", _now())


def _mark_match_removed(match_row: Any) -> None:
    _mark_match_resolved(
        match_row,
        resolution_reason="Removed by user during final course review",
    )

    if hasattr(match_row, "final_course_detail_id"):
        match_row.final_course_detail_id = None


async def _remove_final_course_row(
    session: AsyncSession,
    *,
    final_course: Any,
    CourseExtractionMatches: Any,
) -> tuple[int, int | None, int]:
    file_id = _get_attr(final_course, "source_file", "extraction_file_id")
    student_db_id = _get_attr(final_course, "s_id", "student_id")

    if not file_id:
        raise HTTPException(status_code=400, detail="Final course has no source file")

    match_rows = await _find_match_rows_for_final_course(
        session,
        CourseExtractionMatches=CourseExtractionMatches,
        final_course=final_course,
    )

    for match_row in match_rows:
        _mark_match_removed(match_row)

    await session.delete(final_course)
    await session.flush()

    return int(file_id), _to_int(student_db_id), len(match_rows)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/files")
async def list_extraction_files(
    session: AsyncSession = Depends(get_session),
    status: str | None = Query(None),
    term: str | None = Query(None),
):
    stmt = select(models.ExtractionFileDetails).order_by(
        models.ExtractionFileDetails.upload_date.desc()
    )

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            stmt = stmt.where(models.ExtractionFileDetails.process_status.in_(statuses))

    if term:
        stmt = stmt.where(models.ExtractionFileDetails.year_intake == term)

    rows = (await session.execute(stmt)).scalars().all()

    results = []

    for row in rows:
        summary = await _build_summary_for_file(session, row)

        results.append(
            {
                "id": row.id,
                "file_name": row.file_name,
                "process_status": row.process_status,
                "upload_date": row.upload_date,
                "processed_date": getattr(row, "processed_date", None),
                "institution_id": row.institution_id,
                "year_intake": row.year_intake,
                "program_id": row.program_id,
                "classifier_type": row.classifier_type,

                "validation_result": summary,
                "course_validation": summary,
                "course_reconciliation": summary,
                "reconciliation_summary": summary,
                "validation_status": row.process_status,
                "validation_type": "course_reconciliation",
                "validation_result_id": None,

                **summary,
            }
        )

    return results


async def _batch_recon_counts(session: AsyncSession, file_ids: list[int]) -> dict[int, dict]:
    """Per-file reconciliation counts via SQL aggregation (no course-row loading).
    Powers the Completed/Needs Review list summaries cheaply."""
    out: dict[int, dict] = {fid: {} for fid in file_ids}
    if not file_ids:
        return out
    from sqlalchemy import func

    async def _count(file_col, *, flt=None):
        stmt = select(file_col, func.count() if flt is None else func.count().filter(flt)).where(
            file_col.in_(file_ids)
        ).group_by(file_col)
        return {fid: n for fid, n in (await session.execute(stmt)).all()}

    docai = await _count(models.Course_details.source_file)
    gemini = await _count(models.GeminiCourseDetails.source_file)
    FCD = models.FinalCourseDetails
    final_total = await _count(FCD.source_file)
    final_nr = await _count(FCD.source_file, flt=FCD.needs_review.is_(True))
    M = models.CourseExtractionMatches
    match_unresolved = await _count(
        M.extraction_file_id, flt=M.needs_review.is_(True) & M.reviewed_by_user.is_(False)
    )
    # A row is "auto-fixed" when reconciliation took a value from Gemini for any
    # user-visible field (month-only fixes don't count); "clean" when Document AI
    # stood on its own. The per-field source columns store the compact label "gem".
    from sqlalchemy import or_
    gem_cols = (
        FCD.crs_id_source, FCD.crs_description_source, FCD.crs_letter_grade_source,
        FCD.crs_hs_source, FCD.crs_grade_source, FCD.crs_year_source,
        FCD.crs_credit_attempted_source, FCD.crs_credit_completed_source,
        FCD.crs_term_gpa_source,
    )
    gemini_used = or_(*[col.ilike("gem%") for col in gem_cols])
    auto_fixed = await _count(FCD.source_file, flt=gemini_used)

    for fid in file_ids:
        d = docai.get(fid, 0) or 0
        g = gemini.get(fid, 0) or 0
        f = final_total.get(fid, 0) or 0
        fnr = final_nr.get(fid, 0) or 0
        munr = match_unresolved.get(fid, 0) or 0
        af = auto_fixed.get(fid, 0) or 0
        open_review = fnr + munr
        out[fid] = {
            "document_ai_course_count": d,
            "raw_document_ai_course_count": d,
            "gemini_course_count": g,
            "raw_gemini_course_count": g,
            "raw_max_source_course_count": max(d, g),
            "final_course_count": f,
            "actual_final_course_count": f,
            "expected_final_course_count": max(d, g),
            "needs_review_count": open_review,
            "open_review_count": open_review,
            "final_needs_review_count": fnr,
            "auto_fixed_count": af,
            "clean_count": max(0, f - af - fnr),
            "final_count_shortfall": f < max(d, g),
        }
    return out


@router.get("/section-counts")
async def section_counts(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
):
    """Per-section counts for the sidebar badges — two grouped queries, no row
    loading, safe to poll."""
    from sqlalchemy import func
    F = models.ExtractionFileDetails
    stmt = select(F.process_status, func.count()).group_by(F.process_status)
    if year_intake:
        stmt = stmt.where(F.year_intake == year_intake)
    by_status = {(s or "unknown"): n for s, n in (await session.execute(stmt)).all()}
    completed = by_status.get("completed", 0)
    needs_review = by_status.get("needs_review", 0)
    needs_review_audit = by_status.get("needs_review_audit", 0)
    new_type = by_status.get("new_type", 0)
    # Not Processed uses the SAME predicate as the /not-processed list (see
    # _not_processed_conditions) so the badge count and the list can't diverge.
    np_stmt = (
        select(func.count()).select_from(F).where(*_not_processed_conditions(F))
    )
    if year_intake:
        np_stmt = np_stmt.where(F.year_intake == year_intake)
    not_processed = (await session.execute(np_stmt)).scalar() or 0
    # Upload = every transcript uploaded for the term (all statuses) — matches the
    # "N files" the Upload page shows (both are ExtractionFileDetails for the term).
    upload_total = sum(by_status.values())
    # Classify = transcripts that have a detected classifier/type.
    cstmt = select(func.count()).select_from(F).where(F.classifier_type.isnot(None))
    if year_intake:
        cstmt = cstmt.where(F.year_intake == year_intake)
    classify_total = (await session.execute(cstmt)).scalar() or 0
    dstmt = (
        select(models.StudentAgSummary.admission_decision, func.count())
        .join(models.Students, models.Students.id == models.StudentAgSummary.student_id)
        .join(F, models.Students.source_file == F.id)
        .where(F.process_status == "completed")
        .group_by(models.StudentAgSummary.admission_decision)
    )
    if year_intake:
        dstmt = dstmt.where(F.year_intake == year_intake)
    d = {(k or "pending"): n for k, n in (await session.execute(dstmt)).all()}
    admitted = d.get("admitted", 0)
    denied = d.get("denied", 0)
    waitlisted = d.get("waitlisted", 0)
    pending = d.get("pending", 0)
    return {
        "completed": completed,
        "needs_review": needs_review,
        "needs_review_audit": needs_review_audit,
        "audit_review": needs_review_audit,
        "human_review_with_audit": needs_review_audit,
        "not_processed": not_processed,
        "new_type": new_type,
        "upload_total": upload_total,
        "classify_total": classify_total,
        "admitted": admitted,
        "denied": denied,
        "waitlisted": waitlisted,
        "pending": pending,
        # Admission Center header total — all students with a computed decision.
        "decisions_total": admitted + denied + waitlisted + pending,
    }


@router.get("/decision-trends")
async def decision_trends(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
):
    """Admission decisions grouped by the month the transcript was processed, for
    the selected term. Feeds the dashboard's month-wise trend chart with REAL
    data (no estimates)."""
    from sqlalchemy import func
    F = models.ExtractionFileDetails
    ym = func.to_char(func.date_trunc("month", F.processed_date), "YYYY-MM")
    stmt = (
        select(ym.label("ym"), models.StudentAgSummary.admission_decision, func.count())
        .join(models.Students, models.Students.id == models.StudentAgSummary.student_id)
        .join(F, models.Students.source_file == F.id)
        .where(F.process_status == "completed", F.processed_date.isnot(None))
        .group_by(ym, models.StudentAgSummary.admission_decision)
    )
    if year_intake:
        stmt = stmt.where(F.year_intake == year_intake)
    rows = (await session.execute(stmt)).all()

    by_month: dict[str, dict[str, int]] = {}
    for ym_value, decision, count in rows:
        if not ym_value:
            continue
        bucket = by_month.setdefault(
            ym_value, {"admitted": 0, "denied": 0, "waitlisted": 0, "pending": 0}
        )
        key = decision or "pending"
        if key in bucket:
            bucket[key] += int(count)
    months = [
        {
            "ym": k,
            "admitted": v["admitted"],
            "denied": v["denied"],
            "waitlisted": v["waitlisted"],
        }
        for k, v in sorted(by_month.items())
    ]
    return {"months": months}


@router.get("/completed")
async def list_completed_students(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
    slim: bool = Query(False),
):
    # Existing trusted transcript students.
    student_stmt = (
        select(models.Students, models.ExtractionFileDetails)
        .join(
            models.ExtractionFileDetails,
            models.Students.source_file == models.ExtractionFileDetails.id,
        )
        .where(models.ExtractionFileDetails.process_status == "completed")
        .order_by(models.Students.id.desc())
        .options(noload("*"))
    )

    if year_intake:
        student_stmt = student_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    student_file_rows = (await session.execute(student_stmt)).all()
    students = [row[0] for row in student_file_rows]
    files_by_student_id = {row[0].id: row[1] for row in student_file_rows}
    student_db_ids = [student.id for student in students]

    ag_by_student_id: dict[int, Any] = {}
    if student_db_ids:
        ag_rows = (
            await session.execute(
                select(models.StudentAgSummary)
                .where(models.StudentAgSummary.student_id.in_(student_db_ids))
                .options(noload("*"))
            )
        ).scalars().all()
        ag_by_student_id = {row.student_id: row for row in ag_rows}

    classifier_names = await _classifier_names_for(
        session,
        files_by_student_id.values(),
    )
    results: list[dict] = []

    if slim:
        for student in students:
            source_file = files_by_student_id.get(student.id)
            ag = ag_by_student_id.get(student.id)
            results.append(
                {
                    "id": str(student.s_id or student.id),
                    "db_id": student.id,
                    "student_id": student.s_id,
                    "student_name": student.s_name,
                    "file_name": getattr(source_file, "file_name", None),
                    "format": _format_label(source_file, classifier_names),
                    "school_name": getattr(student, "hs_name", None),
                    "birth_date": getattr(student, "s_date_of_birth", None),
                    "graduation_date": getattr(student, "hs_graduation_date", None),
                    "address": getattr(student, "s_address", None),
                    "source_file": getattr(source_file, "id", None),
                    "admission_decision": ag.admission_decision if ag else None,
                    "reviewed": bool(getattr(ag, "reviewed", False)) if ag else False,
                    "effective_status": "completed",
                    "is_new_transcript_type": False,
                }
            )
    else:
        file_ids = [
            sf.id
            for sf in files_by_student_id.values()
            if sf is not None
        ]
        counts = await _batch_recon_counts(session, file_ids)

        for student in students:
            source_file = files_by_student_id.get(student.id)
            if source_file is None:
                continue

            c = counts.get(source_file.id, {})
            ag = ag_by_student_id.get(student.id)
            needs_attention = bool(
                c.get("open_review_count", 0) > 0
                or c.get("final_count_shortfall")
            )

            results.append(
                {
                    "id": str(student.s_id or student.id),
                    "db_id": student.id,
                    "student_id": student.s_id,
                    "student_name": student.s_name,
                    "file_name": getattr(source_file, "file_name", None),
                    "format": _format_label(source_file, classifier_names),
                    "school_name": getattr(student, "hs_name", None),
                    "birth_date": getattr(student, "s_date_of_birth", None),
                    "graduation_date": getattr(student, "hs_graduation_date", None),
                    "address": getattr(student, "s_address", None),
                    "gpa": (
                        getattr(student, "hs_total_gpa_course", None)
                        or getattr(student, "hs_aca_gpa_course", None)
                        or getattr(student, "hs_university_gpa", None)
                    ),
                    "source_file": source_file.id,
                    "admission_decision": ag.admission_decision if ag else None,
                    "reviewed": (
                        bool(getattr(ag, "reviewed", False))
                        if ag
                        else False
                    ),
                    "effective_status": "completed",
                    "needs_attention": needs_attention,
                    "review_reason": (
                        "course_count_shortfall"
                        if c.get("final_count_shortfall")
                        else ("open_review" if needs_attention else None)
                    ),
                    "is_new_transcript_type": False,
                    **c,
                }
            )

    # Gemini-only new transcript students.
    NewTranscriptStudents = _new_transcript_student_model()
    new_stmt = (
        select(NewTranscriptStudents, models.ExtractionFileDetails)
        .join(
            models.ExtractionFileDetails,
            NewTranscriptStudents.source_file
            == models.ExtractionFileDetails.id,
        )
        .where(models.ExtractionFileDetails.process_status == "completed")
        .order_by(NewTranscriptStudents.id.desc())
        .options(noload("*"))
    )

    if year_intake:
        new_stmt = new_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    new_student_file_rows = (await session.execute(new_stmt)).all()

    if new_student_file_rows:
        new_file_ids = list(
            {
                int(file_row.id)
                for _, file_row in new_student_file_rows
            }
        )
        new_courses_by_file: dict[int, list[Any]] = {}
        NewTranscriptCourseDetails = _new_transcript_course_model()

        new_course_rows = (
            await session.execute(
                select(NewTranscriptCourseDetails)
                .where(
                    NewTranscriptCourseDetails.source_file.in_(new_file_ids)
                )
                .order_by(
                    NewTranscriptCourseDetails.crs_year.asc(),
                    NewTranscriptCourseDetails.crs_grade.asc(),
                    NewTranscriptCourseDetails.crs_month.asc(),
                    NewTranscriptCourseDetails.id.asc(),
                )
                .options(noload("*"))
            )
        ).scalars().all()

        for course in new_course_rows:
            new_courses_by_file.setdefault(
                int(course.source_file),
                [],
            ).append(course)

        for student, source_file in new_student_file_rows:
            student_courses = [
                course
                for course in new_courses_by_file.get(int(source_file.id), [])
                if _to_int(course.s_id) == int(student.id)
            ]
            summary = _build_new_transcript_summary_from_rows(
                source_file=source_file,
                students=[student],
                courses=student_courses,
            )

            if slim:
                results.append(
                    {
                        "id": str(_encode_new_record_id(student.id)),
                        "db_id": _encode_new_record_id(student.id),
                        "student_id": student.s_id,
                        "student_name": student.s_name,
                        "format": student.hs_name,
                        "school_name": student.hs_name,
                        "birth_date": student.s_date_of_birth,
                        "graduation_date": student.hs_graduation_date,
                        "address": student.s_address,
                        "source_file": source_file.id,
                        "admission_decision": None,
                        "reviewed": False,
                        "effective_status": "completed",
                        "is_new_transcript_type": True,
                        "storage_source": "new_transcript_tables",
                    }
                )
            else:
                serialized = _serialize_new_transcript_student(
                    student,
                    student_courses,
                    source_file,
                    summary,
                    include_courses=False,
                )
                serialized["effective_status"] = "completed"
                serialized["needs_attention"] = False
                serialized["admission_decision"] = None
                serialized["reviewed"] = False
                results.append(serialized)

    return results


@router.get("/audit-review")
async def list_audit_review(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
):
    """
    Return only Gemini-only new transcript files routed to Human Review with
    Audit. Normal needs_review rows remain on the existing Human Review page.
    """
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    student_stmt = (
        select(NewTranscriptStudents, models.ExtractionFileDetails)
        .join(
            models.ExtractionFileDetails,
            NewTranscriptStudents.source_file
            == models.ExtractionFileDetails.id,
        )
        .where(
            models.ExtractionFileDetails.process_status
            == "needs_review_audit"
        )
        .order_by(NewTranscriptStudents.id.desc())
        .options(noload("*"))
    )

    if year_intake:
        student_stmt = student_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    student_file_rows = (await session.execute(student_stmt)).all()
    results: list[dict] = []
    student_file_ids: set[int] = set()

    if student_file_rows:
        file_ids = list(
            {
                int(source_file.id)
                for _, source_file in student_file_rows
            }
        )

        course_rows = (
            await session.execute(
                select(NewTranscriptCourseDetails)
                .where(
                    NewTranscriptCourseDetails.source_file.in_(file_ids)
                )
                .order_by(
                    NewTranscriptCourseDetails.crs_year.asc(),
                    NewTranscriptCourseDetails.crs_grade.asc(),
                    NewTranscriptCourseDetails.crs_month.asc(),
                    NewTranscriptCourseDetails.id.asc(),
                )
                .options(noload("*"))
            )
        ).scalars().all()

        courses_by_file: dict[int, list[Any]] = {}
        for course in course_rows:
            courses_by_file.setdefault(
                int(course.source_file),
                [],
            ).append(course)

        for student, source_file in student_file_rows:
            file_id = int(source_file.id)
            student_file_ids.add(file_id)

            student_courses = [
                course
                for course in courses_by_file.get(file_id, [])
                if _to_int(course.s_id) == int(student.id)
            ]

            summary = _build_new_transcript_summary_from_rows(
                source_file=source_file,
                students=[student],
                courses=student_courses,
            )

            serialized = _serialize_new_transcript_student(
                student,
                student_courses,
                source_file,
                summary,
                include_courses=True,
            )
            serialized["effective_status"] = "needs_review_audit"
            serialized["process_status"] = "needs_review_audit"
            serialized["file_status"] = "needs_review_audit"
            serialized["review_bucket"] = "human_review_with_audit"
            serialized["review_reason"] = (
                "incomplete_student_or_course_data"
                if not _is_new_transcript_student_complete(
                    student,
                    student_courses,
                )
                else "gemini_only_new_transcript_pending_audit"
            )
            results.append(serialized)

    # Keep audit files visible even when Gemini could not create a student row.
    orphan_stmt = select(models.ExtractionFileDetails).where(
        models.ExtractionFileDetails.process_status
        == "needs_review_audit"
    )

    if student_file_ids:
        orphan_stmt = orphan_stmt.where(
            models.ExtractionFileDetails.id.notin_(student_file_ids)
        )

    if year_intake:
        orphan_stmt = orphan_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    orphan_files = (await session.execute(orphan_stmt)).scalars().all()

    for source_file in orphan_files:
        summary = _build_new_transcript_summary_from_rows(
            source_file=source_file,
            students=[],
            courses=[],
        )

        results.append(
            {
                "id": None,
                "student_id": None,
                "db_id": None,
                "new_transcript_student_id": None,
                "student_name": source_file.file_name,
                "file_name": source_file.file_name,
                "email": None,
                "format": "Unknown School",
                "school_name": "Unknown School",
                "birth_date": None,
                "graduation_date": None,
                "address": None,
                "gpa": None,
                "recalculated_gpa": None,
                "marks": None,
                "source_file": source_file.id,
                "file_status": "needs_review_audit",
                "process_status": "needs_review_audit",
                "effective_status": "needs_review_audit",
                "student_data_complete": False,
                "processed_at": (
                    getattr(source_file, "processed_date", None)
                    or getattr(source_file, "upload_date", None)
                ),
                "is_file_only": True,
                "is_new_transcript_type": True,
                "storage_source": "new_transcript_tables",
                "review_bucket": "human_review_with_audit",
                "review_reason": "gemini_extraction_requires_full_audit",
                "courses": None,
                "course_count": 0,
                "validation_result": summary,
                "course_validation": summary,
                "course_reconciliation": summary,
                "reconciliation_summary": summary,
                "validation_status": summary.get("status"),
                "validation_result_id": None,
                "validation_type": "gemini_only_new_transcript",
                **summary,
            }
        )

    return results


@router.get("/needs-review")
async def list_needs_review(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
):
    # Existing trusted-pipeline students.
    student_stmt = (
        select(models.Students, models.ExtractionFileDetails)
        .join(
            models.ExtractionFileDetails,
            models.Students.source_file == models.ExtractionFileDetails.id,
        )
        .where(models.ExtractionFileDetails.process_status == "needs_review")
        .order_by(models.Students.id.desc())
        .options(noload("*"))
    )

    if year_intake:
        student_stmt = student_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    student_file_rows = (await session.execute(student_stmt)).all()
    students = [row[0] for row in student_file_rows]
    files_by_student_id = {row[0].id: row[1] for row in student_file_rows}
    student_source_files = {
        int(student.source_file)
        for student in students
        if student.source_file
    }

    results: list[dict] = []

    nr_file_ids = list(
        {
            int(source_file.id)
            for source_file in files_by_student_id.values()
            if source_file is not None
        }
    )
    prefetch_by_file, matches_by_file, final_rows_by_file = (
        await _prefetch_reconciliation(
            session,
            nr_file_ids,
            with_uc=False,
        )
    )
    final_courses_by_student = {
        student.id: (
            final_rows_by_file.get(int(student.source_file), [])
            if student.source_file
            else []
        )
        for student in students
    }
    classifier_names = await _classifier_names_for(session, files_by_student_id.values())

    for student in students:
        final_courses = final_courses_by_student.get(student.id, [])
        source_file = files_by_student_id.get(student.id)

        if source_file is None:
            continue

        file_status = _get_file_status(source_file)
        file_status_normalized = str(file_status or "").lower().strip()

        if file_status_normalized != "needs_review":
            continue

        summary = await _build_reconciliation_summary(
            session,
            source_file.id,
            prefetch=prefetch_by_file.get(source_file.id),
        )

        student_complete = _is_student_complete(
            student,
            final_courses,
            source_file,
        )

        should_show = bool(
            not student_complete
            or summary.get("open_review_count", 0) > 0
            or summary.get("needs_review_count", 0) > 0
            or summary.get("final_count_shortfall", False)
            or summary.get("course_id_mismatch_count", 0) > 0
        )

        if not should_show and file_status_normalized != "needs_review":
            continue

        match_lookup = _match_lookup_from_matches(
            matches_by_file.get(source_file.id, [])
        )

        serialized = _serialize_student(
            student,
            final_courses,
            source_file,
            summary,
            match_lookup,
            include_courses=False,  # slim list; dialog fetches courses on open
            format_label=_format_label(source_file, classifier_names),
        )
        serialized["effective_status"] = "needs_review"
        serialized["is_new_transcript_type"] = False

        if summary.get("final_count_shortfall"):
            serialized["review_reason"] = "course_count_shortfall"
        elif summary.get("needs_review_count", 0) > 0:
            serialized["review_reason"] = "final_course_rows_need_review"
        elif not student_complete:
            serialized["review_reason"] = (
                "incomplete_student_or_final_course_data"
            )
        else:
            serialized["review_reason"] = "file_marked_needs_review"

        results.append(serialized)

    # Gemini-only new transcript students.
    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    new_stmt = (
        select(NewTranscriptStudents, models.ExtractionFileDetails)
        .join(
            models.ExtractionFileDetails,
            NewTranscriptStudents.source_file
            == models.ExtractionFileDetails.id,
        )
        .where(models.ExtractionFileDetails.process_status == "needs_review")
        .order_by(NewTranscriptStudents.id.desc())
        .options(noload("*"))
    )

    if year_intake:
        new_stmt = new_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    new_student_file_rows = (await session.execute(new_stmt)).all()

    if new_student_file_rows:
        new_file_ids = list(
            {
                int(source_file.id)
                for _, source_file in new_student_file_rows
            }
        )

        new_course_rows = (
            await session.execute(
                select(NewTranscriptCourseDetails)
                .where(
                    NewTranscriptCourseDetails.source_file.in_(new_file_ids)
                )
                .order_by(
                    NewTranscriptCourseDetails.crs_year.asc(),
                    NewTranscriptCourseDetails.crs_grade.asc(),
                    NewTranscriptCourseDetails.crs_month.asc(),
                    NewTranscriptCourseDetails.id.asc(),
                )
                .options(noload("*"))
            )
        ).scalars().all()

        new_courses_by_file: dict[int, list[Any]] = {}
        for course in new_course_rows:
            new_courses_by_file.setdefault(
                int(course.source_file),
                [],
            ).append(course)

        for student, source_file in new_student_file_rows:
            student_source_files.add(int(source_file.id))
            student_courses = [
                course
                for course in new_courses_by_file.get(int(source_file.id), [])
                if _to_int(course.s_id) == int(student.id)
            ]
            summary = _build_new_transcript_summary_from_rows(
                source_file=source_file,
                students=[student],
                courses=student_courses,
            )
            serialized = _serialize_new_transcript_student(
                student,
                student_courses,
                source_file,
                summary,
                include_courses=False,
            )
            serialized["effective_status"] = "needs_review"
            serialized["review_reason"] = (
                "incomplete_student_or_course_data"
                if not _is_new_transcript_student_complete(
                    student,
                    student_courses,
                )
                else "gemini_only_new_transcript_pending_human_review"
            )
            results.append(serialized)

    # Files with no student row remain visible as file-only review records.
    from sqlalchemy import exists as sa_exists

    orphan_stmt = select(models.ExtractionFileDetails).where(
        models.ExtractionFileDetails.process_status == "needs_review",
        ~sa_exists().where(
            models.Students.source_file
            == models.ExtractionFileDetails.id
        ),
        ~sa_exists().where(
            NewTranscriptStudents.source_file
            == models.ExtractionFileDetails.id
        ),
    )

    if year_intake:
        orphan_stmt = orphan_stmt.where(
            models.ExtractionFileDetails.year_intake == year_intake
        )

    orphan_files = (await session.execute(orphan_stmt)).scalars().all()

    for file_row in orphan_files:
        if file_row.id in student_source_files:
            continue

        summary = await _build_summary_for_file(session, file_row)

        results.append(
            {
                "id": None,
                "student_id": None,
                "db_id": None,
                "student_name": file_row.file_name,
                "file_name": file_row.file_name,
                "email": None,
                "format": _format_label(file_row),
                "birth_date": None,
                "graduation_date": None,
                "address": None,
                "gpa": None,
                "marks": None,
                "source_file": file_row.id,
                "file_status": file_row.process_status,
                "process_status": file_row.process_status,
                "effective_status": "needs_review",
                "processed_at": file_row.upload_date,
                "courses": [],
                "final_courses": [],
                "final_course_details": [],
                "is_file_only": True,
                "is_new_transcript_type": bool(
                    summary.get("is_new_transcript_type", False)
                ),
                "review_reason": "file_marked_needs_review",
                "validation_result": summary,
                "course_validation": summary,
                "course_reconciliation": summary,
                "reconciliation_summary": summary,
                "validation_status": file_row.process_status,
                "validation_type": summary.get(
                    "validation_type",
                    "course_reconciliation",
                ),
                "validation_result_id": None,
                **summary,
            }
        )

    return results


@router.post("/files/{file_id}/create-student")
async def create_student_for_file(
    file_id: int,
    payload: dict,
    session: AsyncSession = Depends(get_session),
):
    extraction_row = (
        await session.execute(
            select(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == file_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if not extraction_row:
        raise HTTPException(status_code=404, detail="File not found")

    is_new_transcript_request = bool(
        payload.get("is_new_transcript_type")
        or payload.get("storage_source") == "new_transcript_tables"
        or await _is_new_transcript_file(session, file_id)
    )

    if is_new_transcript_request:
        return await _create_new_transcript_student_for_file(
            session=session,
            extraction_row=extraction_row,
            payload=payload,
        )

    from datetime import date as _date

    def _parse_date(val):
        if not val:
            return None
        if isinstance(val, _date):
            return val
        try:
            return _date.fromisoformat(str(val))
        except (ValueError, TypeError):
            return None

    def _parse_float(val):
        if val in (None, ""):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    student_id = payload.get("student_id") or file_id

    student = models.Students(
        s_id=student_id,
        s_name=payload.get("student_name") or payload.get("name"),
        hs_name=payload.get("format") or payload.get("school") or "",
        s_address=payload.get("address"),
        s_date_of_birth=_parse_date(payload.get("birth_date")),
        hs_graduation_date=_parse_date(payload.get("graduation_date")),
        hs_total_gpa_course=_parse_float(payload.get("gpa")),
        source_file=file_id,
    )

    session.add(student)
    await session.flush()

    FinalCourseDetails = _final_course_model()

    for course in payload.get("courses") or []:
        course_name = str(
            course.get("name") or course.get("course_name") or ""
        ).strip()
        course_grade = str(course.get("grade") or "").strip()
        credits = _to_float(
            _first_non_empty(
                course.get("credits"),
                course.get("credits_completed"),
                course.get("credit_completed"),
            )
        )

        if not course_name and not course_grade and credits is None:
            continue

        values = _course_values_for_final_table(
            model_cls=FinalCourseDetails,
            student=student,
            file_id=file_id,
            payload=course,
        )

        session.add(FinalCourseDetails(**values))

    await session.flush()

    await _refresh_file_status_from_final_courses(session, file_id)

    await session.commit()
    await session.refresh(student)

    final_courses = await _final_rows_for_student(
        session,
        student_db_id=student.id,
        file_id=file_id,
    )

    summary = await _build_reconciliation_summary(session, file_id)
    match_lookup = await _match_lookup_by_final_course_id(session, file_id)

    return _serialize_student(
        student,
        final_courses,
        extraction_row,
        summary,
        match_lookup,
    )


@router.get("/students/{student_db_id}/detail")
async def get_student_detail(
    student_db_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Full serialized student (with courses + reconciliation), fetched on demand
    when the detail dialog opens. The /completed and /needs-review list endpoints
    stay slim (no per-student course arrays) and load fast; the dialog rebuilds
    from this full payload. Same shape as a list row used to have."""

    new_student_id = _decode_new_record_id(student_db_id)
    if new_student_id is not None:
        NewTranscriptStudents = _new_transcript_student_model()

        row = (
            await session.execute(
                select(
                    NewTranscriptStudents,
                    models.ExtractionFileDetails,
                )
                .outerjoin(
                    models.ExtractionFileDetails,
                    NewTranscriptStudents.source_file
                    == models.ExtractionFileDetails.id,
                )
                .where(NewTranscriptStudents.id == new_student_id)
            )
        ).first()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="New transcript student not found",
            )

        student, source_file = row
        courses = await _new_transcript_courses_for_student(
            session,
            student_db_id=int(student.id),
            file_id=int(student.source_file),
        )
        summary = _build_new_transcript_summary_from_rows(
            source_file=source_file,
            students=[student],
            courses=courses,
        )

        return _serialize_new_transcript_student(
            student,
            courses,
            source_file,
            summary,
            include_courses=True,
        )

    # Student + its source file in one round trip.
    row = (
        await session.execute(
            select(models.Students, models.ExtractionFileDetails)
            .outerjoin(
                models.ExtractionFileDetails,
                models.Students.source_file == models.ExtractionFileDetails.id,
            )
            .where(models.Students.id == student_db_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Student not found")
    student, source_file = row
    file_id = student.source_file

    if file_id:
        final_courses = await _final_rows_for_student(
            session, student_db_id=student_db_id, file_id=file_id
        )
        summary = await _build_reconciliation_summary(session, file_id)
        match_lookup = await _match_lookup_by_final_course_id(session, file_id)
    else:
        final_courses, summary, match_lookup = [], {}, {}

    return _serialize_student(
        student,
        final_courses,
        source_file,
        summary,
        match_lookup,
        include_courses=True,
    )


@router.post("/students/{student_id}/review")
async def update_student_and_courses(
    student_id: int,
    payload: dict,
    light: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    if _decode_new_record_id(student_id) is not None:
        return await _update_new_transcript_student_and_courses(
            session=session,
            encoded_student_id=student_id,
            payload=payload,
            light=light,
        )

    student = (
        await session.execute(
            select(models.Students).where(models.Students.id == student_id)
        )
    ).scalar_one_or_none()

    if not student:
        student = (
            await session.execute(
                select(models.Students).where(models.Students.s_id == student_id)
            )
        ).scalars().first()

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    from datetime import date as _date

    def _parse_date(val):
        if not val:
            return None
        if isinstance(val, _date):
            return val
        try:
            return _date.fromisoformat(str(val))
        except (ValueError, TypeError):
            return None

    def _parse_float(val):
        if val in (None, ""):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    updates = {
        "s_name": payload.get("student_name") or payload.get("name"),
        "hs_name": payload.get("format") or payload.get("school"),
        "s_address": payload.get("address"),
        "s_date_of_birth": _parse_date(payload.get("birth_date")),
        "hs_graduation_date": _parse_date(payload.get("graduation_date")),
        "hs_total_gpa_course": _parse_float(payload.get("gpa")),
    }

    for key, value in updates.items():
        if value is not None and hasattr(student, key):
            setattr(student, key, value)

    FinalCourseDetails = _final_course_model()
    CourseExtractionMatches = _match_model()
    incoming_courses = payload.get("courses") or []

    if incoming_courses:
        existing_final_courses = await _final_rows_for_student(
            session,
            student_db_id=student.id,
            file_id=student.source_file,
        )

        existing_by_id = {
            course.id: course
            for course in existing_final_courses
            if getattr(course, "id", None) is not None
        }

        for course in incoming_courses:
            course_id = course.get("id")

            course_name = str(
                course.get("name") or course.get("course_name") or ""
            ).strip()
            course_grade = str(course.get("grade") or "").strip()
            credits = _to_float(
                _first_non_empty(
                    course.get("credits"),
                    course.get("credits_completed"),
                    course.get("credit_completed"),
                )
            )

            if not course_name and not course_grade and credits is None:
                continue

            if course_id and int(course_id) in existing_by_id:
                target = existing_by_id[int(course_id)]

                if _payload_is_remove_action(course):
                    await _remove_final_course_row(
                        session,
                        final_course=target,
                        CourseExtractionMatches=CourseExtractionMatches,
                    )
                    continue

                values = _course_values_for_final_table(
                    model_cls=FinalCourseDetails,
                    student=student,
                    file_id=student.source_file,
                    payload=course,
                )

                _apply_model_values(target, values, skip_created_at=True, skip_none=True)

                _set_if_has(
                    target,
                    "needs_review",
                    bool(course.get("needs_review", False)),
                )
                _set_if_has(target, "review_reason", course.get("review_reason"))
                _set_if_has(
                    target,
                    "review_status",
                    _normalize_review_status(
                        course.get("review_status"),
                        needs_review=bool(course.get("needs_review", False)),
                    ),
                )
                _set_if_has(
                    target,
                    "resolution_reason",
                    course.get("resolution_reason")
                    or course.get("resolution")
                    or "Reviewed by user",
                )
                _set_if_has(target, "updated_at", _now())

            elif not course_id:
                values = _course_values_for_final_table(
                    model_cls=FinalCourseDetails,
                    student=student,
                    file_id=student.source_file,
                    payload=course,
                )
                session.add(FinalCourseDetails(**values))

    await session.flush()

    source_file = None

    if student.source_file:
        source_file = (
            await session.execute(
                select(models.ExtractionFileDetails).where(
                    models.ExtractionFileDetails.id == student.source_file
                )
            )
        ).scalar_one_or_none()

        await _refresh_file_status_from_final_courses(session, student.source_file)

    await session.commit()

    final_courses = await _final_rows_for_student(
        session,
        student_db_id=student.id,
        file_id=student.source_file,
    )

    summary = (
        await _build_reconciliation_summary(session, student.source_file)
        if student.source_file
        else {}
    )

    match_lookup = (
        await _match_lookup_by_final_course_id(session, student.source_file)
        if student.source_file
        else {}
    )

    return _serialize_student(
        student,
        final_courses,
        source_file,
        summary,
        match_lookup,
    )


@router.post("/final-courses/{course_id}/review")
async def update_final_course_review(
    course_id: int,
    payload: dict,
    light: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    if _decode_new_record_id(course_id) is not None:
        return await _update_new_transcript_course_review(
            session=session,
            encoded_course_id=course_id,
            payload=payload,
            light=light,
        )

    FinalCourseDetails = _final_course_model()
    CourseExtractionMatches = _match_model()

    final_course = (
        await session.execute(
            select(FinalCourseDetails).where(FinalCourseDetails.id == course_id)
        )
    ).scalar_one_or_none()

    if not final_course:
        raise HTTPException(status_code=404, detail="Final course not found")

    file_id = _get_attr(final_course, "source_file", "extraction_file_id")
    student_db_id = _get_attr(final_course, "s_id", "student_id")

    if not file_id:
        raise HTTPException(status_code=400, detail="Final course has no source file")

    student = None

    if student_db_id:
        student = (
            await session.execute(
                select(models.Students).where(models.Students.id == int(student_db_id))
            )
        ).scalar_one_or_none()

    if not student:
        student = (
            await session.execute(
                select(models.Students)
                .where(models.Students.source_file == int(file_id))
                .order_by(models.Students.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Student not found for final course")

    if _payload_is_remove_action(payload):
        removed_file_id, removed_student_db_id, _ = await _remove_final_course_row(
            session,
            final_course=final_course,
            CourseExtractionMatches=CourseExtractionMatches,
        )

        process_status = await _refresh_file_status_from_final_courses(
            session,
            removed_file_id,
        )

        await session.commit()

        if light:
            return {
                "ok": True,
                "removed_course_id": course_id,
                "process_status": process_status,
            }

        source_file = (
            await session.execute(
                select(models.ExtractionFileDetails).where(
                    models.ExtractionFileDetails.id == removed_file_id
                )
            )
        ).scalar_one_or_none()

        final_courses = await _final_rows_for_student(
            session,
            student_db_id=removed_student_db_id or student.id,
            file_id=removed_file_id,
        )

        summary = await _build_reconciliation_summary(session, removed_file_id)
        match_lookup = await _match_lookup_by_final_course_id(
            session,
            removed_file_id,
        )

        response = _serialize_student(
            student,
            final_courses,
            source_file,
            summary,
            match_lookup,
        )
        response["ok"] = True
        response["removed_course_id"] = course_id
        response["process_status"] = process_status

        return response

    if _payload_has_course_update_fields(payload):
        values = _course_values_for_final_table(
            model_cls=FinalCourseDetails,
            student=student,
            file_id=int(file_id),
            payload=payload,
        )

        _apply_model_values(final_course, values, skip_created_at=True, skip_none=True)

    if "final_source" in payload or "source" in payload or "extraction_source" in payload:
        final_source = _normalize_final_source(
            _first_non_empty(
                payload.get("final_source"),
                payload.get("source"),
                payload.get("extraction_source"),
                _get_attr(final_course, "final_source"),
            )
        )
        _set_if_has(final_course, "final_source", final_source)

    if "needs_review" in payload:
        _set_if_has(final_course, "needs_review", bool(payload.get("needs_review")))

    if "review_status" in payload or "needs_review" in payload:
        _set_if_has(
            final_course,
            "review_status",
            _normalize_review_status(
                payload.get("review_status"),
                needs_review=bool(payload.get("needs_review", False)),
            ),
        )

    if "review_reason" in payload:
        _set_if_has(final_course, "review_reason", payload.get("review_reason"))

    should_mark_reviewed = bool(
        payload.get("mark_reviewed") is True
        or payload.get("reviewed_by_user") is True
        or _is_resolved_review_status(payload.get("review_status"))
        or _normalize_action(payload.get("resolution")) in {"accept_final", "reviewed", "keep"}
        or _normalize_action(payload.get("action")) in {"review", "accept_final", "keep"}
    )

    if should_mark_reviewed:
        _set_if_has(final_course, "needs_review", False)
        _set_if_has(final_course, "review_reason", None)
        _set_if_has(final_course, "review_status", "auto_resolved")
        _set_if_has(
            final_course,
            "resolution_reason",
            payload.get("resolution_reason") or "Reviewed by user",
        )
        _set_if_has(
            final_course,
            "final_source",
            _normalize_final_source(_get_attr(final_course, "final_source")),
        )

    _set_if_has(final_course, "updated_at", _now())

    linked_matches = await _find_match_rows_for_final_course(
        session,
        CourseExtractionMatches=CourseExtractionMatches,
        final_course=final_course,
    )

    if should_mark_reviewed:
        for match_row in linked_matches:
            _mark_match_resolved(
                match_row,
                resolution_reason=(
                    payload.get("resolution_reason")
                    or payload.get("resolution")
                    or "Accepted final course by user"
                ),
            )

    await session.flush()

    process_status = await _refresh_file_status_from_final_courses(
        session,
        int(file_id),
    )

    await session.commit()

    # light=true skips only the large response rebuild. The authoritative file
    # status has already been refreshed above.
    if light:
        return {"ok": True, "process_status": process_status}

    source_file = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == int(file_id)
            )
        )
    ).scalar_one_or_none()

    final_courses = await _final_rows_for_student(
        session,
        student_db_id=student.id,
        file_id=int(file_id),
    )

    summary = await _build_reconciliation_summary(session, int(file_id))
    match_lookup = await _match_lookup_by_final_course_id(session, int(file_id))

    response = _serialize_student(
        student,
        final_courses,
        source_file,
        summary,
        match_lookup,
    )
    response["ok"] = True
    response["process_status"] = process_status

    return response


@router.post("/course-extraction-matches/{match_id}/resolve")
async def resolve_course_extraction_match(
    match_id: int,
    payload: dict | None = None,
    light: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    payload = payload or {}

    CourseExtractionMatches = _match_model()
    FinalCourseDetails = _final_course_model()

    match_row = (
        await session.execute(
            select(CourseExtractionMatches).where(
                CourseExtractionMatches.id == match_id
            )
        )
    ).scalar_one_or_none()

    if not match_row:
        raise HTTPException(status_code=404, detail="Course extraction match not found")

    file_id = _get_attr(match_row, "source_file", "extraction_file_id")

    if not file_id:
        raise HTTPException(status_code=400, detail="Match row has no source file")

    final_course_id = _first_non_empty(
        payload.get("final_course_id"),
        payload.get("final_course_detail_id"),
        _get_attr(match_row, "final_course_detail_id"),
    )

    final_course = None

    if final_course_id:
        final_course = (
            await session.execute(
                select(FinalCourseDetails).where(
                    FinalCourseDetails.id == int(final_course_id)
                )
            )
        ).scalar_one_or_none()

    if _payload_is_remove_action(payload):
        _mark_match_removed(match_row)

        removed_final_course_id = None

        if final_course is not None:
            removed_final_course_id = getattr(final_course, "id", None)

            await _remove_final_course_row(
                session,
                final_course=final_course,
                CourseExtractionMatches=CourseExtractionMatches,
            )

        await session.flush()

        process_status = await _refresh_file_status_from_final_courses(
            session,
            int(file_id),
        )

        await session.commit()

        if light:
            return {
                "ok": True,
                "match_id": match_id,
                "file_id": int(file_id),
                "process_status": process_status,
            }

        return {
            "ok": True,
            "match_id": match_id,
            "file_id": int(file_id),
            "removed_final_course_id": removed_final_course_id,
            "process_status": process_status,
        }

    _mark_match_resolved(
        match_row,
        resolution_reason=(
            payload.get("resolution_reason")
            or payload.get("resolution")
            or "Resolved by user"
        ),
    )

    if final_course is not None:
        final_course_payload = payload.get("final_course")

        if isinstance(final_course_payload, dict) and _payload_has_course_update_fields(
            final_course_payload
        ):
            student_db_id = _get_attr(final_course, "s_id", "student_id")
            student = None

            if student_db_id:
                student = (
                    await session.execute(
                        select(models.Students).where(
                            models.Students.id == int(student_db_id)
                        )
                    )
                ).scalar_one_or_none()

            if student:
                values = _course_values_for_final_table(
                    model_cls=FinalCourseDetails,
                    student=student,
                    file_id=int(file_id),
                    payload=final_course_payload,
                )
                _apply_model_values(
                    final_course,
                    values,
                    skip_created_at=True,
                    skip_none=True,
                )

        if "final_source" in payload or "source" in payload or "extraction_source" in payload:
            _set_if_has(
                final_course,
                "final_source",
                _normalize_final_source(
                    _first_non_empty(
                        payload.get("final_source"),
                        payload.get("source"),
                        payload.get("extraction_source"),
                        _get_attr(final_course, "final_source"),
                    )
                ),
            )

        _set_if_has(final_course, "needs_review", False)
        _set_if_has(final_course, "review_reason", None)
        _set_if_has(final_course, "review_status", "auto_resolved")
        _set_if_has(
            final_course,
            "resolution_reason",
            payload.get("resolution_reason") or "Resolved by user",
        )
        _set_if_has(
            final_course,
            "final_source",
            _normalize_final_source(_get_attr(final_course, "final_source")),
        )
        _set_if_has(final_course, "updated_at", _now())

    await session.flush()

    process_status = await _refresh_file_status_from_final_courses(
        session,
        int(file_id),
    )

    await session.commit()

    if light:
        return {
            "ok": True,
            "match_id": match_id,
            "file_id": int(file_id),
            "process_status": process_status,
        }

    return {
        "ok": True,
        "match_id": match_id,
        "file_id": int(file_id),
        "process_status": process_status,
    }



@router.get("/files/{file_id}/matches")
async def list_course_extraction_matches_for_file(
    file_id: int,
    session: AsyncSession = Depends(get_session),
):
    source_file = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == file_id
            )
        )
    ).scalar_one_or_none()

    if not source_file:
        raise HTTPException(status_code=404, detail="File not found")

    if await _is_new_transcript_file(session, file_id):
        summary = await _build_summary_for_file(session, source_file)
        return {
            "file_id": file_id,
            "summary": summary,
            "matches": [],
            "is_new_transcript_type": True,
        }

    matches = await _load_matches_for_file(session, file_id)
    summary = await _build_reconciliation_summary(session, file_id)

    return {
        "file_id": file_id,
        "summary": summary,
        "matches": [_serialize_match(row) for row in matches],
    }

@router.post("/files/{file_id}/complete")
async def complete_file_if_ready(
    file_id: int,
    session: AsyncSession = Depends(get_session),
):
    source_file = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == file_id
            )
        )
    ).scalar_one_or_none()

    if not source_file:
        raise HTTPException(status_code=404, detail="File not found")

    if await _is_new_transcript_file(session, file_id):
        # Load the isolated rows once, validate once, and build the response from
        # those same objects. The old flow loaded the same courses again after
        # committing, which made Move to Auto Complete noticeably slow.
        students, courses = await _new_transcript_rows_for_file(session, file_id)

        incomplete_course_issues: list[tuple[Any, list[str]]] = []
        for course in courses:
            missing_fields = _new_course_missing_required_fields(course)
            if missing_fields:
                incomplete_course_issues.append((course, missing_fields))
                if hasattr(course, "reviewed_by_user"):
                    course.reviewed_by_user = False

        # Persist the invariant repair before final status calculation so an
        # incomplete row can never remain reviewed=true in the database.
        await session.flush()

        process_status = await _refresh_new_transcript_file_status(
            session,
            file_id,
            allow_complete=True,
            source_file=source_file,
            students=students,
            courses=courses,
        )

        summary = _build_new_transcript_summary_from_rows(
            source_file=source_file,
            students=students,
            courses=courses,
        )

        await session.commit()

        if process_status != "completed":
            if not students:
                message = (
                    "Student details are missing. Please review the transcript "
                    "before moving it to Auto Complete."
                )
            elif not courses:
                message = (
                    "No course rows are available yet. Add or extract the courses "
                    "before moving this transcript to Auto Complete."
                )
            elif incomplete_course_issues:
                first_course, first_missing = incomplete_course_issues[0]
                first_name = str(
                    _get_attr(
                        first_course,
                        "crs_description",
                        "course_name",
                        "name",
                    )
                    or "The first incomplete course"
                ).strip()
                missing_text = _format_new_course_missing_fields(first_missing)
                count = len(incomplete_course_issues)
                message = (
                    f"{count} course row{'s' if count != 1 else ''} still "
                    "need information before they can be reviewed. "
                    f"{first_name} needs {missing_text}."
                )
            else:
                unreviewed_count = sum(
                    1
                    for course in courses
                    if not bool(getattr(course, "reviewed_by_user", False))
                )
                message = (
                    f"{unreviewed_count} course row"
                    f"{'s' if unreviewed_count != 1 else ''} still need review. "
                    "Mark each complete course as reviewed before moving this "
                    "transcript to Auto Complete."
                )

            raise HTTPException(
                status_code=400,
                detail={
                    "message": message,
                    "process_status": process_status,
                    "incomplete_course_count": len(incomplete_course_issues),
                    "unreviewed_course_count": int(
                        summary.get("unreviewed_course_count", 0) or 0
                    ),
                },
            )

        return {
            "ok": True,
            "file_id": file_id,
            "process_status": process_status,
            "summary": summary,
            "is_new_transcript_type": True,
        }

    process_status = await _refresh_file_status_from_final_courses(session, file_id)
    await session.commit()

    summary = await _build_reconciliation_summary(session, file_id)

    if process_status != "completed":
        raise HTTPException(
            status_code=400,
            detail={
                "message": "File still has unresolved or incomplete final rows.",
                "process_status": process_status,
                "summary": summary,
            },
        )

    return {
        "ok": True,
        "file_id": file_id,
        "process_status": process_status,
        "summary": summary,
    }


@router.get("/files/{file_id}/pdf")
async def fetch_file_pdf(
    file_id: int,
    session: AsyncSession = Depends(get_session),
):
    extraction_row = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == file_id
            )
        )
    ).scalar_one_or_none()

    if not extraction_row:
        raise HTTPException(status_code=404, detail="File not found")

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    bucket = storage.client.bucket(bucket_name)

    raw_file_name = str(extraction_row.file_name or "").replace("\\", "/").lstrip("/")
    base_file_name = PurePosixPath(raw_file_name).name

    if not base_file_name:
        raise HTTPException(status_code=404, detail="PDF file name is missing")

    upload_prefix = storage.build_upload_prefix(
        extraction_row.year_intake or "default-term",
        None,
        None,
    ).rstrip("/") + "/"
    classified_prefix = storage.build_classified_upload_prefix(
        extraction_row.year_intake or "default-term",
        None,
    ).rstrip("/") + "/"

    blob = None

    # Fastest path for repeated Review opens.
    cached_blob_name = _PDF_BLOB_NAME_CACHE.get(file_id)
    if cached_blob_name:
        cached_blob = bucket.blob(cached_blob_name)
        try:
            cached_exists = await asyncio.to_thread(cached_blob.exists)
        except Exception:
            cached_exists = False

        if cached_exists:
            blob = cached_blob
        else:
            _PDF_BLOB_NAME_CACHE.pop(file_id, None)

    # Fast exact-path candidates before any list_blobs scan.
    if blob is None:
        exact_candidates: list[str] = []

        # If the DB already carries an object path, use it directly.
        if "/" in raw_file_name:
            exact_candidates.append(raw_file_name)

        # Audit files are normally classified under Others.
        if str(extraction_row.process_status or "").lower().strip() == "needs_review_audit":
            exact_candidates.append(
                f"{classified_prefix}Others/{base_file_name}"
            )

        exact_candidates.extend(
            [
                f"{classified_prefix}{base_file_name}",
                f"{upload_prefix}{base_file_name}",
            ]
        )

        seen_candidates: set[str] = set()
        for candidate_name in exact_candidates:
            if not candidate_name or candidate_name in seen_candidates:
                continue
            seen_candidates.add(candidate_name)

            candidate_blob = bucket.blob(candidate_name)
            try:
                exists = await asyncio.to_thread(candidate_blob.exists)
            except Exception:
                exists = False

            if exists:
                blob = candidate_blob
                break

    # Target the most likely folders first. This is much cheaper than scanning
    # every object in the bucket for each Review click.
    if blob is None:
        search_prefixes = [
            f"{classified_prefix}Others/Grouped_by_school/",
            f"{classified_prefix}Others/",
            classified_prefix,
            upload_prefix,
        ]

        for prefix in search_prefixes:
            candidates = await asyncio.to_thread(
                lambda p=prefix: list(bucket.list_blobs(prefix=p))
            )

            for candidate_blob in candidates:
                candidate_name = str(candidate_blob.name or "")
                if (
                    candidate_name == raw_file_name
                    or candidate_name == base_file_name
                    or candidate_name.endswith(f"/{base_file_name}")
                ):
                    blob = candidate_blob
                    break

            if blob is not None:
                break

    # Last-resort compatibility fallback for older/atypical storage paths.
    if blob is None:
        candidates = await asyncio.to_thread(lambda: list(bucket.list_blobs()))

        for candidate_blob in candidates:
            candidate_name = str(candidate_blob.name or "")
            if (
                candidate_name == raw_file_name
                or candidate_name == base_file_name
                or candidate_name.endswith(f"/{base_file_name}")
            ):
                blob = candidate_blob
                break

    if blob is None:
        raise HTTPException(status_code=404, detail="PDF blob not found in storage")

    _PDF_BLOB_NAME_CACHE[file_id] = blob.name

    data = await asyncio.to_thread(blob.download_as_bytes)

    safe_name = base_file_name.replace('"', "")
    return StreamingResponse(
        iter([data]),
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{safe_name}"',
        },
    )

@router.get("/not-processed")
async def list_not_processed(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
):
    # Same predicate as the /section-counts badge (see _not_processed_conditions)
    # so the "Human Review with Audit" count and this list always agree: any row
    # that isn't completed / needs_review / processing / new_type, whose
    # transcript isn't already handled under a processed twin.
    stmt = (
        select(models.ExtractionFileDetails)
        .where(*_not_processed_conditions(models.ExtractionFileDetails))
        .order_by(models.ExtractionFileDetails.upload_date.desc())
    )

    if year_intake:
        stmt = stmt.where(models.ExtractionFileDetails.year_intake == year_intake)

    rows = (await session.execute(stmt)).scalars().all()

    # Not-processed rows have no extracted courses, so building a reconciliation
    # summary per row is pure waste (an N+1 that made this page slow). The
    # backlog list only needs the file's identity/status.
    empty_summary: dict = {}
    return [
        {
            "id": row.id,
            "file_name": row.file_name,
            "process_status": row.process_status,
            "upload_date": row.upload_date,
            "institution_id": row.institution_id,
            "year_intake": row.year_intake,
            "program_id": row.program_id,
            "classifier_type": row.classifier_type,
            "validation_result": empty_summary,
            "course_validation": empty_summary,
            "course_reconciliation": empty_summary,
            "reconciliation_summary": empty_summary,
            "validation_status": row.process_status,
            "validation_type": "course_reconciliation",
            "validation_result_id": None,
        }
        for row in rows
    ]


@router.post("/cleanup-orphaned-uploaded")
async def cleanup_orphaned_uploaded(
    session: AsyncSession = Depends(get_session),
    term: str | None = Query(None, alias="term"),
    dry_run: bool = Query(True),
):
    """Remove 'uploaded' extraction_file_details rows whose source PDF no longer
    exists in GCS.

    When a transcript file is deleted, the GCS blob is removed but the
    extraction_file_details row can be left behind at status 'uploaded'. Those
    orphans have no PDF and no extracted content, yet the "Not Processed" badge
    counts them forever. This purges only those orphans:

      - ONLY rows with process_status == 'uploaded' are ever considered
        (completed / needs_review are never touched).
      - A row is deleted only when NO blob in the bucket matches its file_name,
        i.e. the PDF is genuinely gone. Rows whose PDF still exists (real pending
        files awaiting extraction) are left alone.

    dry_run=True (default) reports what WOULD be deleted without deleting.
    """
    stmt = select(models.ExtractionFileDetails).where(
        models.ExtractionFileDetails.process_status == "uploaded"
    )
    if term:
        stmt = stmt.where(models.ExtractionFileDetails.year_intake == term)
    rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return {
            "term": term,
            "dry_run": dry_run,
            "checked_uploaded": 0,
            "orphaned_missing_pdf": 0,
            "still_pending_with_pdf": 0,
            "deleted": 0,
            "orphaned": [],
        }

    # One full-bucket listing (cheap vs. per-row listing) to test existence.
    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    bucket = storage.client.bucket(bucket_name)
    blob_names = await asyncio.to_thread(
        lambda: [b.name for b in bucket.list_blobs()]
    )

    def blob_exists(file_name: str | None) -> bool:
        if not file_name:
            return False
        suffix = f"/{file_name}"
        for name in blob_names:
            if name == file_name or name.endswith(suffix):
                return True
        return False

    orphaned = [r for r in rows if not blob_exists(r.file_name)]
    orphaned_ids = [r.id for r in orphaned]

    deleted = 0
    if not dry_run and orphaned_ids:
        # Re-assert status in the DELETE so a row that just started processing
        # in a concurrent request is never removed. Children cascade (FK
        # ondelete=CASCADE), but orphans carry no extracted courses.
        await session.execute(
            delete(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id.in_(orphaned_ids),
                models.ExtractionFileDetails.process_status == "uploaded",
            )
        )
        await session.commit()
        deleted = len(orphaned_ids)

    return {
        "term": term,
        "dry_run": dry_run,
        "checked_uploaded": len(rows),
        "orphaned_missing_pdf": len(orphaned),
        "still_pending_with_pdf": len(rows) - len(orphaned),
        "deleted": deleted,
        "orphaned": [
            {"id": r.id, "term": r.year_intake, "file_name": r.file_name}
            for r in orphaned
        ],
    }


@router.post("/reset-unknown-schools-to-new-type")
async def reset_unknown_schools_to_new_type(
    session: AsyncSession = Depends(get_session),
    term: str | None = Query(None, alias="term"),
    dry_run: bool = Query(True),
):
    """Reset files whose school has no trained extractor (classifier -> 'others')
    back to 'new_type', undoing extractions that happened before the gate.

    These were extracted with the wrong fallback processor and dumped into Needs
    Review; they belong in New Transcript Type until an extractor is built. Only
    rows NOT completed are touched. dry_run=True (default) reports first.
    """
    from app.routers.cloud_folder_locations import _detect_classifier_name

    F = models.ExtractionFileDetails
    stmt = select(F).where(
        F.process_status.notin_(
            (
                "completed",
                "new_type",
                "needs_review_audit",
                "processing",
            )
        )
    )
    if term:
        stmt = stmt.where(F.year_intake == term)
    rows = (await session.execute(stmt)).scalars().all()

    NewTranscriptStudents = _new_transcript_student_model()
    NewTranscriptCourseDetails = _new_transcript_course_model()

    isolated_student_file_ids = {
        int(file_id)
        for file_id in (
            await session.execute(
                select(NewTranscriptStudents.source_file)
            )
        ).scalars().all()
        if file_id is not None
    }
    isolated_course_file_ids = {
        int(file_id)
        for file_id in (
            await session.execute(
                select(NewTranscriptCourseDetails.source_file)
            )
        ).scalars().all()
        if file_id is not None
    }
    isolated_file_ids = (
        isolated_student_file_ids | isolated_course_file_ids
    )

    targets = [
        r for r in rows
        if (
            int(r.id) not in isolated_file_ids
            and _detect_classifier_name(r.file_name, r.file_name) == "others"
        )
    ]
    ids = [r.id for r in targets]

    reset = 0
    if not dry_run and ids:
        await session.execute(
            update(F).where(F.id.in_(ids)).values(process_status="new_type")
        )
        await session.commit()
        reset = len(ids)

    return {
        "term": term,
        "dry_run": dry_run,
        "unknown_school_rows": len(targets),
        "reset": reset,
        "files": [
            {"id": r.id, "term": r.year_intake, "status": r.process_status, "file_name": r.file_name}
            for r in targets
        ],
    }


@router.post("/cleanup-duplicate-uploaded")
async def cleanup_duplicate_uploaded(
    session: AsyncSession = Depends(get_session),
    term: str | None = Query(None, alias="term"),
    dry_run: bool = Query(True),
):
    """Remove 'uploaded' rows that duplicate an already-processed transcript.

    Double ingestion (raw upload path + processed copy path) leaves the upload
    row at status 'uploaded' while its twin is completed/needs_review — so the
    same transcript shows in both Completed and Not Processed. This deletes the
    redundant 'uploaded' row ONLY when a completed/needs_review twin exists for
    the same term + file base name (the twin holds all the extracted data, so
    nothing is lost). dry_run=True (default) reports without deleting.
    """
    F = models.ExtractionFileDetails
    stmt = select(F).where(
        F.process_status == "uploaded",
        _processed_twin_exists(F),
    )
    if term:
        stmt = stmt.where(F.year_intake == term)
    rows = (await session.execute(stmt)).scalars().all()
    dup_ids = [r.id for r in rows]

    deleted = 0
    if not dry_run and dup_ids:
        await session.execute(
            delete(F).where(F.id.in_(dup_ids), F.process_status == "uploaded")
        )
        await session.commit()
        deleted = len(dup_ids)

    return {
        "term": term,
        "dry_run": dry_run,
        "duplicate_uploaded": len(rows),
        "deleted": deleted,
        "duplicates": [
            {"id": r.id, "term": r.year_intake, "file_name": r.file_name}
            for r in rows
        ],
    }


@router.post("/reconcile/re-evaluate")
async def re_evaluate_reconciliation(
    session: AsyncSession = Depends(get_session),
    year_intake: str | None = Query(None, alias="term"),
):
    """Re-run reconciliation on already-extracted needs_review files using the
    stored Document AI + Gemini rows — NO new extraction or API calls. Applies
    the current reconciliation rules so files whose only issues were soft (e.g.
    credit_attempted / school_name / a format-absent grade level) move to
    completed. Genuine conflicts (grade, course_id, count shortfall) stay."""
    from app.services.course_reconciliation_service import CourseReconciliationService
    from app.services.persistence_service import PersistenceService

    stmt = (
        select(models.Students, models.ExtractionFileDetails)
        .join(
            models.ExtractionFileDetails,
            models.Students.source_file == models.ExtractionFileDetails.id,
        )
        .where(models.ExtractionFileDetails.process_status == "needs_review")
    )
    if year_intake:
        stmt = stmt.where(models.ExtractionFileDetails.year_intake == year_intake)

    rows = (await session.execute(stmt)).all()

    svc = CourseReconciliationService(session)
    persistence = PersistenceService(session)
    moved_to_completed = 0
    still_needs_review = 0
    errors = 0

    for student, ef in rows:
        try:
            result = await svc.reconcile_file(
                extraction_file_id=int(ef.id),
                student_db_id=int(student.id),
            )
            new_status = (
                result.get("file_status")
                or result.get("process_status")
                or "needs_review"
            )
            await persistence.mark_file_status(int(ef.id), new_status)
            await session.commit()
            if new_status == "completed":
                moved_to_completed += 1
            else:
                still_needs_review += 1
        except Exception:
            await session.rollback()
            errors += 1

    return {
        "reevaluated": len(rows),
        "moved_to_completed": moved_to_completed,
        "still_needs_review": still_needs_review,
        "errors": errors,
    }


@router.post("/files/{file_id}/rerun")
async def rerun_file_extraction(
    file_id: int,
    session: AsyncSession = Depends(get_session),
):
    extraction_row = (
        await session.execute(
            select(models.ExtractionFileDetails).where(
                models.ExtractionFileDetails.id == file_id
            )
        )
    ).scalar_one_or_none()

    if not extraction_row:
        raise HTTPException(status_code=404, detail="File not found")

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    bucket = storage.client.bucket(bucket_name)

    blob = None

    search_prefixes = [
        storage.build_classified_upload_prefix(
            extraction_row.year_intake or "default-term",
            None,
        ),
        storage.build_upload_prefix(
            extraction_row.year_intake or "default-term",
            None,
            None,
        ),
    ]

    for prefix in search_prefixes:
        blobs = await asyncio.to_thread(
            lambda p=prefix: list(bucket.list_blobs(prefix=p))
        )

        for candidate_blob in blobs:
            if (
                candidate_blob.name.endswith(f"/{extraction_row.file_name}")
                or candidate_blob.name == extraction_row.file_name
            ):
                blob = candidate_blob
                break

        if blob:
            break

    if blob is None:
        blobs = await asyncio.to_thread(lambda: list(bucket.list_blobs()))

        for candidate_blob in blobs:
            if (
                candidate_blob.name.endswith(f"/{extraction_row.file_name}")
                or candidate_blob.name == extraction_row.file_name
            ):
                blob = candidate_blob
                break

    if blob is None:
        raise HTTPException(status_code=404, detail="PDF not found in storage")

    content = await asyncio.to_thread(blob.download_as_bytes)
    gcs_uri = f"gs://{bucket_name}/{blob.name}"
    normalized_blob_path = "/" + str(blob.name or "").replace("\\", "/").strip("/").lower()
    is_grouped_new_transcript = (
        "/transcript/others/grouped_by_school/" in normalized_blob_path
    )

    GeminiCourseDetails = _gemini_course_model()
    CourseExtractionMatches = _match_model()
    FinalCourseDetails = _final_course_model()

    await _null_out_cross_table_links(
        session,
        file_id=file_id,
        FinalCourseDetails=FinalCourseDetails,
        CourseExtractionMatches=CourseExtractionMatches,
    )

    await session.execute(
        delete(FinalCourseDetails).where(
            _file_column(FinalCourseDetails) == file_id
        )
    )

    await session.execute(
        delete(CourseExtractionMatches).where(
            _file_column(CourseExtractionMatches) == file_id
        )
    )

    await session.execute(
        delete(GeminiCourseDetails).where(
            _file_column(GeminiCourseDetails) == file_id
        )
    )

    await session.execute(
        delete(models.Course_details).where(
            models.Course_details.source_file == file_id
        )
    )

    await session.execute(
        delete(models.Students).where(
            models.Students.source_file == file_id
        )
    )

    # Also clear the isolated Gemini-only new transcript tables. This is safe
    # for known transcript files because the delete predicates are file-scoped.
    NewTranscriptCourseDetails = _new_transcript_course_model()
    NewTranscriptStudents = _new_transcript_student_model()

    await session.execute(
        delete(NewTranscriptCourseDetails).where(
            NewTranscriptCourseDetails.source_file == file_id
        )
    )
    await session.execute(
        delete(NewTranscriptStudents).where(
            NewTranscriptStudents.source_file == file_id
        )
    )

    await session.commit()

    from app.routers.cloud_folder_locations import (
        _detect_classifier_name,
        _select_processor_id,
    )

    gcs_path = blob.name if blob else extraction_row.file_name
    classifier_name = _detect_classifier_name(extraction_row.file_name, gcs_path)

    # Grouped Others transcripts use the isolated Gemini-only rerun below.
    # For every other path, trust the same path-aware classifier decision used
    # by the latest main branch so known district transcripts are not
    # incorrectly routed to New Transcript Type.
    if not is_grouped_new_transcript and classifier_name == "others":
        await session.execute(
            update(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == file_id)
            .values(process_status="new_type")
        )
        await session.commit()
        return {
            "ok": True,
            "file_id": file_id,
            "process_status": "new_type",
            "reason": "no_extractor_awaiting_new_type_setup",
            "message": "This school has no extractor yet; routed to New Transcript Type.",
        }

    if is_grouped_new_transcript:
        await session.execute(
            update(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == file_id)
            .values(process_status="processing")
        )
        await session.commit()

        try:
            from app.services.new_transcript_type_extraction_service import (
                NewTranscriptTypeExtractionService,
            )

            transcript_group = PurePosixPath(blob.name).parent.name
            result = await NewTranscriptTypeExtractionService().process_gemini_only_transcript(
                session=session,
                extraction_file=extraction_row,
                gcs_uri=gcs_uri,
                institution_id=extraction_row.institution_id or 0,
                classifier_name=transcript_group,
            )

            return {
                "ok": True,
                "file_id": file_id,
                "students": result.get("students", 0),
                "courses": result.get("courses", 0),
                "final_courses": result.get("courses", 0),
                "process_status": result.get("process_status"),
                "mode": result.get("mode"),
                "review_bucket": result.get("review_bucket"),
                "unresolved_courses": result.get("unresolved_courses", 0),
                "is_new_transcript_type": True,
            }
        except Exception as exc:
            await session.execute(
                update(models.ExtractionFileDetails)
                .where(models.ExtractionFileDetails.id == file_id)
                .values(process_status="failed")
            )
            await session.commit()
            raise HTTPException(status_code=500, detail=str(exc))

    processor_id = _select_processor_id(extraction_row.file_name, gcs_path)

    if extraction_row.classifier_type:
        classifier_type = (
            await session.execute(
                select(models.ClassifiersType).where(
                    models.ClassifiersType.id == extraction_row.classifier_type
                )
            )
        ).scalar_one_or_none()

        if classifier_type and classifier_type.processor_id:
            processor_id = classifier_type.processor_id

            if classifier_type.classifier_name:
                classifier_name = classifier_type.classifier_name

    await session.execute(
        update(models.ExtractionFileDetails)
        .where(models.ExtractionFileDetails.id == file_id)
        .values(process_status="processing")
    )
    await session.commit()

    try:
        from app.services.transcript_processor import (
            ExtractionContext,
            TranscriptProcessor,
        )

        ctx = ExtractionContext(
            extraction_file_id=file_id,
            institution_id=extraction_row.institution_id or 0,
            classifier_type_id=extraction_row.classifier_type or 0,
            used_processor_id=processor_id,
            file_name=extraction_row.file_name,
            classifier_name=classifier_name,
        )

        processor = TranscriptProcessor()

        result = await processor.process_bytes_and_persist(
            session,
            ctx,
            content,
            gcs_uri=gcs_uri,
        )

        try:
            from app.services.uc_doorway_course_mapping_service import (
                schedule_mapping_for_file as _schedule_mapping,
            )

            _schedule_mapping(file_id)
        except Exception:
            pass

        return {
            "ok": True,
            "file_id": file_id,
            "students": result.get("students", 0),
            "courses": result.get("courses", 0),
            "final_courses": result.get("final_courses", result.get("courses", 0)),
            "process_status": result.get("process_status"),

            "document_ai_courses_inserted": result.get(
                "document_ai_courses_inserted"
            ),
            "gemini_courses_inserted": result.get("gemini_courses_inserted"),
            "raw_document_ai_course_count": result.get(
                "raw_document_ai_course_count"
            ),
            "raw_gemini_course_count": result.get("raw_gemini_course_count"),
            "course_reconciliation": result.get("course_reconciliation"),

            "course_validation": result.get("course_reconciliation"),
            "validation_save_result": result.get("course_reconciliation"),
        }

    except Exception as exc:
        await session.execute(
            update(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == file_id)
            .values(process_status="failed")
        )
        await session.commit()

        raise HTTPException(status_code=500, detail=str(exc))

# ---------------------------------------------------------------------------
# Per-student notes (shared across devices; table created lazily so no migration
# is needed).
# ---------------------------------------------------------------------------
_notes_table_ready = False


async def _ensure_notes_table(session: AsyncSession) -> None:
    global _notes_table_ready
    if _notes_table_ready:
        return
    from sqlalchemy import text as _t
    await session.execute(_t(
        "CREATE TABLE IF NOT EXISTS student_note_entries ("
        "id BIGSERIAL PRIMARY KEY, note_key TEXT NOT NULL, author TEXT, role TEXT, "
        "body TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now())"
    ))
    await session.execute(_t(
        "CREATE INDEX IF NOT EXISTS idx_student_note_entries_key "
        "ON student_note_entries (note_key)"
    ))
    await session.commit()
    _notes_table_ready = True


@router.get("/student-notes/{note_key}")
async def list_student_notes(note_key: str, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import text as _t
    await _ensure_notes_table(session)
    rows = (await session.execute(
        _t(
            "SELECT id, author, role, body, created_at FROM student_note_entries "
            "WHERE note_key = :k ORDER BY created_at DESC, id DESC"
        ),
        {"k": note_key},
    )).all()
    return {
        "notes": [
            {
                "id": r[0],
                "author": r[1] or "",
                "role": r[2] or "",
                "body": r[3] or "",
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]
    }


@router.post("/student-notes/{note_key}")
async def add_student_note(note_key: str, payload: dict, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import text as _t
    await _ensure_notes_table(session)
    body = str((payload or {}).get("body", "") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Note body is required")
    author = str((payload or {}).get("author", "") or "").strip() or "Staff"
    role = str((payload or {}).get("role", "") or "").strip()
    row = (await session.execute(
        _t(
            "INSERT INTO student_note_entries (note_key, author, role, body) "
            "VALUES (:k, :a, :r, :b) RETURNING id, created_at"
        ),
        {"k": note_key, "a": author, "r": role, "b": body},
    )).first()
    await session.commit()
    return {
        "id": row[0] if row else None,
        "author": author,
        "role": role,
        "body": body,
        "created_at": row[1].isoformat() if row and row[1] else None,
    }
