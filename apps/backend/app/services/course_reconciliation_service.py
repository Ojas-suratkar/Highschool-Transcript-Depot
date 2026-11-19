"""
Course reconciliation service.

Clean 4-table pipeline:

1. course_details = raw Document AI extracted course rows.
2. gemini_course_details = raw Gemini extracted course rows.
3. course_extraction_matches = row-by-row comparison decisions.
4. final_course_details = final trusted course rows used by frontend/admission.

Rules implemented here:
- Matching is order-independent. Row order is only a weak tie-breaker.
- Step 1 is course-count/row matching: match whatever Document AI and Gemini can safely match by course number/row identity.
- Step 2 is field reconciliation: for matched rows, compare all fields and pick trusted values field-by-field.
- Step 3 is count-owner source-only preservation: when both extractors have rows, keep matched rows plus source-only rows from the extractor with the larger raw course count.
- Final row count must not exceed both raw source counts; this prevents double-counting rows when matching coverage is low.
- When Document AI controls the course count, valid Document AI course ID/course name/grade values are kept for matched rows unless there is explicit proof to override them.
- Gemini-filled high-risk fields on matched rows are forced to Needs Review when row identity is not extremely safe or Gemini's course ID/name combination conflicts with other Gemini rows.
- Gemini-only rows can fill rows that Document AI missed when they are complete, high-confidence, believable, and not unsafe duplicates.
- Document-AI-only rows can also remain when Gemini missed them and the row is complete/believable.
- Doc-AI-only rescue: when Document AI has a bad/missing course ID or a wrong-column course name like 5.00/5.00 B, try to link it to an unmatched Gemini row before creating a source-only Needs Review row.
- Course names that look like credit/grade text, for example 5.00/5.00 B, are invalid and cannot complete unless Gemini supplies a safe matched course name.
- Mayfair term month repair: Fall=1, Spring=6, Summer/Summer School/Intersession=7 when term context is visible.
- Course name conflicts are auto-fixed from Gemini only when Gemini strongly proves a better value; otherwise valid Document AI course names are kept without Needs Review.
- Course ID verifier evidence is converted into a calculated proof score (verifier confidence × match-score component × row-identity component). Document AI wins by default unless calculated proof is strong enough.
- Plus/minus letter grade variants match by base grade and do not block completion: A/A-/A+, B/B-/B+, etc. The exact selected grade is still stored.
- Grade disagreements use the same calculated proof score, but valid Document AI grades win by default and do not block completion at 92.8% verifier/Gemini disagreement.
- Calculated proof thresholds for grade overwrite: below 98% keep Document AI and complete; 98%+ with extremely safe row identity can use verifier/Gemini.
- Focused Gemini grade-scan is used as evidence and can fill missing/invalid Document AI grades when confidence is high enough.
- Missing Document AI fields are auto-filled from Gemini only when Gemini has at least 92% confidence and row identity is safe.
- If Document AI has a usable value, Gemini must prove Document AI wrong through calculated proof/verifier evidence before overwriting.
- Month is optional when both extractors truly have no month/term context.
- For non-St. Anthony rows, Gemini month can be used/fill final month in backend; frontend hides month-only Gemini changes.
- Month is a row identity key: explicit Month 1 vs Month 6 rows must not match each other.
- Month mismatch is not a review reason and is not written as a user-facing field difference.
- If both sources miss month but the raw row context says a month/term field was expected, the row goes to Needs Review.
- Source-only rows are considered only from the course-count owner when both sources are present.
- Gemini-only rows may increase the final count when Gemini has more raw rows than Document AI.
- For Mayfair/LBUSD-style transcripts, Gemini-only rows are not auto-resolved unless deterministic PDF row geometry confirms the course ID, title, term, grade, and credits belong to the same visual row.
- Document-AI-only rows may remain when Document AI has at least as many raw rows as Gemini.
- Source-only rows go to Needs Review only when required fields are missing, values look invalid, confidence/evidence is weak, exact duplicates repeat, or a nearby conflicting row cannot be safely resolved.
- St. Anthony/Saint Anthony final rows use Document AI as primary, but matched Gemini rows are linked so validated rows show Document AI + Gemini.
- St. Anthony/Saint Anthony unmatched Gemini rows are kept and can auto-resolve when complete/high-confidence, so a course found only by Gemini is not lost.
- St. Anthony/Saint Anthony rows do not require course ID or month.
- St. Anthony/Saint Anthony grade-level conflicts are auto-resolved from Gemini/inferred year and do not block completion.
- St. Anthony/Saint Anthony credits are required; missing/invalid credits keep the row in Needs Review, but valid Document AI credits, including 0.0, are kept even when Gemini differs.
- Old validation tables are not used.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

try:
    from app.services.transcript_row_geometry import extract_transcript_row_geometry
except Exception:
    extract_transcript_row_geometry = None


MATCH_THRESHOLD = 0.58
LOW_MATCH_COVERAGE_THRESHOLD = 0.60
COURSE_ID_CONFLICT_NAME_AUTO_MATCH_THRESHOLD = 0.97
ROW_CONTEXT_AMBIGUITY_MARGIN = 0.08
GEMINI_AUTO_FILL_CONFIDENCE_THRESHOLD = 0.70
HIGH_CONFIDENCE_THRESHOLD = 0.70
BAD_SINGLE_COURSE_CREDIT_LIMIT = 15.0

# Gemini is a helper, not the judge. When Document AI has a valid value,
# keep Document AI unless Gemini has strong proof that Document AI is wrong.
DOC_AI_DEFAULT_KEEP_MATCH_THRESHOLD = 0.72
GEMINI_STRONG_PROOF_CONFIDENCE_THRESHOLD = 0.85
GEMINI_GRADE_REVIEW_CONFIDENCE_THRESHOLD = 0.85
GEMINI_GRADE_AUTO_OVERRIDE_CONFIDENCE_THRESHOLD = 0.99
GEMINI_GRADE_SCAN_STRONG_CONFIDENCE_THRESHOLD = GEMINI_GRADE_AUTO_OVERRIDE_CONFIDENCE_THRESHOLD
GEMINI_GRADE_SCAN_MATCH_SCORE_THRESHOLD = 8.0
COURSE_NAME_GEMINI_AUTO_FIX_SIMILARITY_THRESHOLD = 0.72
GRADE_CONFLICT_AUTO_RESOLVE_MATCH_THRESHOLD = DOC_AI_DEFAULT_KEEP_MATCH_THRESHOLD
# Grade verifier auto-overwrite is stricter than normal row matching.
# It requires the row identity to be extremely safe, because grades are high-risk.
GRADE_VERIFIER_EXTREME_ROW_MATCH_THRESHOLD = 0.92
# Course ID is high-risk like grade, but stricter. A valid Document AI
# course ID wins unless the focused course-ID verifier proves Gemini is correct
# at 100% confidence and the row identity is extremely safe. Any verifier proof
# below 100% that supports Gemini goes to Needs Review.
COURSE_ID_VERIFIER_REVIEW_CONFIDENCE_THRESHOLD = 0.0
COURSE_ID_VERIFIER_AUTO_OVERRIDE_CONFIDENCE_THRESHOLD = 1.0
COURSE_ID_VERIFIER_EXTREME_ROW_MATCH_THRESHOLD = 0.92

# Calculated proof is the actual decision score for risky grade/course-id
# conflicts. Gemini/verifier self-confidence alone is not enough.
#
# formula:
#   calculated_proof =
#       verifier_confidence
#       * verifier_match_score_component
#       * row_identity_component
#       * source_agreement_component
#
# This prevents a self-reported 100% verifier answer from overwriting a correct
# Document AI value when the verifier looked at the wrong row/column.
CALCULATED_PROOF_REVIEW_THRESHOLD = 0.85
CALCULATED_PROOF_AUTO_OVERRIDE_THRESHOLD = 0.98
CALCULATED_PROOF_MISSING_MATCH_SCORE_COMPONENT = 0.80
HIGH_RISK_GEMINI_FILL_MATCH_THRESHOLD = 0.92
GEMINI_MISSING_FIELD_AUTO_FILL_CONFIDENCE_THRESHOLD = 0.92
GEMINI_MISSING_FIELD_RESCUE_MATCH_THRESHOLD = 0.62

# Optional deterministic PDF text-geometry evidence.
# This is intentionally additive. If transcript_row_geometry.py is absent,
# the PDF path cannot be resolved, or the geometry parser returns no rows,
# reconciliation falls back to the existing matching and count-owner behavior.
TRANSCRIPT_GEOMETRY_MATCH_THRESHOLD = 0.78
TRANSCRIPT_GEOMETRY_STRONG_MATCH_THRESHOLD = 0.86
TRANSCRIPT_GEOMETRY_REPAIR_THRESHOLD = 0.86


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _gemini_confident(confidence: Any) -> bool:
    numeric_confidence = _coerce_float(confidence)
    return (
        numeric_confidence is not None
        and numeric_confidence >= GEMINI_AUTO_FILL_CONFIDENCE_THRESHOLD
    )


def _gemini_has_strong_proof(confidence: Any) -> bool:
    numeric_confidence = _coerce_float(confidence)
    return (
        numeric_confidence is not None
        and numeric_confidence >= GEMINI_STRONG_PROOF_CONFIDENCE_THRESHOLD
    )


def _raw_payload_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    if isinstance(payload, str):
        cleaned = payload.strip()

        if not cleaned:
            return {}

        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    return {}


def _grade_scan_confident(confidence: Any) -> bool:
    numeric_confidence = _coerce_float(confidence)
    return (
        numeric_confidence is not None
        and numeric_confidence >= GEMINI_GRADE_SCAN_STRONG_CONFIDENCE_THRESHOLD
    )


def _normalized_match_score_component(
    match_score: Any,
    *,
    missing_component: float = CALCULATED_PROOF_MISSING_MATCH_SCORE_COMPONENT,
) -> float:
    """
    Convert verifier match_score into a 0..1 multiplier.

    Gemini/verifier confidence is self-reported. A high confidence only becomes
    strong proof when the verifier also says it matched the exact visual row.
    If match_score is missing, use a conservative component so confidence=1.0
    cannot auto-overwrite by itself.
    """

    numeric_score = _coerce_float(match_score)

    if numeric_score is None:
        return missing_component

    if numeric_score > 1:
        numeric_score = numeric_score / 10.0

    return max(0.0, min(float(numeric_score), 1.0))


def _calculated_row_identity_component(
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    *,
    match_confidence: float | None,
) -> float:
    """
    Score how safe it is to treat Doc AI, Gemini, and verifier as the same row.

    Hard row-context mismatches intentionally reduce this score even if Gemini
    reports high confidence.
    """

    if doc_row is None or gemini_row is None:
        return 0.75

    base = _coerce_float(match_confidence)

    if base is None:
        base = _score_match(doc_row, gemini_row)

    base = max(0.0, min(float(base), 1.0))

    year_match = _same_int(doc_row.year, gemini_row.year)
    month_match = _same_int(doc_row.month, gemini_row.month)
    grade_level_match = _same_int(doc_row.grade_level, gemini_row.grade_level)
    course_id_match = _same_course_id(doc_row, gemini_row)

    attempted_match = _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
    completed_match = _same_credit(doc_row.credit_completed, gemini_row.credit_completed)
    credit_match = attempted_match is True or completed_match is True

    visual_alignment_safe = _visual_alignment_safely_links(doc_row, gemini_row)

    if year_match is False and not visual_alignment_safe:
        base = min(base, 0.45)

    if month_match is False and not visual_alignment_safe:
        base = min(base, 0.45)

    if grade_level_match is False and not visual_alignment_safe:
        base = min(base, 0.65)

    if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
        base = min(base, 0.65)

    if attempted_match is False and completed_match is False:
        base = min(base, 0.75)

    # For grade proof, a course-ID mismatch means the row identity is not
    # extremely safe. For course-ID proof this may be the field under review, so
    # it is a softer penalty.
    if (
        course_id_match is False
        and doc_row.course_number
        and gemini_row.course_number
        and doc_row.course_number != gemini_row.course_number
    ):
        base = min(base, 0.70)

    # Reward fully aligned context a little, but never above 1.
    if (
        year_match is not False
        and month_match is not False
        and grade_level_match is not False
        and _course_names_same_identity(doc_row.course_name, gemini_row.course_name)
        and credit_match
    ):
        base = max(base, 0.92)

    if visual_alignment_safe and _course_names_same_identity(doc_row.course_name, gemini_row.course_name) and credit_match:
        base = max(base, 0.92)

    return max(0.0, min(base, 1.0))



def _gemini_missing_field_confident(confidence: Any) -> bool:
    numeric_confidence = _coerce_float(confidence)
    return (
        numeric_confidence is not None
        and numeric_confidence >= GEMINI_MISSING_FIELD_AUTO_FILL_CONFIDENCE_THRESHOLD
    )


def _format_missing_field_confidence_requirement(confidence: Any) -> str:
    return (
        f"Gemini confidence is {_format_confidence_percent(confidence)}, below the "
        f"{round(GEMINI_MISSING_FIELD_AUTO_FILL_CONFIDENCE_THRESHOLD * 100)}% auto-fill threshold."
    )


def _gemini_confident_rescue_fill_is_safe(
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    *,
    match_confidence: float | None = None,
) -> bool:
    """
    Safe rescue rule for rows where Document AI missed or misplaced important
    fields, but Gemini extracted the same visible row with high confidence.

    This intentionally allows Gemini to repair Doc AI year/month/course ID when
    Doc AI attached the course to the wrong Mayfair/LBUSD term, as long as the
    row identity is still proven by stable fields such as course name, grade,
    credits, and grade level.
    """

    if doc_row is None or gemini_row is None:
        return False

    if not _gemini_missing_field_confident(gemini_row.confidence):
        return False

    if match_confidence is not None and match_confidence < GEMINI_MISSING_FIELD_RESCUE_MATCH_THRESHOLD:
        return False

    if gemini_row.course_name and _looks_like_wrong_column_course_name(gemini_row.course_name):
        return False

    if doc_row.course_name and not _looks_like_wrong_column_course_name(doc_row.course_name):
        if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
            return False
    elif not gemini_row.course_name:
        return False

    grade_level_mismatch = _same_int(doc_row.grade_level, gemini_row.grade_level) is False

    if grade_level_mismatch:
        # Only allow grade-year repair when Document AI is already incomplete or
        # suspicious. This catches Mayfair/LBUSD rows where Doc AI missed the
        # course ID and attached the row to the wrong term, while still blocking
        # ordinary matched rows from drifting across grade blocks.
        if not _doc_ai_row_needs_gemini_rescue(doc_row):
            return False

        row_distance = abs((doc_row.row_index or 0) - (gemini_row.row_index or 0))
        if row_distance > 5:
            return False

    if doc_row.grade and gemini_row.grade and _same_grade(doc_row, gemini_row) is False:
        return False

    attempted_match = _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
    completed_match = _same_credit(doc_row.credit_completed, gemini_row.credit_completed)

    if attempted_match is False and completed_match is False:
        return False

    if _course_id_numbers_conflict(doc_row, gemini_row):
        return False

    return True


def _gemini_missing_field_auto_fill_decision(
    *,
    field_name: str,
    gemini_value: Any,
    gemini_confidence: Any,
    doc_row: "NormalizedCourseRow | None" = None,
    gemini_row: "NormalizedCourseRow | None" = None,
    match_confidence: float | None = None,
    high_risk: bool = False,
) -> tuple[Any, str, bool, str | None]:
    """
    Decision for fields missing/invalid in Document AI.

    Gemini may auto-fill only when it has >=92% confidence and the matched row
    is safe. If confidence is below that threshold, we still return Gemini's
    value for visibility, but keep the row in Needs Review.
    """

    if gemini_value in (None, ""):
        return None, "missing", True, f"{field_name} is missing from both sources."

    if not _gemini_missing_field_confident(gemini_confidence):
        return gemini_value, "gemini_needs_review_low_confidence_auto_fill", True, (
            f"Document AI {field_name} is missing/invalid; "
            f"{_format_missing_field_confidence_requirement(gemini_confidence)}"
        )

    if doc_row is not None and gemini_row is not None:
        if high_risk:
            safe = (
                _matched_high_risk_gemini_fill_is_safe(
                    doc_row,
                    gemini_row,
                    match_confidence=match_confidence,
                )
                or _gemini_confident_rescue_fill_is_safe(
                    doc_row,
                    gemini_row,
                    match_confidence=match_confidence,
                )
            )
        else:
            safe = (
                _calculated_row_identity_component(
                    doc_row,
                    gemini_row,
                    match_confidence=match_confidence,
                )
                >= GEMINI_MISSING_FIELD_RESCUE_MATCH_THRESHOLD
                or _gemini_confident_rescue_fill_is_safe(
                    doc_row,
                    gemini_row,
                    match_confidence=match_confidence,
                )
            )

        if not safe:
            return gemini_value, "gemini_needs_review_unsafe_row_identity", True, (
                f"Document AI {field_name} is missing/invalid and Gemini confidence is "
                f"{_format_confidence_percent(gemini_confidence)}, but row identity is not safe enough for automatic fill."
            )

    return gemini_value, "gemini_confident_92_auto_fill", False, None


def _gemini_can_repair_document_ai_context_field(
    *,
    field_name: str,
    doc_value: Any,
    gemini_value: Any,
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    match_confidence: float | None,
) -> bool:
    """
    Allow Gemini to repair Document AI context fields such as year/month when
    Doc AI clearly attached an incomplete row to the wrong term and Gemini has
    a high-confidence same-row extraction.

    The OCR term-bundle branch is intentionally additive and narrow. It only
    applies to grade_level/month/year, and only when Document AI OCR visual-row
    evidence attached to the Gemini row provides all three values together.
    """

    if gemini_value in (None, ""):
        return False

    if doc_row is None or gemini_row is None:
        return False

    if _ocr_term_bundle_allows_context_repair(
        field_name=field_name,
        doc_row=doc_row,
        gemini_row=gemini_row,
        gemini_value=gemini_value,
    ):
        return True

    if _visual_alignment_allows_context_repair(
        doc_row,
        gemini_row,
        match_confidence=match_confidence,
    ):
        return True

    if not _doc_ai_row_needs_gemini_rescue(doc_row):
        return False

    return _gemini_confident_rescue_fill_is_safe(
        doc_row,
        gemini_row,
        match_confidence=match_confidence,
    )




def _calculated_grade_proof_score(
    *,
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    grade_scan_evidence: dict[str, Any] | None,
    match_confidence: float | None,
    doc_grade: Any,
    gemini_grade: Any,
) -> float | None:
    """
    Calculated grade proof.

    This is the only score allowed to push a valid Document AI grade into
    Needs Review or into Gemini/verifier auto-correction. A verifier's raw
    confidence alone is not enough.
    """

    if not grade_scan_evidence:
        return None

    verifier_grade = _grade_scan_proof_grade(grade_scan_evidence)

    if not verifier_grade:
        return None

    verifier_confidence = _grade_scan_proof_confidence(grade_scan_evidence)

    if verifier_confidence is None:
        return None

    match_component = _normalized_match_score_component(
        grade_scan_evidence.get("match_score")
    )
    row_component = _calculated_row_identity_component(
        doc_row,
        gemini_row,
        match_confidence=match_confidence,
    )

    doc_base = _base_grade(doc_grade)
    gemini_base = _base_grade(gemini_grade)
    verifier_base = _base_grade(verifier_grade)

    # If Doc AI and Gemini already agree and verifier alone disagrees, treat
    # verifier as weak evidence even when it reports 100%.
    if doc_base and gemini_base and doc_base == gemini_base and verifier_base != doc_base:
        agreement_component = 0.65
    elif verifier_base and gemini_base and verifier_base == gemini_base:
        agreement_component = 1.0
    elif verifier_base and doc_base and verifier_base == doc_base:
        agreement_component = 1.0
    else:
        # Third value is useful enough to potentially request review, but not
        # enough to auto-overwrite.
        agreement_component = 0.75

    proof = (
        verifier_confidence
        * match_component
        * row_component
        * agreement_component
    )

    return round(max(0.0, min(proof, 1.0)), 4)


def _calculated_course_id_proof_score(
    *,
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    course_id_scan_evidence: dict[str, Any] | None,
    match_confidence: float | None,
    doc_course_id: Any,
    gemini_course_id: Any,
) -> float | None:
    """
    Calculated Course ID proof.

    Course ID is high-risk. Gemini/verifier can override a valid Document AI ID
    only when this calculated score is strong and row identity is extremely safe.
    """

    if not course_id_scan_evidence:
        return None

    verifier_id = _course_id_scan_proof_id(course_id_scan_evidence)

    if not verifier_id:
        return None

    verifier_confidence = _course_id_scan_proof_confidence(course_id_scan_evidence)

    if verifier_confidence is None:
        return None

    match_component = _normalized_match_score_component(
        course_id_scan_evidence.get("match_score")
    )
    row_component = _calculated_row_identity_component(
        doc_row,
        gemini_row,
        match_confidence=match_confidence,
    )

    if _course_ids_equivalent(verifier_id, gemini_course_id):
        agreement_component = 1.0
    elif _course_ids_equivalent(verifier_id, doc_course_id):
        agreement_component = 1.0
    else:
        agreement_component = 0.75

    proof = (
        verifier_confidence
        * match_component
        * row_component
        * agreement_component
    )

    return round(max(0.0, min(proof, 1.0)), 4)


def _calculated_proof_in_middle_band(score: Any) -> bool:
    numeric_score = _coerce_float(score)

    return (
        numeric_score is not None
        and CALCULATED_PROOF_REVIEW_THRESHOLD
        <= numeric_score
        < CALCULATED_PROOF_AUTO_OVERRIDE_THRESHOLD
    )


def _calculated_proof_can_auto_override(score: Any) -> bool:
    numeric_score = _coerce_float(score)

    return (
        numeric_score is not None
        and numeric_score >= CALCULATED_PROOF_AUTO_OVERRIDE_THRESHOLD
    )



def _grade_proof_confidence(
    *,
    gemini_confidence: Any,
    grade_scan_evidence: dict[str, Any] | None,
) -> float | None:
    values: list[float] = []

    base_confidence = _coerce_float(gemini_confidence)

    if base_confidence is not None:
        values.append(base_confidence)

    if grade_scan_evidence and grade_scan_evidence.get("grade"):
        scan_confidence = _coerce_float(grade_scan_evidence.get("confidence"))

        if scan_confidence is not None:
            values.append(scan_confidence)

    return max(values) if values else None


def _grade_proof_in_middle_band(confidence: Any) -> bool:
    numeric_confidence = _coerce_float(confidence)
    return (
        numeric_confidence is not None
        and GEMINI_GRADE_REVIEW_CONFIDENCE_THRESHOLD
        <= numeric_confidence
        < GEMINI_GRADE_AUTO_OVERRIDE_CONFIDENCE_THRESHOLD
    )


def _grade_proof_can_auto_override(confidence: Any) -> bool:
    numeric_confidence = _coerce_float(confidence)
    return (
        numeric_confidence is not None
        and numeric_confidence >= GEMINI_GRADE_AUTO_OVERRIDE_CONFIDENCE_THRESHOLD
    )


def _grade_scan_proof_confidence(
    grade_scan_evidence: dict[str, Any] | None,
) -> float | None:
    if not grade_scan_evidence or not grade_scan_evidence.get("grade"):
        return None

    if not _grade_scan_match_strong(grade_scan_evidence.get("match_score")):
        return None

    return _coerce_float(grade_scan_evidence.get("confidence"))


def _grade_scan_proof_grade(
    grade_scan_evidence: dict[str, Any] | None,
) -> str | None:
    if not grade_scan_evidence:
        return None

    grade = grade_scan_evidence.get("grade")

    if grade in (None, ""):
        return None

    return str(grade).strip()


def _format_confidence_percent(confidence: Any) -> str:
    numeric_confidence = _coerce_float(confidence)

    if numeric_confidence is None:
        return "unknown confidence"

    return f"{round(numeric_confidence * 100, 1)}%"


def _grade_scan_match_strong(match_score: Any) -> bool:
    numeric_score = _coerce_float(match_score)

    if numeric_score is None:
        return True

    return numeric_score >= GEMINI_GRADE_SCAN_MATCH_SCORE_THRESHOLD


def _extract_grade_scan_evidence(row: "NormalizedCourseRow | None") -> dict[str, Any]:
    if row is None:
        return {}

    payload = _raw_payload_dict(row.raw_payload)

    if not payload:
        return {}

    grade = (
        payload.get("backend_grade_scan_grade")
        or payload.get("grade_scan_grade")
        or payload.get("verified_grade")
    )
    before_grade = (
        payload.get("backend_grade_scan_before_grade")
        or payload.get("grade_scan_before_grade")
    )
    confidence = (
        payload.get("backend_grade_scan_confidence")
        or payload.get("grade_scan_confidence")
        or payload.get("verified_grade_confidence")
    )
    match_score = (
        payload.get("backend_grade_scan_match_score")
        or payload.get("grade_scan_match_score")
    )
    agrees_with_main = (
        payload.get("backend_grade_scan_agrees_with_main")
        if "backend_grade_scan_agrees_with_main" in payload
        else payload.get("grade_scan_agrees_with_main")
    )
    applied = bool(
        payload.get("backend_grade_scan_applied")
        or payload.get("grade_scan_applied")
        or grade
    )

    if not applied and grade in (None, ""):
        return {}

    return {
        "applied": applied,
        "grade": str(grade).strip() if grade not in (None, "") else None,
        "before_grade": str(before_grade).strip() if before_grade not in (None, "") else None,
        "confidence": _coerce_float(confidence),
        "match_score": _coerce_float(match_score),
        "agrees_with_main": agrees_with_main,
        "raw": payload.get("backend_grade_scan_row") or payload.get("grade_scan_row"),
    }


def _extract_course_id_scan_evidence(row: "NormalizedCourseRow | None") -> dict[str, Any]:
    """
    Optional focused course-ID verifier evidence.

    This service supports verifier values if gemini_course_extractor.py stores
    them in raw_payload. If those keys are absent, reconciliation falls back to
    the normal Document AI/Gemini comparison.
    """

    if row is None:
        return {}

    payload = _raw_payload_dict(row.raw_payload)

    if not payload:
        return {}

    course_id = (
        payload.get("backend_course_id_scan_course_id")
        or payload.get("course_id_scan_course_id")
        or payload.get("verified_course_id")
        or payload.get("verified_crs_id")
    )
    confidence = (
        payload.get("backend_course_id_scan_confidence")
        or payload.get("course_id_scan_confidence")
        or payload.get("verified_course_id_confidence")
        or payload.get("verified_crs_id_confidence")
    )
    match_score = (
        payload.get("backend_course_id_scan_match_score")
        or payload.get("course_id_scan_match_score")
    )
    applied = bool(
        payload.get("backend_course_id_scan_applied")
        or payload.get("course_id_scan_applied")
        or course_id
    )

    if not applied and course_id in (None, ""):
        return {}

    return {
        "applied": applied,
        "course_id": str(course_id).strip() if course_id not in (None, "") else None,
        "confidence": _coerce_float(confidence),
        "match_score": _coerce_float(match_score),
        "raw": payload.get("backend_course_id_scan_row") or payload.get("course_id_scan_row"),
    }


def _course_id_scan_match_strong(match_score: Any) -> bool:
    numeric_score = _coerce_float(match_score)

    if numeric_score is None:
        return True

    return numeric_score >= GEMINI_GRADE_SCAN_MATCH_SCORE_THRESHOLD


def _course_id_scan_proof_confidence(
    course_id_scan_evidence: dict[str, Any] | None,
) -> float | None:
    if not course_id_scan_evidence or not course_id_scan_evidence.get("course_id"):
        return None

    if not _course_id_scan_match_strong(course_id_scan_evidence.get("match_score")):
        return None

    return _coerce_float(course_id_scan_evidence.get("confidence"))


def _course_id_scan_proof_id(
    course_id_scan_evidence: dict[str, Any] | None,
) -> str | None:
    if not course_id_scan_evidence:
        return None

    course_id = course_id_scan_evidence.get("course_id")

    if course_id in (None, ""):
        return None

    return str(course_id).strip()


def _normalize_course_id_for_compare(value: Any) -> str:
    if value in (None, ""):
        return ""

    text = str(value).upper().strip()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _course_ids_equivalent(left: Any, right: Any) -> bool:
    return bool(
        _normalize_course_id_for_compare(left)
        and _normalize_course_id_for_compare(left) == _normalize_course_id_for_compare(right)
    )



def _extract_visible_course_id_from_ocr_row_text(row_text: Any) -> str | None:
    """
    Extract the course ID printed at the start of a trusted OCR visual-row text.

    This is intentionally start-anchored so it does not accidentally capture
    credits, grades, years, or numbers inside the course title. It supports the
    formats already seen in the pipeline:
      - Mayfair: "p 9120", "* p 8501", "+ p 4140", "6875", "+ CC001"
      - LBUSD: "P 1025", "N 3707", "HP 1449", "H P 2318"
    """

    if row_text in (None, ""):
        return None

    text_value = str(row_text).strip()

    if not text_value:
        return None

    match = re.match(
        r"^\s*(?P<marker>[+*])?\s*"
        r"(?:(?P<prefix>H\s*P|HP|AP|P|N|R|H|p|n|r)\s+)?"
        r"(?P<number>CC\d{2,4}|\d{3,5})\b",
        text_value,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    marker = (match.group("marker") or "").strip()
    prefix_raw = (match.group("prefix") or "").strip()
    number = (match.group("number") or "").strip()

    if not number:
        return None

    if number.upper().startswith("CC"):
        base_id = number.upper()
    elif prefix_raw:
        compact_prefix = re.sub(r"\s+", "", prefix_raw)
        # Preserve Mayfair lower-case p when OCR prints lower-case p.
        if compact_prefix == "p":
            normalized_prefix = "p"
        elif compact_prefix == "n":
            normalized_prefix = "n"
        elif compact_prefix == "r":
            normalized_prefix = "r"
        else:
            normalized_prefix = compact_prefix.upper()

        base_id = f"{normalized_prefix} {number}"
    else:
        base_id = number

    if marker:
        return f"{marker} {base_id}".strip()

    return base_id.strip()


def _course_id_ocr_row_text_confirms_same_course(
    *,
    row_text: Any,
    row: "NormalizedCourseRow | None",
    visible_course_id: Any,
) -> bool:
    """
    Confirm that OCR row text belongs to this same course before using its
    printed course ID.

    The rule is deliberately safer than a blind majority vote:
    - OCR must expose a start-of-row course ID.
    - The row text must match the course title.
    - The row text must also confirm either grade or credits.

    This allows fixing Mayfair continuation rows such as:
      "p 9120 French III A- 5.00 5.00"
    even when Gemini saved the wrong course ID from a nearby row.
    """

    if row is None:
        return False

    if row_text in (None, "") or visible_course_id in (None, ""):
        return False

    if not _is_valid_course_id_value(visible_course_id):
        return False

    text_value = str(row_text).strip()
    text_upper = text_value.upper()

    if not text_value:
        return False

    course_name_ok = False

    if row.course_name not in (None, ""):
        course_name_ok = (
            _names_similar(text_value, row.course_name) >= 0.55
            or _names_token_similar(text_value, row.course_name, threshold=0.45)
        )

    if not course_name_ok:
        return False

    grade_ok = False
    base_grade = _base_grade(row.grade)

    if base_grade:
        grade_ok = bool(
            re.search(rf"\b{re.escape(base_grade)}[+-]?\b", text_upper)
        )

    credit_ok = False

    for credit in (row.credit_attempted, row.credit_completed):
        credit_float = _coerce_float(credit)

        if credit_float is None:
            continue

        if abs(credit_float - int(credit_float)) < 0.01:
            credit_pattern = str(int(credit_float))
        else:
            credit_pattern = str(credit_float)

        if re.search(rf"\b{re.escape(credit_pattern)}(?:\.0{{1,2}})?\b", text_value):
            credit_ok = True
            break

    return bool(grade_ok or credit_ok)


def _extract_ocr_course_id_evidence(
    row: "NormalizedCourseRow | None",
) -> dict[str, Any]:
    """
    Return start-of-visual-row Course ID evidence from Document AI OCR text.

    This helper is additive and only reads raw_payload keys already attached to
    gemini_course_details. It does not change counts or matching.
    """

    if row is None:
        return {
            "confirmed": False,
            "course_id": None,
            "row_text": None,
            "reason": "row is missing",
        }

    payload = _raw_payload_dict(row.raw_payload)
    row_text = payload.get("document_ai_ocr_row_text")
    visible_course_id = _extract_visible_course_id_from_ocr_row_text(row_text)

    if row_text in (None, ""):
        return {
            "confirmed": False,
            "course_id": None,
            "row_text": None,
            "reason": "no OCR row text",
        }

    if visible_course_id in (None, ""):
        return {
            "confirmed": False,
            "course_id": None,
            "row_text": row_text,
            "reason": "no visible course ID at start of OCR row text",
        }

    confirmed = _course_id_ocr_row_text_confirms_same_course(
        row_text=row_text,
        row=row,
        visible_course_id=visible_course_id,
    )

    return {
        "confirmed": confirmed,
        "course_id": visible_course_id,
        "row_text": row_text,
        "reason": None if confirmed else "OCR row text did not confirm course title plus grade/credits",
    }


def _select_course_id_from_ocr_majority(
    *,
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    doc_id: Any,
    gemini_id: Any,
) -> tuple[Any, str, bool, str | None] | None:
    """
    Safe weighted-majority Course ID rule.

    Sources:
      1. Document AI course ID
      2. Gemini course ID
      3. Document AI OCR visual-row text

    OCR row text is only counted when it confirms the same row by title plus
    grade/credits. If OCR confirms a visible Course ID, it can repair a shifted
    Gemini Course ID. This fixes the row-48-style problem without changing the
    rest of the reconciliation pipeline.
    """

    evidence_rows: list[tuple[str, dict[str, Any], Any]] = []

    if doc_row is not None:
        evidence_rows.append(
            ("document_ai_ocr_row_text", _extract_ocr_course_id_evidence(doc_row), doc_id)
        )

    if gemini_row is not None:
        evidence_rows.append(
            ("document_ai_ocr_row_text", _extract_ocr_course_id_evidence(gemini_row), gemini_id)
        )

    confirmed_evidence = [
        (source, evidence, source_id)
        for source, evidence, source_id in evidence_rows
        if evidence.get("confirmed") and _is_valid_course_id_value(evidence.get("course_id"))
    ]

    if not confirmed_evidence:
        return None

    # If both rows have OCR evidence but the OCR IDs disagree, do not guess.
    confirmed_ids = {
        _normalize_course_id_for_compare(evidence.get("course_id"))
        for _source, evidence, _source_id in confirmed_evidence
        if evidence.get("course_id") not in (None, "")
    }

    if len(confirmed_ids) != 1:
        return None

    ocr_course_id = confirmed_evidence[0][1].get("course_id")

    if ocr_course_id in (None, ""):
        return None

    # Majority / agreement cases.
    if _course_ids_equivalent(ocr_course_id, doc_id):
        return doc_id, "document_ai_ocr_course_id_confirmed", False, None

    if _course_ids_equivalent(ocr_course_id, gemini_id):
        return gemini_id, "gemini_course_id_confirmed_by_document_ai_ocr", False, None

    # OCR third value case. This is allowed only because the helper already
    # confirmed the exact visual row by title plus grade/credits.
    return (
        ocr_course_id,
        "document_ai_ocr_row_text_course_id_repair",
        False,
        None,
    )


def _source_only_gemini_course_id_ocr_repair(
    row: "NormalizedCourseRow",
) -> tuple[Any, str] | None:
    """
    Repair a Gemini-only row's course ID from OCR row text when OCR confirms the
    same visual row.

    This only affects the final Course ID value for a source-only Gemini row.
    It does not mutate raw gemini_course_details and does not change counts.
    """

    evidence = _extract_ocr_course_id_evidence(row)

    if not evidence.get("confirmed"):
        return None

    ocr_course_id = evidence.get("course_id")

    if ocr_course_id in (None, ""):
        return None

    if not _is_valid_course_id_value(ocr_course_id):
        return None

    if _course_ids_equivalent(ocr_course_id, row.course_id):
        return row.course_id, "gemini_course_id_confirmed_by_document_ai_ocr"

    return ocr_course_id, "document_ai_ocr_row_text_course_id_repair"


def _grade_scan_is_strong(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False

    return (
        bool(evidence.get("grade"))
        and _grade_scan_confident(evidence.get("confidence"))
        and _grade_scan_match_strong(evidence.get("match_score"))
    )


def _grade_scan_grade(row: "NormalizedCourseRow | None") -> str | None:
    evidence = _extract_grade_scan_evidence(row)

    if not _grade_scan_is_strong(evidence):
        return None

    grade = evidence.get("grade")
    return str(grade).strip() if grade not in (None, "") else None


def _effective_gemini_grade_confidence(
    *,
    gemini_confidence: Any,
    grade_scan_evidence: dict[str, Any] | None,
    allow_grade_scan: bool,
) -> float | None:
    values: list[float] = []

    base_confidence = _coerce_float(gemini_confidence)

    if base_confidence is not None:
        values.append(base_confidence)

    if allow_grade_scan and _grade_scan_is_strong(grade_scan_evidence):
        scan_confidence = _coerce_float(grade_scan_evidence.get("confidence"))

        if scan_confidence is not None:
            values.append(scan_confidence)

    return max(values) if values else None


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _month_to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value if 1 <= value <= 12 else None

    text = str(value).strip()

    try:
        month = int(text)
        return month if 1 <= month <= 12 else None
    except Exception:
        pass

    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    low = text.lower()

    for key, val in months.items():
        if re.search(rf"\b{re.escape(key)}\b", low):
            return val

    # Fall/Spring are terms, not month numbers.
    return None


def _mayfair_term_month_from_context(*values: Any) -> int | None:
    """
    Repair Mayfair term months from visible term context.

    Mayfair transcript sections can show Fall/Spring/Summer terms instead of a
    numeric month. For this pipeline we normalize:
      Fall -> 1
      Spring -> 6
      Summer / Summer School / Intersession -> 7

    The repair only applies when the surrounding text indicates Mayfair.
    """

    pieces: list[str] = []

    for value in values:
        if value in (None, "", [], {}):
            continue

        if isinstance(value, dict):
            try:
                pieces.append(json.dumps(value, default=str))
            except Exception:
                pieces.append(str(value))
        else:
            pieces.append(str(value))

    text_value = " ".join(pieces).upper()

    if not text_value:
        return None

    if "MAYFAIR" not in text_value:
        return None

    if re.search(r"\b(INTERSESSION|SUMMER|SUMMER SCHOOL|SUMR)\b", text_value):
        return 7

    if re.search(r"\bSPRING\b", text_value):
        return 6

    if re.search(r"\bFALL\b", text_value):
        return 1

    return None



def _year_to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip()

    try:
        parsed = int(text)
        if 1900 <= parsed <= 2100:
            return parsed
    except Exception:
        pass

    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None



def _academic_start_year_from_context(*values: Any) -> int | None:
    """
    Extract the START year from an academic-year range.

    Pipeline rule for Mayfair and LBUSD-style academic-year ranges:
      2021-2022 -> 2021
      2022-2023 -> 2022
      2023-2024 -> 2023

    If a transcript only gives a single explicit year, no repair is applied.
    """

    pieces: list[str] = []

    for value in values:
        if value in (None, "", [], {}):
            continue

        if isinstance(value, dict):
            try:
                pieces.append(json.dumps(value, default=str))
            except Exception:
                pieces.append(str(value))
        else:
            pieces.append(str(value))

    text_value = " ".join(pieces)

    if not text_value:
        return None

    match = re.search(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b", text_value)

    if not match:
        return None

    return int(match.group(1))


def _repair_year_to_academic_start_year(
    current_year: Any,
    *context_values: Any,
) -> int | None:
    current = _year_to_int(current_year)
    start_year = _academic_start_year_from_context(*context_values)

    if start_year is not None:
        return start_year

    return current




def _ocr_row_text_matches_course_identity(
    *,
    row_text: Any,
    course_id: Any = None,
    course_name: Any = None,
    grade: Any = None,
    credit_attempted: Any = None,
    credit_completed: Any = None,
) -> bool:
    """
    Safety check before trusting Document AI OCR section context.

    The OCR visual row is allowed to repair term context only when its row text
    visibly belongs to the same course row by course number or course title.
    This prevents a section header from a nearby row/column from changing rows
    that are already correct.

    Course ID is allowed as one anchor, but it is not required. This matters for
    shifted Mayfair rows where Gemini has the wrong Course ID but the OCR row
    text still proves the same visual row by course title plus grade/credits.
    """

    if row_text in (None, ""):
        return False

    text_value = str(row_text).strip()

    if not text_value:
        return False

    anchors = 0

    course_number = _course_number_from_raw(course_id)
    if course_number and re.search(rf"\b{re.escape(course_number)}\b", text_value):
        anchors += 2

    if course_name not in (None, ""):
        name_score = _names_similar(row_text, course_name)
        if name_score >= 0.55 or _names_token_similar(row_text, course_name, threshold=0.45):
            anchors += 2

    base_grade = _base_grade(grade)
    if base_grade and re.search(rf"\b{re.escape(base_grade)}[+-]?\b", text_value.upper()):
        anchors += 1

    attempted = _coerce_float(credit_attempted)
    completed = _coerce_float(credit_completed)

    for credit in (attempted, completed):
        if credit is None:
            continue

        # Match common transcript forms such as 5, 5.0, 5.00.
        credit_pattern = str(int(credit)) if abs(credit - int(credit)) < 0.01 else str(credit)
        if re.search(rf"\b{re.escape(credit_pattern)}(?:\.0{{1,2}})?\b", text_value):
            anchors += 1
            break

    return anchors >= 2


def _extract_document_ai_ocr_term_bundle(
    *,
    raw_payload: Any,
    course_id: Any = None,
    course_name: Any = None,
    grade: Any = None,
    credit_attempted: Any = None,
    credit_completed: Any = None,
) -> dict[str, Any] | None:
    """
    Return a complete OCR term-context bundle from Document AI visual-row OCR.

    Important rule:
    grade_level, month, and year are treated as one bundle. If the OCR evidence
    is trusted, all three must move together. This fixes continued-column rows
    where grade year was correct but month/year came from a different section.
    """

    payload = _raw_payload_dict(raw_payload)

    if not payload:
        return None

    row_text = payload.get("document_ai_ocr_row_text")
    grade_level = _coerce_int(payload.get("document_ai_ocr_section_grade"))
    month = _month_to_int(payload.get("document_ai_ocr_section_month"))
    year = _year_to_int(payload.get("document_ai_ocr_section_year"))

    if grade_level is None or month is None or year is None:
        return None

    if not _is_valid_grade_level(grade_level):
        return None

    if not _ocr_row_text_matches_course_identity(
        row_text=row_text,
        course_id=course_id,
        course_name=course_name,
        grade=grade,
        credit_attempted=credit_attempted,
        credit_completed=credit_completed,
    ):
        return None

    return {
        "grade_level": grade_level,
        "month": month,
        "year": year,
        "row_text": row_text,
        "section_name": payload.get("document_ai_ocr_section_name"),
        "section_source": payload.get("document_ai_ocr_section_source"),
        "match_score": _coerce_float(payload.get("document_ai_ocr_match_score")),
        "source": "document_ai_ocr_term_bundle",
    }


def _ocr_term_bundle_for_row(
    row: "NormalizedCourseRow | None",
) -> dict[str, Any] | None:
    if row is None:
        return None

    return _extract_document_ai_ocr_term_bundle(
        raw_payload=row.raw_payload,
        course_id=row.course_id,
        course_name=row.course_name,
        grade=row.grade,
        credit_attempted=row.credit_attempted,
        credit_completed=row.credit_completed,
    )


def _ocr_term_bundle_allows_context_repair(
    *,
    field_name: str,
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    gemini_value: Any,
) -> bool:
    """
    Let OCR visual-row evidence repair only term-context fields, and only when
    the OCR bundle agrees with the Gemini normalized value.

    This is intentionally narrow:
    - does not affect counts
    - does not affect course id/name/grade/credits
    - does not run when OCR evidence is absent/incomplete
    """

    if field_name not in {"grade_level", "year", "month"}:
        return False

    if doc_row is None or gemini_row is None:
        return False

    bundle = _ocr_term_bundle_for_row(gemini_row)

    if not bundle:
        return False

    bundle_key = {
        "grade_level": "grade_level",
        "year": "year",
        "month": "month",
    }[field_name]

    if _same_int(bundle.get(bundle_key), gemini_value) is not True:
        return False

    # The OCR row text has already matched the Gemini row. Now make sure the
    # matched Doc AI row is not a totally different course.
    if doc_row.course_name and gemini_row.course_name:
        if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
            return False

    if _course_id_numbers_conflict(doc_row, gemini_row):
        # Different numeric IDs are allowed only when the title/grade/credits
        # still prove this is the same visual row. Otherwise do not repair.
        if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
            return False

    if doc_row.grade and gemini_row.grade and _same_grade(doc_row, gemini_row) is False:
        return False

    attempted_match = _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
    completed_match = _same_credit(doc_row.credit_completed, gemini_row.credit_completed)

    if attempted_match is False and completed_match is False:
        return False

    return True



def _normalize_text(value: Any) -> str:
    text = str(value or "").upper()
    text = text.replace("Η", "H")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = re.sub(r"[^A-Z0-9 ()/&+-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_course_name(value: Any) -> str:
    text = _normalize_text(value)

    phrase_replacements = {
        "BIO LVNG ERTH": "BIOLOGY LIVING EARTH",
        "BIO LIVING EARTH": "BIOLOGY LIVING EARTH",
        "CHEM EARTH SYS": "CHEMISTRY EARTH SYSTEMS",
        "CHEM EARTH SYSTEM": "CHEMISTRY EARTH SYSTEMS",
        "INTRO HITH CAR": "INTRO HEALTH CARE",
        "INTRO HLTH CAR": "INTRO HEALTH CARE",
        "HUM GEOG": "HUMAN GEOGRAPHY",
        "MATH ANALYSIS HB-": "MATH ANALYSIS H",
        "MATH ANALYSIS HB": "MATH ANALYSIS H",
        "INTG MATH": "INTEGRATED MATH",
        "INT MATH": "INTEGRATED MATH",
        "INTGRD MATH": "INTEGRATED MATH",
        "INTGRTD MATH": "INTEGRATED MATH",
        "AP GOVT": "AP GOVERNMENT",
        "AP GOV": "AP GOVERNMENT",
        "BIG HISTORY PROJECT WORLD HIST": "BIG HISTORY PROJECT WORLD HISTORY",
        "BIG HIST PROJECT WORLD HIST": "BIG HISTORY PROJECT WORLD HISTORY",
        "ADV KINESIOLOGY": "ADVANCED KINESIOLOGY",
    }

    word_replacements = {
        "ENG": "ENGLISH",
        "ELA": "ENGLISH",
        "ALG": "ALGEBRA",
        "BIO": "BIOLOGY",
        "CHEM": "CHEMISTRY",
        "GOVT": "GOVERNMENT",
        "GOV": "GOVERNMENT",
        "HIST": "HISTORY",
        "GEOG": "GEOGRAPHY",
        "GEOM": "GEOMETRY",
        "INTG": "INTEGRATED",
        "INTGRD": "INTEGRATED",
        "INTGRTD": "INTEGRATED",
        "PCT": "PERCENT",
    }

    for old, new in phrase_replacements.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)

    for old, new in word_replacements.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)

    return re.sub(r"\s+", " ", text).strip()


def _repair_final_course_name_display(value: Any) -> tuple[Any, str | None]:
    """
    Apply tiny, evidence-backed final display-name repairs.

    Keep this map intentionally small. It fixes known transcript-title order
    cases without inventing broad subject-name rewrites.
    """

    if value in (None, ""):
        return value, None

    original = str(value).strip()
    normalized = _normalize_course_name(original)

    exact_repairs = {
        "COLLABORATIVE MATHEMATICS": "Mathematics Collaborative",
    }

    repaired = exact_repairs.get(normalized)

    if repaired and repaired != original:
        return repaired, "course_name_exact_display_repair"

    return value, None


def _apply_course_name_repair_to_final_values(
    final_values: dict[str, Any],
) -> None:
    repaired_name, repair_reason = _repair_final_course_name_display(
        final_values.get("course_name")
    )

    if not repair_reason:
        return

    final_values["course_name"] = repaired_name

    field_decisions = final_values.setdefault("field_decisions", {})
    previous_source = str(field_decisions.get("course_name") or "document_ai")

    if "gemini" in previous_source.lower() or previous_source.lower() == "gem":
        field_decisions["course_name"] = "gemini_course_name_exact_display_repair"
    elif "both" in previous_source.lower():
        field_decisions["course_name"] = "both_course_name_exact_display_repair"
    else:
        field_decisions["course_name"] = "document_ai_course_name_exact_display_repair"

    current_resolution = final_values.get("resolution_reason")
    if current_resolution:
        final_values["resolution_reason"] = f"{current_resolution}; {repair_reason}"
    else:
        final_values["resolution_reason"] = repair_reason


def _normalize_grade(value: Any) -> str:
    grade = re.sub(r"\s+", "", str(value or "").strip().upper())

    # DR is not a real grade code in this workflow.
    # Treat it as an OCR/parse error for D, not as CR.
    # CR is preserved only when the extractor actually reads CR.
    if grade == "DR":
        return "D"

    return grade


def _canonical_grade_value(value: Any) -> str | None:
    grade = _normalize_grade(value)
    return grade if grade else None


def _base_grade(value: Any) -> str:
    grade = _normalize_grade(value)

    if not grade:
        return ""

    letter_match = re.match(r"^([ABCDF])[\+\-]?$", grade)
    if letter_match:
        return letter_match.group(1)

    return grade


def _is_standard_letter_grade(value: Any) -> bool:
    return bool(re.match(r"^[ABCDF][\+\-]?$", _normalize_grade(value)))


def _course_number_from_raw(value: Any) -> str:
    if value in (None, ""):
        return ""

    match = re.search(r"(\d+)", str(value))
    return match.group(1) if match else ""


def _course_prefix_from_raw(value: Any) -> str | None:
    if value in (None, ""):
        return None

    match = re.search(r"\b([A-Za-z]+)\b", str(value))
    return match.group(1).upper() if match else None


def _is_valid_course_id_value(value: Any) -> bool:
    if value in (None, ""):
        return False

    text = str(value).strip()

    if not text:
        return False

    # A valid course id should contain at least one alphanumeric token. Symbols
    # alone such as "+" or "*" are not valid course IDs.
    return bool(re.search(r"[A-Za-z0-9]", text)) and not bool(re.fullmatch(r"[+*\s]+", text))


def _course_id_alpha_prefix(value: Any) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip().upper()
    match = re.match(r"^\s*([A-Z]+)\s*\d+", text)
    return match.group(1) if match else ""


def _course_id_number(value: Any) -> str:
    return _course_number_from_raw(value)


def _format_course_id(prefix: str | None, number: str | None) -> str | None:
    clean_number = str(number or "").strip()
    clean_prefix = str(prefix or "").strip().upper()

    if not clean_number:
        return None

    if clean_prefix:
        return f"{clean_prefix} {clean_number}"

    return clean_number


def _same_required_row_context(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> bool:
    # Only use this for auto-cleaning risky IDs when the surrounding row context
    # already proves both sources are describing the same row.
    required_checks = [
        _same_int(doc_row.year, gemini_row.year),
        _same_int(doc_row.month, gemini_row.month),
        _same_int(doc_row.grade_level, gemini_row.grade_level),
    ]

    return all(check is not False for check in required_checks)


def _is_cleaner_course_id_candidate(
    *,
    noisy_id: Any,
    clean_id: Any,
    noisy_name: Any,
    clean_name: Any,
) -> bool:
    """
    Return True when clean_id is a safer same-number course id than noisy_id.

    This is intentionally evidence-based. It does not say AP/IN/etc. are always
    invalid. It only flags cases where one source has the same numeric course
    number and a shorter prefix while the other source has extra leading
    letters that can plausibly come from OCR/title bleed.
    """

    noisy_number = _course_id_number(noisy_id)
    clean_number = _course_id_number(clean_id)

    if not noisy_number or not clean_number or noisy_number != clean_number:
        return False

    noisy_prefix = _course_id_alpha_prefix(noisy_id)
    clean_prefix = _course_id_alpha_prefix(clean_id)

    if not noisy_prefix or not clean_prefix:
        return False

    if noisy_prefix == clean_prefix:
        return False

    # The cleaner candidate must be a shorter alpha prefix from the other source.
    if len(clean_prefix) >= len(noisy_prefix):
        return False

    # The noisy prefix should contain the clean prefix. This catches examples
    # like IN -> N, HPX -> HP, APP -> AP, without banning real IN/AP codes.
    if clean_prefix not in noisy_prefix:
        return False

    # If course names are unrelated, do not auto-clean. Use both sequence and
    # token identity so "PE 10 Advanced Kinesiology" and
    # "Advanced Kinesiology PE 10" are treated as the same course.
    if not _course_names_same_identity(noisy_name, clean_name):
        return False

    return True


def _choose_cleaner_same_number_course_id(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> tuple[Any, str] | None:
    if not _same_required_row_context(doc_row, gemini_row):
        return None

    if not (
        doc_row.course_number
        and gemini_row.course_number
        and doc_row.course_number == gemini_row.course_number
    ):
        return None

    if _is_cleaner_course_id_candidate(
        noisy_id=doc_row.course_id,
        clean_id=gemini_row.course_id,
        noisy_name=doc_row.course_name,
        clean_name=gemini_row.course_name,
    ):
        return gemini_row.course_id, "gemini_cleaner_same_number_course_id"

    if _is_cleaner_course_id_candidate(
        noisy_id=gemini_row.course_id,
        clean_id=doc_row.course_id,
        noisy_name=gemini_row.course_name,
        clean_name=doc_row.course_name,
    ):
        return doc_row.course_id, "document_ai_cleaner_same_number_course_id"

    return None


def _is_valid_grade(value: Any) -> bool:
    grade = _normalize_grade(value)

    if not grade:
        return False

    letter_grades = {
        "A+",
        "A",
        "A-",
        "B+",
        "B",
        "B-",
        "C+",
        "C",
        "C-",
        "D+",
        "D",
        "D-",
        "F",
        "P",
        "NP",
        "CR",
        "NC",
        "I",
        "W",
    }

    if grade in letter_grades:
        return True

    try:
        numeric = float(grade)
        return 0 <= numeric <= 100
    except Exception:
        return False


def _is_valid_grade_level(value: Any) -> bool:
    grade_level = _coerce_int(value)
    return grade_level is not None and 6 <= grade_level <= 12


def _is_plausible_credit(value: Any) -> bool:
    credit = _coerce_float(value)
    return credit is not None and 0 <= credit <= BAD_SINGLE_COURSE_CREDIT_LIMIT


def _is_bad_credit(value: Any) -> bool:
    credit = _coerce_float(value)
    return credit is not None and credit > BAD_SINGLE_COURSE_CREDIT_LIMIT


def _credits_equal(left: Any, right: Any) -> bool:
    left_float = _coerce_float(left)
    right_float = _coerce_float(right)

    if left_float is None or right_float is None:
        return False

    return abs(left_float - right_float) < 0.01


def _same_month_for_review(left: Any, right: Any) -> bool | None:
    left_int = _month_to_int(left)
    right_int = _month_to_int(right)

    if left_int is None and right_int is None:
        return None

    if left_int is None or right_int is None:
        return None

    if left_int == right_int:
        return True

    # Month mismatch is not a review blocker.
    return None


def _field_decisions_include_user_visible_gemini_fix(
    field_decisions: dict[str, Any] | None,
) -> bool:
    # Backend may use Gemini to fill/correct month, but frontend should not
    # advertise month-only changes as "fixed." This helper is only for summary
    # counts; final_course_details can still store crs_month_source="gemini".
    if not isinstance(field_decisions, dict):
        return False

    hidden_fields = {
        "month",
        "crs_month",
        "final_month",
        "term_month",
    }

    for field_name, source in field_decisions.items():
        normalized_field = str(field_name or "").strip().lower()
        normalized_source = str(source or "").strip().lower()

        if normalized_field in hidden_fields:
            continue

        if normalized_source.startswith("gemini") or normalized_source == "gem":
            return True

    return False


def _compact_source_label(value: Any) -> str | None:
    """
    Store source-only labels in short DB source columns.

    Do not store decision/reason strings such as
    "document_ai_default_grade_kept_grade_scan_disagreed" in *_source fields.
    """

    if value in (None, ""):
        return None

    text = str(value).strip().lower()

    if not text:
        return None

    if "not_applicable" in text or text in {"n/a", "na", "none"}:
        return "na"

    if "missing" in text or text.startswith("miss"):
        return "miss"

    if "both" in text or "matched" in text or "same_base" in text:
        return "both"

    if "document_ai" in text or "doc_ai" in text or text.startswith("doc"):
        return "docai"

    if "gemini" in text or text.startswith("gem"):
        return "gem"

    return text[:5]


def _compact_field_decisions(
    field_decisions: dict[str, Any] | None,
) -> dict[str, str | None]:
    if not isinstance(field_decisions, dict):
        return {}

    return {
        str(field_name): _compact_source_label(source)
        for field_name, source in field_decisions.items()
        if field_name not in (None, "")
    }


def _names_similar(left: Any, right: Any) -> float:
    left_name = _normalize_course_name(left)
    right_name = _normalize_course_name(right)

    if not left_name or not right_name:
        return 0.0

    if left_name == right_name:
        return 1.0

    # Treat purely cosmetic differences (parentheses, hyphens, slashes, spacing)
    # as equal so e.g. "(Pre-AP English 2)" matches "Pre-AP English 2".
    def _loose(s: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[()/&+\-]", " ", s)).strip()

    if _loose(left_name) == _loose(right_name):
        return 1.0

    return SequenceMatcher(None, left_name, right_name).ratio()


def _name_token_set(value: Any) -> set[str]:
    normalized = _normalize_course_name(value)
    if not normalized:
        return set()

    stop_tokens = {
        "A",
        "B",
        "C",
        "D",
        "F",
        "P",
        "H",
        "HP",
        "AP",
        "PE",
        "I",
        "II",
        "III",
        "IV",
        "V",
    }

    tokens = {
        token
        for token in re.findall(r"[A-Z0-9]+", normalized)
        if token and token not in stop_tokens
    }

    return tokens


def _names_token_similar(left: Any, right: Any, *, threshold: float = 0.72) -> bool:
    left_tokens = _name_token_set(left)
    right_tokens = _name_token_set(right)

    if not left_tokens or not right_tokens:
        return False

    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens

    if not union:
        return False

    jaccard = len(intersection) / len(union)
    containment = len(intersection) / min(len(left_tokens), len(right_tokens))

    return jaccard >= threshold or containment >= 0.80


def _course_names_same_identity(left: Any, right: Any) -> bool:
    return _names_similar(left, right) >= 0.78 or _names_token_similar(left, right)


def _looks_like_wrong_column_course_name(value: Any) -> bool:
    """
    Detect when a course name is actually credit / course-id / grade text.

    Example bad final value:
        "5,00/5,00 8262 B"
    """

    if value in (None, ""):
        return False

    raw = str(value).strip()

    if not raw:
        return False

    normalized = _normalize_text(raw)

    # Credit pair inside the title means the extractor read the credit column.
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*/\s*\d+(?:[\.,]\d+)?\b", raw):
        return True

    # Mostly numbers/slashes and a grade letter is not a course name.
    if re.fullmatch(r"[\d\s,./-]+\s*(?:A|B|C|D|F|P|CR|NC|NM)?", normalized):
        return True

    tokens = normalized.split()
    grade_tokens = {"A", "B", "C", "D", "F", "P", "CR", "NC", "NM"}
    alpha_tokens = [token for token in tokens if re.search(r"[A-Z]", token)]
    meaningful_alpha_tokens = [
        token
        for token in alpha_tokens
        if token not in grade_tokens
    ]

    if not meaningful_alpha_tokens and any(re.search(r"\d", token) for token in tokens):
        return True

    return False



def _is_valid_course_name(value: Any) -> bool:
    """
    Basic course-name validity check used by Gemini-only fallback logic.

    This is intentionally small and conservative:
    - It does not change matching/count ownership.
    - It only prevents obviously invalid names from auto-completing.
    - It fixes the previous NameError when Gemini-only fallback called this helper.
    """

    if value in (None, ""):
        return False

    text = str(value).strip()

    if not text:
        return False

    if _looks_like_wrong_column_course_name(text):
        return False

    # Real course names should contain at least one letter.
    return bool(re.search(r"[A-Za-z]", text))

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


def _row_id(row: Any) -> int | None:
    """
    Read a row primary key without triggering SQLAlchemy async lazy loading.

    In async SQLAlchemy, getattr(row, "id") can still try to refresh an expired
    ORM object. Reconciliation should never cause hidden database IO from a
    synchronous helper, so prefer already-loaded dictionary state.
    """
    if row is None:
        return None

    if isinstance(row, dict):
        return _coerce_int(row.get("id"))

    row_dict = getattr(row, "__dict__", {}) or {}

    if "id" in row_dict:
        return _coerce_int(row_dict.get("id"))

    mapper = getattr(row, "__mapper__", None)

    if mapper is not None:
        # Do not getattr() mapped ORM objects here. If id is not in __dict__,
        # accessing it may trigger a lazy refresh and MissingGreenlet.
        return None

    try:
        return _coerce_int(getattr(row, "id", None))
    except Exception:
        return None


def _loaded_row_scalar_context(row: Any) -> dict[str, Any]:
    """
    Build a safe debug/context payload from already-loaded row values only.

    This prevents helpers from doing str(row) on a SQLAlchemy ORM object, which
    can call model __repr__ and trigger async lazy-loading outside greenlet_spawn.
    """
    if row is None:
        return {}

    if isinstance(row, dict):
        source = row
    else:
        source = getattr(row, "__dict__", {}) or {}

    safe: dict[str, Any] = {}

    for key, value in source.items():
        if key.startswith("_"):
            continue

        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, (dict, list, tuple)):
            safe[key] = value

    return safe


def _get_attr(row: Any, *names: str) -> Any:
    """
    Safely read already-loaded ORM/simple-object attributes.

    SQLAlchemy async ORM can raise MissingGreenlet/greenlet_spawn errors when a
    normal getattr() triggers a lazy load outside SQLAlchemy's async greenlet.
    Reconciliation should only read fields that were already selected with the
    row, so this helper prefers __dict__ and mapper column names without forcing
    lazy database I/O.
    """
    if row is None:
        return None

    if isinstance(row, dict):
        for name in names:
            value = row.get(name)
            if value not in (None, ""):
                return value
        return None

    row_dict = getattr(row, "__dict__", {}) or {}

    mapper_column_names: set[str] = set()
    mapper = getattr(row, "__mapper__", None)

    if mapper is not None:
        try:
            mapper_column_names = set(mapper.columns.keys())
        except Exception:
            mapper_column_names = set()

    for name in names:
        value = None
        found = False

        if name in row_dict:
            value = row_dict.get(name)
            found = True
        elif mapper is not None:
            # Important: never hasattr()/getattr() SQLAlchemy ORM instances
            # for unloaded attributes in a sync helper. That is what causes
            # "greenlet_spawn has not been called; can't call await_only() here".
            # Treat missing mapped/unmapped names as unavailable.
            if not mapper_column_names or name in mapper_column_names:
                found = True
                value = None
        else:
            try:
                value = getattr(row, name)
                found = True
            except Exception:
                found = False
                value = None

        if found and value not in (None, ""):
            return value

    return None



# ---------------------------------------------------------------------------
# Optional visual alignment / geometry helpers
# ---------------------------------------------------------------------------

def _json_value(payload: Any, *names: str) -> Any:
    payload_dict = _raw_payload_dict(payload)

    for name in names:
        if name in payload_dict and payload_dict.get(name) not in (None, ""):
            return payload_dict.get(name)

    return None


def _direct_or_payload_value(row: Any, payload: Any, *names: str) -> Any:
    value = _get_attr(row, *names)

    if value not in (None, ""):
        return value

    return _json_value(payload, *names)


def _normalize_alignment_column(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value).strip().lower()

    aliases = {
        "l": "left",
        "left": "left",
        "1": "left",
        "0": "left",
        "m": "middle",
        "mid": "middle",
        "middle": "middle",
        "center": "middle",
        "centre": "middle",
        "2": "middle",
        "r": "right",
        "right": "right",
        "3": "right",
    }

    return aliases.get(text, text)


def _normalize_bbox(value: Any) -> list[float] | None:
    if value in (None, "", [], {}):
        return None

    if isinstance(value, str):
        cleaned = value.strip()

        if not cleaned:
            return None

        try:
            value = json.loads(cleaned)
        except Exception:
            parts = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
            value = [float(part) for part in parts] if len(parts) >= 4 else None

    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None

    try:
        return [max(0.0, min(float(value[index]), 1.0)) for index in range(4)]
    except Exception:
        return None


def _extract_row_alignment_metadata(
    *,
    source: str,
    row: Any,
    raw_payload: Any,
    fallback_row_index: int,
) -> dict[str, Any]:
    """
    Read optional row/geometry metadata without requiring DB schema changes.

    The metadata can come from:
    - direct transient row attributes added by Document AI extraction code
    - raw_payload JSON, when available
    - existing Gemini row_index/course_index columns

    If these fields are absent, the existing reconciliation behavior is
    preserved because all alignment helpers return neutral values.
    """

    prefix = "document_ai" if source == "document_ai" else "gemini"

    page_number = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_page_number",
            "page_number",
            "document_ai_page_number",
            "gemini_page_number",
        )
    )
    column = _normalize_alignment_column(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_column",
            f"{prefix}_visual_column",
            "column",
            "visual_column",
            "document_ai_column",
            "gemini_column",
        )
    )
    original_row_index = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_original_row_index",
            f"{prefix}_row_index",
            "original_row_index",
            "row_index",
            "course_index",
        )
    )
    visual_row_index = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_visual_row_index",
            "visual_row_index",
            "global_row_index",
            "geometry_row_index",
        )
    )
    page_row_index = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_page_row_index",
            "page_row_index",
        )
    )
    column_row_index = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_column_row_index",
            "column_row_index",
            "row_in_column",
        )
    )
    block_index = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_block_index",
            "block_index",
            "section_index",
        )
    )
    row_in_block = _coerce_int(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_row_in_block",
            "row_in_block",
            "section_row_index",
        )
    )
    section_name = _direct_or_payload_value(
        row,
        raw_payload,
        f"{prefix}_section_name",
        "section_name",
        "term_section",
        "term_header",
    )
    section_key = _direct_or_payload_value(
        row,
        raw_payload,
        f"{prefix}_section_key",
        "section_key",
        "term_key",
    )
    alignment_key = _direct_or_payload_value(
        row,
        raw_payload,
        f"{prefix}_alignment_key",
        "alignment_key",
        "visual_alignment_key",
    )
    visual_sort_key = _direct_or_payload_value(
        row,
        raw_payload,
        f"{prefix}_visual_sort_key",
        "visual_sort_key",
    )
    row_bbox = _normalize_bbox(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_row_bbox",
            "row_bbox",
            "document_ai_row_bbox",
            "gemini_row_bbox",
        )
    )
    raw_word_bbox = _normalize_bbox(
        _direct_or_payload_value(
            row,
            raw_payload,
            f"{prefix}_raw_word_bbox",
            "raw_word_bbox",
            "document_ai_raw_word_bbox",
            "gemini_raw_word_bbox",
        )
    )
    geometry_source = _direct_or_payload_value(
        row,
        raw_payload,
        f"{prefix}_geometry_source",
        f"{prefix}_sequence_source",
        "geometry_source",
        "sequence_source",
    )

    safe_row_index = (
        visual_row_index
        or page_row_index
        or original_row_index
        or fallback_row_index
    )

    return {
        "source": source,
        "page_number": page_number,
        "column": column,
        "original_row_index": original_row_index,
        "visual_row_index": visual_row_index,
        "page_row_index": page_row_index,
        "column_row_index": column_row_index,
        "block_index": block_index,
        "row_in_block": row_in_block,
        "safe_row_index": safe_row_index,
        "section_name": str(section_name).strip() if section_name not in (None, "") else None,
        "section_key": str(section_key).strip() if section_key not in (None, "") else None,
        "alignment_key": str(alignment_key).strip() if alignment_key not in (None, "") else None,
        "visual_sort_key": visual_sort_key,
        "row_bbox": row_bbox,
        "raw_word_bbox": raw_word_bbox,
        "geometry_source": str(geometry_source).strip() if geometry_source not in (None, "") else None,
    }


def _alignment_value(row: "NormalizedCourseRow | None", key: str) -> Any:
    if row is None or not isinstance(row.alignment, dict):
        return None

    return row.alignment.get(key)


def _alignment_has_geometry(row: "NormalizedCourseRow | None") -> bool:
    if row is None:
        return False

    return bool(
        _alignment_value(row, "alignment_key")
        or (
            _alignment_value(row, "page_number") is not None
            and _alignment_value(row, "column") is not None
            and (
                _alignment_value(row, "row_in_block") is not None
                or _alignment_value(row, "column_row_index") is not None
                or _alignment_value(row, "visual_row_index") is not None
            )
        )
    )


def _visual_alignment_safely_links(
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
) -> bool:
    """
    Return True only when optional geometry/sequence evidence says both sources
    are describing the same visual row.

    This is intentionally conservative and has no effect when geometry metadata
    is absent.
    """

    if not (_alignment_has_geometry(doc_row) and _alignment_has_geometry(gemini_row)):
        return False

    doc_key = _alignment_value(doc_row, "alignment_key")
    gemini_key = _alignment_value(gemini_row, "alignment_key")

    if doc_key and gemini_key and str(doc_key) == str(gemini_key):
        return True

    doc_page = _alignment_value(doc_row, "page_number")
    gemini_page = _alignment_value(gemini_row, "page_number")

    if doc_page is not None and gemini_page is not None and doc_page != gemini_page:
        return False

    doc_column = _alignment_value(doc_row, "column")
    gemini_column = _alignment_value(gemini_row, "column")

    if doc_column and gemini_column and doc_column != gemini_column:
        return False

    doc_block = _alignment_value(doc_row, "block_index")
    gemini_block = _alignment_value(gemini_row, "block_index")
    doc_row_in_block = _alignment_value(doc_row, "row_in_block")
    gemini_row_in_block = _alignment_value(gemini_row, "row_in_block")

    if (
        doc_block is not None
        and gemini_block is not None
        and doc_row_in_block is not None
        and gemini_row_in_block is not None
    ):
        return doc_block == gemini_block and doc_row_in_block == gemini_row_in_block

    doc_column_row = _alignment_value(doc_row, "column_row_index")
    gemini_column_row = _alignment_value(gemini_row, "column_row_index")

    if doc_column_row is not None and gemini_column_row is not None:
        return abs(int(doc_column_row) - int(gemini_column_row)) <= 1

    doc_visual = _alignment_value(doc_row, "visual_row_index")
    gemini_visual = _alignment_value(gemini_row, "visual_row_index")

    if doc_visual is not None and gemini_visual is not None:
        return abs(int(doc_visual) - int(gemini_visual)) <= 1

    return False


def _visual_alignment_conflicts(
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
) -> bool:
    if not (_alignment_has_geometry(doc_row) and _alignment_has_geometry(gemini_row)):
        return False

    doc_page = _alignment_value(doc_row, "page_number")
    gemini_page = _alignment_value(gemini_row, "page_number")

    if doc_page is not None and gemini_page is not None and doc_page != gemini_page:
        return True

    doc_column = _alignment_value(doc_row, "column")
    gemini_column = _alignment_value(gemini_row, "column")

    if doc_column and gemini_column and doc_column != gemini_column:
        return True

    doc_block = _alignment_value(doc_row, "block_index")
    gemini_block = _alignment_value(gemini_row, "block_index")

    if doc_block is not None and gemini_block is not None and abs(int(doc_block) - int(gemini_block)) > 1:
        return True

    doc_visual = _alignment_value(doc_row, "visual_row_index")
    gemini_visual = _alignment_value(gemini_row, "visual_row_index")

    if doc_visual is not None and gemini_visual is not None and abs(int(doc_visual) - int(gemini_visual)) > 4:
        return True

    return False


def _visual_alignment_score_bonus(
    doc_row: "NormalizedCourseRow",
    gemini_row: "NormalizedCourseRow",
) -> float:
    if _visual_alignment_safely_links(doc_row, gemini_row):
        return 0.08

    if _visual_alignment_conflicts(doc_row, gemini_row):
        return -0.12

    return 0.0


def _visual_alignment_priority_component(
    doc_row: "NormalizedCourseRow",
    gemini_row: "NormalizedCourseRow",
) -> int:
    if _visual_alignment_safely_links(doc_row, gemini_row):
        return 2

    if _alignment_has_geometry(doc_row) and _alignment_has_geometry(gemini_row):
        return 1

    return 0


def _visual_alignment_allows_context_repair(
    doc_row: "NormalizedCourseRow | None",
    gemini_row: "NormalizedCourseRow | None",
    *,
    match_confidence: float | None = None,
) -> bool:
    """
    Allow Gemini to repair year/month/grade-year only when row geometry proves
    both sources are the same visual row and stable fields agree.

    This is a narrow continued-column repair; it does not affect counts.
    """

    if doc_row is None or gemini_row is None:
        return False

    if not _visual_alignment_safely_links(doc_row, gemini_row):
        return False

    if not _gemini_missing_field_confident(gemini_row.confidence):
        return False

    if match_confidence is not None and match_confidence < 0.58:
        return False

    if doc_row.course_name and gemini_row.course_name:
        if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
            return False

    if _course_id_numbers_conflict(doc_row, gemini_row):
        return False

    if doc_row.grade and gemini_row.grade and _same_grade(doc_row, gemini_row) is False:
        return False

    attempted_match = _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
    completed_match = _same_credit(doc_row.credit_completed, gemini_row.credit_completed)

    if attempted_match is False and completed_match is False:
        return False

    return True



# ---------------------------------------------------------------------------
# Normalized row wrappers
# ---------------------------------------------------------------------------

@dataclass
class NormalizedCourseRow:
    source: str
    row: Any
    row_id: int | None
    row_index: int
    course_id: str | None
    course_number: str
    course_prefix: str | None
    course_name: str | None
    grade: str | None
    grade_level: int | None
    month: int | None
    year: int | None
    school_name: str | None
    credit_attempted: float | None
    credit_completed: float | None
    confidence: float | None
    raw_payload: Any
    alignment: dict[str, Any] | None = None


def _normalize_doc_ai_row(row: Any, row_index: int) -> NormalizedCourseRow:
    course_id = _get_attr(
        row,
        "crs_id",
        "course_id",
        "course_id_raw",
    )

    course_name = _get_attr(
        row,
        "crs_description",
        "course_name",
        "name",
        "title",
    )

    grade = _get_attr(
        row,
        "crs_letter_grade",
        "grade",
        "letter_grade",
        "mark",
    )

    credit_attempted = _coerce_float(
        _get_attr(
            row,
            "crs_credit_attempted",
            "credit_attempted",
            "credits_attempted",
            "credits",
        )
    )

    credit_completed = _coerce_float(
        _get_attr(
            row,
            "crs_credit_completed",
            "credit_completed",
            "credits_completed",
            "credits",
        )
    )

    if credit_attempted is None and credit_completed is not None:
        credit_attempted = credit_completed

    if credit_completed is None and credit_attempted is not None:
        credit_completed = credit_attempted

    raw_payload = _get_attr(
        row,
        "raw_payload",
        "raw_json",
        "raw_document_ai_payload",
    )
    school_name = _get_attr(row, "crs_hs", "school", "school_name")
    raw_month = _get_attr(row, "crs_month", "month", "term_month")
    month = _month_to_int(raw_month)

    if month is None:
        month = _mayfair_term_month_from_context(
            _loaded_row_scalar_context(row),
            raw_payload,
            school_name,
            course_name,
            raw_month,
        )

    raw_year_value = _get_attr(row, "crs_year", "year", "term_year", "academic_year")
    year = _repair_year_to_academic_start_year(
        raw_year_value,
        _loaded_row_scalar_context(row),
        raw_payload,
        school_name,
        course_name,
    )

    alignment = _extract_row_alignment_metadata(
        source="document_ai",
        row=row,
        raw_payload=raw_payload,
        fallback_row_index=row_index,
    )

    return NormalizedCourseRow(
        source="document_ai",
        row=row,
        row_id=_row_id(row),
        row_index=_coerce_int(alignment.get("safe_row_index")) or row_index,
        course_id=str(course_id).strip() if course_id not in (None, "") else None,
        course_number=_course_number_from_raw(course_id),
        course_prefix=_course_prefix_from_raw(course_id),
        course_name=str(course_name).strip() if course_name not in (None, "") else None,
        grade=_canonical_grade_value(grade),
        grade_level=_coerce_int(
            _get_attr(row, "crs_grade", "grade_level", "term_grade")
        ),
        month=month,
        year=year,
        school_name=school_name,
        credit_attempted=credit_attempted,
        credit_completed=credit_completed,
        confidence=None,
        raw_payload=raw_payload,
        alignment=alignment,
    )


def _normalize_gemini_row(row: Any, row_index: int) -> NormalizedCourseRow:
    course_id = _get_attr(
        row,
        "crs_id",
        "course_id",
        "course_id_raw",
        "gemini_course_id",
    )

    course_name = _get_attr(
        row,
        "crs_description",
        "course_name",
        "name",
        "title",
    )

    grade = _get_attr(
        row,
        "crs_letter_grade",
        "grade",
        "letter_grade",
        "mark",
    )

    credit_attempted = _coerce_float(
        _get_attr(
            row,
            "crs_credit_attempted",
            "credit_attempted",
            "credits_attempted",
            "credits",
        )
    )

    credit_completed = _coerce_float(
        _get_attr(
            row,
            "crs_credit_completed",
            "credit_completed",
            "credits_completed",
            "credits",
        )
    )

    if credit_attempted is None and credit_completed is not None:
        credit_attempted = credit_completed

    if credit_completed is None and credit_attempted is not None:
        credit_completed = credit_attempted

    confidence = _coerce_float(
        _get_attr(
            row,
            "extraction_confidence",
            "gemini_confidence",
            "confidence",
        )
    )

    raw_payload = _get_attr(
        row,
        "raw_payload",
        "raw_json",
        "raw_gemini_payload",
    )
    school_name = _get_attr(row, "crs_hs", "school", "school_name")
    raw_month = _get_attr(row, "crs_month", "month", "term_month")
    month = _month_to_int(raw_month)

    if month is None:
        month = _mayfair_term_month_from_context(
            _loaded_row_scalar_context(row),
            raw_payload,
            school_name,
            course_name,
            raw_month,
        )

    raw_year_value = _get_attr(row, "crs_year", "year", "term_year", "academic_year")
    year = _repair_year_to_academic_start_year(
        raw_year_value,
        _loaded_row_scalar_context(row),
        raw_payload,
        school_name,
        course_name,
    )

    grade_level = _coerce_int(
        _get_attr(row, "crs_grade", "grade_level", "term_grade")
    )

    # Safe continued-column repair:
    # If Document AI OCR has attached a complete visual-row section context to
    # this Gemini row, use grade_level/month/year together as a bundle. Do not
    # mix one context field from OCR with another field from Gemini/Doc AI.
    ocr_term_bundle = _extract_document_ai_ocr_term_bundle(
        raw_payload=raw_payload,
        course_id=course_id,
        course_name=course_name,
        grade=grade,
        credit_attempted=credit_attempted,
        credit_completed=credit_completed,
    )

    alignment = _extract_row_alignment_metadata(
        source="gemini",
        row=row,
        raw_payload=raw_payload,
        fallback_row_index=_coerce_int(_get_attr(row, "row_index", "course_index")) or row_index,
    )

    if ocr_term_bundle:
        grade_level = ocr_term_bundle["grade_level"]
        month = ocr_term_bundle["month"]
        year = ocr_term_bundle["year"]
        alignment["document_ai_ocr_term_bundle"] = ocr_term_bundle
        alignment["document_ai_ocr_term_bundle_applied"] = True

    return NormalizedCourseRow(
        source="gemini",
        row=row,
        row_id=_row_id(row),
        row_index=_coerce_int(alignment.get("safe_row_index")) or _coerce_int(_get_attr(row, "row_index", "course_index")) or row_index,
        course_id=str(course_id).strip() if course_id not in (None, "") else None,
        course_number=_course_number_from_raw(course_id),
        course_prefix=_course_prefix_from_raw(course_id),
        course_name=str(course_name).strip() if course_name not in (None, "") else None,
        grade=_canonical_grade_value(grade),
        grade_level=grade_level,
        month=month,
        year=year,
        school_name=school_name,
        credit_attempted=credit_attempted,
        credit_completed=credit_completed,
        confidence=confidence,
        raw_payload=raw_payload,
        alignment=alignment,
    )




def _course_payload(row: NormalizedCourseRow | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "row_id": row.row_id,
        "row_index": row.row_index,
        "course_id": row.course_id,
        "course_number": row.course_number,
        "course_prefix": row.course_prefix,
        "course_name": row.course_name,
        "grade": row.grade,
        "base_grade": _base_grade(row.grade),
        "grade_level": row.grade_level,
        "month": row.month,
        "year": row.year,
        "school_name": row.school_name,
        "credit_attempted": row.credit_attempted,
        "credit_completed": row.credit_completed,
        "confidence": row.confidence,
        "grade_scan_evidence": _extract_grade_scan_evidence(row),
        "course_id_scan_evidence": _extract_course_id_scan_evidence(row),
        "alignment": row.alignment or {},
        "raw_payload": row.raw_payload,
    }


# ---------------------------------------------------------------------------
# Canonical PDF row-geometry attachment and safe in-memory repair
# ---------------------------------------------------------------------------

def _geometry_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _normalized_geometry_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    course_id = _geometry_value(row, "course_id", "crs_id")
    course_name = _geometry_value(row, "course_name", "crs_description", "course_title")
    grade = _geometry_value(row, "grade", "crs_letter_grade", "mark")

    credit_attempted = _coerce_float(
        _geometry_value(row, "credit_attempted", "crs_credit_attempted", "credits_attempted")
    )
    credit_completed = _coerce_float(
        _geometry_value(row, "credit_completed", "crs_credit_completed", "credits_completed")
    )

    if credit_attempted is None and credit_completed is not None:
        credit_attempted = credit_completed

    if credit_completed is None and credit_attempted is not None:
        credit_completed = credit_attempted

    visual_column = _normalize_alignment_column(
        _geometry_value(row, "visual_column", "column")
    )

    page_number = _coerce_int(_geometry_value(row, "page_number", "page"))
    column_index = _coerce_int(_geometry_value(row, "column_index"))
    block_index = _coerce_int(_geometry_value(row, "block_index", "section_index"))
    row_in_block = _coerce_int(_geometry_value(row, "row_in_block", "section_row_index"))
    geometry_row_index = _coerce_int(_geometry_value(row, "geometry_row_index", "visual_row_index")) or index

    alignment_key = _geometry_value(row, "geometry_alignment_key", "alignment_key")
    if not alignment_key:
        alignment_key = f"p{page_number or 0}:c{column_index or 0}:b{block_index or 0}:r{row_in_block or geometry_row_index}"

    normalized = {
        "geometry_row_index": geometry_row_index,
        "page_number": page_number,
        "visual_column": visual_column,
        "column_index": column_index,
        "block_index": block_index,
        "row_in_block": row_in_block,
        "section_name": _geometry_value(row, "section_name"),
        "section_key": _geometry_value(row, "section_key"),
        "term_name": _geometry_value(row, "term_name"),
        "school_name": _geometry_value(row, "school_name"),
        "grade_level": _coerce_int(_geometry_value(row, "grade_level", "grade_year", "crs_grade")),
        "year": _year_to_int(_geometry_value(row, "year", "crs_year")),
        "month": _month_to_int(_geometry_value(row, "month", "crs_month")),
        "course_id": str(course_id).strip() if course_id not in (None, "") else None,
        "course_number": _course_number_from_raw(course_id),
        "course_prefix": _course_prefix_from_raw(course_id),
        "course_name": str(course_name).strip() if course_name not in (None, "") else None,
        "grade": _canonical_grade_value(grade),
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "row_bbox": _normalize_bbox(_geometry_value(row, "row_bbox")),
        "raw_word_bbox": _normalize_bbox(_geometry_value(row, "raw_word_bbox")),
        "field_bboxes": row.get("field_bboxes") if isinstance(row.get("field_bboxes"), dict) else {},
        "line_text": _geometry_value(row, "line_text", "raw_text"),
        "visual_sort_key": row.get("visual_sort_key"),
        "geometry_alignment_key": str(alignment_key),
        "geometry_source": _geometry_value(row, "geometry_source") or "transcript_row_geometry",
    }

    return normalized


def _normalize_geometry_rows(geometry_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not geometry_rows:
        return []

    normalized: list[dict[str, Any]] = []

    for index, row in enumerate(geometry_rows, start=1):
        if not isinstance(row, dict):
            continue

        normalized_row = _normalized_geometry_row(row, index)

        if not normalized_row.get("course_name") and not normalized_row.get("course_id"):
            continue

        normalized.append(normalized_row)

    return normalized


def _geometry_credit_matches_source(row: NormalizedCourseRow, geometry_row: dict[str, Any]) -> bool:
    attempted_match = _same_credit(row.credit_attempted, geometry_row.get("credit_attempted"))
    completed_match = _same_credit(row.credit_completed, geometry_row.get("credit_completed"))

    return attempted_match is True or completed_match is True


def _score_geometry_row_against_source_row(
    source_row: NormalizedCourseRow,
    geometry_row: dict[str, Any],
) -> float:
    """
    Score whether a raw Doc AI/Gemini row represents a deterministic PDF visual row.

    This does not change counts. It only lets reconciliation attach a canonical
    visual-row witness when the match is strong enough.
    """

    name_score = _names_similar(source_row.course_name, geometry_row.get("course_name"))

    source_number = source_row.course_number
    geometry_number = str(geometry_row.get("course_number") or "")

    id_match = bool(source_number and geometry_number and source_number == geometry_number)
    id_conflict = bool(source_number and geometry_number and source_number != geometry_number)

    grade_match = _base_grade(source_row.grade) and _base_grade(source_row.grade) == _base_grade(geometry_row.get("grade"))
    credit_match = _geometry_credit_matches_source(source_row, geometry_row)

    grade_level_match = _same_int(source_row.grade_level, geometry_row.get("grade_level"))
    year_match = _same_int(source_row.year, geometry_row.get("year"))
    month_match = _same_int(source_row.month, geometry_row.get("month"))

    score = 0.0
    score += name_score * 0.40

    if id_match:
        score += 0.25
    elif id_conflict:
        # Allow canonical repair for the exact bug we are fixing:
        # the course title belongs to one row but the ID was borrowed from a nearby row.
        # A strong name/grade/credit/term match can still link the source row to geometry.
        score -= 0.06

    if grade_match:
        score += 0.08

    if credit_match:
        score += 0.10

    if grade_level_match is True:
        score += 0.04
    elif grade_level_match is False:
        score -= 0.03

    if year_match is True:
        score += 0.04
    elif year_match is False:
        score -= 0.03

    if month_match is True:
        score += 0.04
    elif month_match is False:
        score -= 0.02

    row_distance = abs((source_row.row_index or 0) - int(geometry_row.get("geometry_row_index") or 0))
    if row_distance <= 1:
        score += 0.05
    elif row_distance <= 3:
        score += 0.03
    elif row_distance <= 6:
        score += 0.01

    # If course IDs conflict and the names are not strongly related, do not attach.
    if id_conflict and name_score < 0.86:
        score = min(score, 0.58)

    # If the name is weak and the ID is missing/conflicting, do not use row order alone.
    if name_score < 0.70 and not id_match:
        score = min(score, 0.62)

    return max(0.0, min(round(score, 3), 1.0))


def _geometry_attachment_candidates(
    rows: list[NormalizedCourseRow],
    geometry_rows: list[dict[str, Any]],
) -> list[tuple[float, int, int]]:
    candidates: list[tuple[float, int, int]] = []

    for source_index, source_row in enumerate(rows):
        for geometry_index, geometry_row in enumerate(geometry_rows):
            score = _score_geometry_row_against_source_row(source_row, geometry_row)

            if score >= TRANSCRIPT_GEOMETRY_MATCH_THRESHOLD:
                candidates.append((score, source_index, geometry_index))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def _attach_geometry_row_to_source_row(
    source_row: NormalizedCourseRow,
    geometry_row: dict[str, Any],
    *,
    match_score: float,
) -> None:
    alignment = dict(source_row.alignment or {})
    geometry_key = geometry_row.get("geometry_alignment_key")

    alignment.update(
        {
            "geometry_source": geometry_row.get("geometry_source") or "transcript_row_geometry",
            "geometry_match_score": match_score,
            "geometry_alignment_key": geometry_key,
            "geometry_row_index": geometry_row.get("geometry_row_index"),
            "geometry_canonical_row": geometry_row,
            "geometry_page_number": geometry_row.get("page_number"),
            "geometry_visual_column": geometry_row.get("visual_column"),
            "geometry_column_index": geometry_row.get("column_index"),
            "geometry_block_index": geometry_row.get("block_index"),
            "geometry_row_in_block": geometry_row.get("row_in_block"),
            "geometry_section_name": geometry_row.get("section_name"),
            "geometry_section_key": geometry_row.get("section_key"),
            "geometry_row_bbox": geometry_row.get("row_bbox"),
            "geometry_raw_word_bbox": geometry_row.get("raw_word_bbox"),
            "geometry_line_text": geometry_row.get("line_text"),
        }
    )

    # Make existing visual-alignment helpers recognize the canonical geometry row.
    # This is intentionally done only after a strong deterministic match.
    if match_score >= TRANSCRIPT_GEOMETRY_STRONG_MATCH_THRESHOLD and geometry_key:
        alignment["alignment_key"] = geometry_key
        alignment["page_number"] = geometry_row.get("page_number")
        alignment["column"] = geometry_row.get("visual_column")
        alignment["visual_row_index"] = geometry_row.get("geometry_row_index")
        alignment["block_index"] = geometry_row.get("block_index")
        alignment["row_in_block"] = geometry_row.get("row_in_block")
        alignment["section_name"] = geometry_row.get("section_name")
        alignment["section_key"] = geometry_row.get("section_key")
        alignment["row_bbox"] = geometry_row.get("row_bbox")
        alignment["raw_word_bbox"] = geometry_row.get("raw_word_bbox")

    source_row.alignment = alignment


def _source_row_is_safe_for_geometry_repair(
    row: NormalizedCourseRow,
    geometry_row: dict[str, Any],
    *,
    match_score: float,
) -> bool:
    if match_score < TRANSCRIPT_GEOMETRY_REPAIR_THRESHOLD:
        return False

    geometry_name = geometry_row.get("course_name")
    geometry_id = geometry_row.get("course_id")

    name_matches = _course_names_same_identity(row.course_name, geometry_name)
    id_matches = bool(
        row.course_number
        and geometry_row.get("course_number")
        and row.course_number == geometry_row.get("course_number")
    )
    grade_matches = bool(
        row.grade
        and geometry_row.get("grade")
        and _base_grade(row.grade) == _base_grade(geometry_row.get("grade"))
    )
    credit_matches = _geometry_credit_matches_source(row, geometry_row)

    # At least one stable identity anchor is required. This prevents a weak
    # visual-order match from rewriting a correct row.
    return bool(
        name_matches
        or id_matches
        or (grade_matches and credit_matches)
    )


def _repair_source_row_from_geometry_if_safe(
    row: NormalizedCourseRow,
) -> None:
    alignment = row.alignment or {}
    geometry_row = alignment.get("geometry_canonical_row")

    if not isinstance(geometry_row, dict):
        return

    match_score = _coerce_float(alignment.get("geometry_match_score")) or 0.0

    if not _source_row_is_safe_for_geometry_repair(
        row,
        geometry_row,
        match_score=match_score,
    ):
        return

    repaired_fields: list[str] = []

    geometry_course_id = geometry_row.get("course_id")
    geometry_course_name = geometry_row.get("course_name")
    geometry_grade = geometry_row.get("grade")
    geometry_grade_level = _coerce_int(geometry_row.get("grade_level"))
    geometry_month = _month_to_int(geometry_row.get("month"))
    geometry_year = _year_to_int(geometry_row.get("year"))
    geometry_credit_attempted = _coerce_float(geometry_row.get("credit_attempted"))
    geometry_credit_completed = _coerce_float(geometry_row.get("credit_completed"))
    geometry_school_name = geometry_row.get("school_name")

    # Correct internal row-shift cases, for example:
    #   p 1110 + Health  -> 6875 + Health
    #   p 2800 + Intgtd Math II -> p 7511 + Intgtd Math II
    if geometry_course_id and _is_valid_course_id_value(geometry_course_id):
        current_number = row.course_number
        geometry_number = _course_number_from_raw(geometry_course_id)

        should_repair_id = (
            not _is_valid_course_id_value(row.course_id)
            or (
                geometry_course_name
                and _course_names_same_identity(row.course_name, geometry_course_name)
                and geometry_number
                and current_number != geometry_number
            )
            or (
                current_number
                and geometry_number
                and current_number == geometry_number
                and str(row.course_id or "").strip() != str(geometry_course_id).strip()
            )
        )

        if should_repair_id:
            row.course_id = str(geometry_course_id).strip()
            row.course_number = _course_number_from_raw(row.course_id)
            row.course_prefix = _course_prefix_from_raw(row.course_id)
            repaired_fields.append("course_id")

    if geometry_course_name and not _looks_like_wrong_column_course_name(geometry_course_name):
        should_repair_name = (
            not row.course_name
            or _looks_like_wrong_column_course_name(row.course_name)
            or (
                row.course_number
                and geometry_row.get("course_number")
                and row.course_number == geometry_row.get("course_number")
                and not _course_names_same_identity(row.course_name, geometry_course_name)
            )
        )

        if should_repair_name:
            row.course_name = str(geometry_course_name).strip()
            repaired_fields.append("course_name")

    if geometry_grade and _is_valid_grade(geometry_grade):
        should_repair_grade = (
            not _is_valid_grade(row.grade)
            or (
                row.course_name
                and geometry_course_name
                and _course_names_same_identity(row.course_name, geometry_course_name)
                and _base_grade(row.grade) != _base_grade(geometry_grade)
                and match_score >= 0.92
            )
        )

        if should_repair_grade:
            row.grade = _canonical_grade_value(geometry_grade)
            repaired_fields.append("grade")

    if geometry_grade_level is not None and _is_valid_grade_level(geometry_grade_level):
        if row.grade_level != geometry_grade_level:
            row.grade_level = geometry_grade_level
            repaired_fields.append("grade_level")

    if geometry_month is not None:
        if row.month != geometry_month:
            row.month = geometry_month
            repaired_fields.append("month")

    if geometry_year is not None:
        if row.year != geometry_year:
            row.year = geometry_year
            repaired_fields.append("year")

    if geometry_credit_attempted is not None and _is_plausible_credit(geometry_credit_attempted):
        if row.credit_attempted is None or _is_bad_credit(row.credit_attempted):
            row.credit_attempted = geometry_credit_attempted
            repaired_fields.append("credit_attempted")

    if geometry_credit_completed is not None and _is_plausible_credit(geometry_credit_completed):
        if row.credit_completed is None or _is_bad_credit(row.credit_completed):
            row.credit_completed = geometry_credit_completed
            repaired_fields.append("credit_completed")

    if geometry_school_name and not row.school_name:
        row.school_name = str(geometry_school_name).strip()
        repaired_fields.append("school_name")

    if repaired_fields:
        alignment["geometry_applied"] = True
        alignment["geometry_applied_fields"] = sorted(set(repaired_fields))
        row.alignment = alignment


def _attach_transcript_geometry_to_rows(
    *,
    document_ai_rows: list[NormalizedCourseRow],
    gemini_rows: list[NormalizedCourseRow],
    geometry_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Attach deterministic PDF visual-row evidence to loaded raw rows.

    This is intentionally in-memory only. It does not change course_details or
    gemini_course_details. It does not change final count rules. If geometry is
    missing or weak, existing reconciliation behavior remains unchanged.
    """

    normalized_geometry = _normalize_geometry_rows(geometry_rows)

    if not normalized_geometry:
        return {
            "geometry_rows": 0,
            "document_ai_rows_attached": 0,
            "gemini_rows_attached": 0,
            "document_ai_rows_repaired": 0,
            "gemini_rows_repaired": 0,
        }

    def attach_for_source(rows: list[NormalizedCourseRow]) -> tuple[int, int]:
        candidates = _geometry_attachment_candidates(rows, normalized_geometry)
        used_source_indexes: set[int] = set()
        used_geometry_indexes: set[int] = set()
        attached = 0

        for score, source_index, geometry_index in candidates:
            if source_index in used_source_indexes or geometry_index in used_geometry_indexes:
                continue

            source_row = rows[source_index]
            geometry_row = normalized_geometry[geometry_index]

            _attach_geometry_row_to_source_row(
                source_row,
                geometry_row,
                match_score=score,
            )

            used_source_indexes.add(source_index)
            used_geometry_indexes.add(geometry_index)
            attached += 1

        repaired = 0

        for source_row in rows:
            before = json.dumps(source_row.alignment or {}, default=str, sort_keys=True)
            _repair_source_row_from_geometry_if_safe(source_row)
            after_alignment = source_row.alignment or {}

            if after_alignment.get("geometry_applied"):
                repaired += 1

        return attached, repaired

    document_ai_attached, document_ai_repaired = attach_for_source(document_ai_rows)
    gemini_attached, gemini_repaired = attach_for_source(gemini_rows)

    return {
        "geometry_rows": len(normalized_geometry),
        "document_ai_rows_attached": document_ai_attached,
        "gemini_rows_attached": gemini_attached,
        "document_ai_rows_repaired": document_ai_repaired,
        "gemini_rows_repaired": gemini_repaired,
    }


# ---------------------------------------------------------------------------
# Row comparison helpers
# ---------------------------------------------------------------------------

def _same_course_id(
    doc_row: NormalizedCourseRow | None,
    gemini_row: NormalizedCourseRow | None,
) -> bool | None:
    if doc_row is None or gemini_row is None:
        return None

    doc_id = doc_row.course_id
    gemini_id = gemini_row.course_id

    if doc_id in (None, "") and gemini_id in (None, ""):
        return None

    if doc_id in (None, "") or gemini_id in (None, ""):
        return False

    if str(doc_id).strip().upper() == str(gemini_id).strip().upper():
        return True

    if doc_row.course_number and gemini_row.course_number:
        return doc_row.course_number == gemini_row.course_number

    return False


def _same_name(
    doc_row: NormalizedCourseRow | None,
    gemini_row: NormalizedCourseRow | None,
) -> bool | None:
    if doc_row is None or gemini_row is None:
        return None

    if not doc_row.course_name and not gemini_row.course_name:
        return None

    if not doc_row.course_name or not gemini_row.course_name:
        return False

    return _names_similar(doc_row.course_name, gemini_row.course_name) >= 0.88


def _same_grade(
    doc_row: NormalizedCourseRow | None,
    gemini_row: NormalizedCourseRow | None,
) -> bool | None:
    if doc_row is None or gemini_row is None:
        return None

    doc_grade = _base_grade(doc_row.grade)
    gemini_grade = _base_grade(_grade_scan_grade(gemini_row) or gemini_row.grade)

    if not doc_grade and not gemini_grade:
        return None

    if not doc_grade or not gemini_grade:
        return False

    return doc_grade == gemini_grade


def _same_int(left: Any, right: Any) -> bool | None:
    left_int = _coerce_int(left)
    right_int = _coerce_int(right)

    if left_int is None and right_int is None:
        return None

    if left_int is None or right_int is None:
        return False

    return left_int == right_int


def _year_hard_conflict(left: Any, right: Any) -> bool:
    """
    True only when two academic years genuinely disagree (>= 2 years apart).

    Document AI and Gemini routinely report the two ends of the SAME academic
    year (e.g. 2021 vs 2022 for "2021-2022"), so an off-by-one difference is the
    same term under a different convention and must never block a match.
    """
    left_year = _year_to_int(left)
    right_year = _year_to_int(right)

    if left_year is None or right_year is None:
        return False

    return abs(left_year - right_year) >= 2


def _same_credit(left: Any, right: Any) -> bool | None:
    left_float = _coerce_float(left)
    right_float = _coerce_float(right)

    if left_float is None and right_float is None:
        return None

    if left_float is None or right_float is None:
        return False

    return _credits_equal(left_float, right_float)


# ---------------------------------------------------------------------------
# Matching and field decision logic
# ---------------------------------------------------------------------------

def _term_context_key(row: NormalizedCourseRow | None) -> tuple[int | None, int | None, int | None]:
    """
    Transcript term/block identity.

    Mayfair-style transcripts repeat the same course names across Fall/Spring
    blocks. Matching must respect term context first, then course identity. A
    missing value is treated as unknown, but explicit disagreements are hard
    mismatches.
    """

    if row is None:
        return (None, None, None)

    return (
        _coerce_int(row.grade_level),
        _year_to_int(row.year),
        _month_to_int(row.month),
    )


def _complete_term_context(row: NormalizedCourseRow | None) -> bool:
    grade_level, year, month = _term_context_key(row)
    return grade_level is not None and year is not None and month is not None


def _term_context_compatible(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> bool:
    """
    Return False when both extractors provide conflicting term context.

    This prevents rows like Grade 7 Spring Spanish 1A from being matched to a
    later Grade 11 Summer Mod World History row only because row order drifted
    or a course name was copied into the wrong row.
    """

    doc_grade, doc_year, doc_month = _term_context_key(doc_row)
    gem_grade, gem_year, gem_month = _term_context_key(gemini_row)

    # Grade level and month are hard term anchors.
    for left, right in [
        (doc_grade, gem_grade),
        (doc_month, gem_month),
    ]:
        if left is not None and right is not None and left != right:
            return False

    # Academic year: Document AI and Gemini routinely report the two ends of the
    # SAME academic year (e.g. 2021 vs 2022 for "2021-2022"). With grade level and
    # month already aligned, an off-by-one year is the same term under a different
    # convention (a student is in a given grade for only one academic year). Only a
    # gap of 2+ years is a genuine term mismatch.
    if doc_year is not None and gem_year is not None and abs(doc_year - gem_year) >= 2:
        return False

    return True


def _term_context_match_count(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> int:
    doc_grade, doc_year, doc_month = _term_context_key(doc_row)
    gem_grade, gem_year, gem_month = _term_context_key(gemini_row)

    return sum(
        1
        for left, right in [
            (doc_grade, gem_grade),
            (doc_year, gem_year),
            (doc_month, gem_month),
        ]
        if left is not None and right is not None and left == right
    )


def _course_id_numbers_conflict(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> bool:
    return bool(
        doc_row.course_number
        and gemini_row.course_number
        and doc_row.course_number != gemini_row.course_number
    )


def _row_identity_is_extremely_safe_despite_course_id_conflict(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    name_score: float | None = None,
) -> bool:
    """
    Very narrow exception for course-ID conflicts.

    Normally different numeric course IDs mean different transcript rows. The
    only safe exception is when every other row-identity field proves the same
    visible row. This prevents silent wrong merges while still allowing rare OCR
    course-ID mistakes to be linked for review/final field reconciliation.
    """

    if name_score is None:
        name_score = _names_similar(doc_row.course_name, gemini_row.course_name)

    if name_score < COURSE_ID_CONFLICT_NAME_AUTO_MATCH_THRESHOLD:
        return False

    if _complete_term_context(doc_row) and _complete_term_context(gemini_row):
        if _term_context_key(doc_row) != _term_context_key(gemini_row):
            return False

    if _term_context_match_count(doc_row, gemini_row) < 2:
        return False

    if _same_grade(doc_row, gemini_row) is not True:
        return False

    if not (
        _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted) is True
        or _same_credit(doc_row.credit_completed, gemini_row.credit_completed) is True
    ):
        return False

    return True


def _score_match(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> float:
    visual_alignment_safe = _visual_alignment_safely_links(doc_row, gemini_row)

    if not _term_context_compatible(doc_row, gemini_row) and not visual_alignment_safe:
        return 0.0

    if _visual_alignment_conflicts(doc_row, gemini_row):
        return 0.0

    name_score = _names_similar(doc_row.course_name, gemini_row.course_name)
    same_course_id = _same_course_id(doc_row, gemini_row)

    # Course ID conflict is a high-risk row-identity problem. Do not let name
    # similarity or row order compensate unless the surrounding term/grade/credit
    # context is extremely safe.
    if _course_id_numbers_conflict(doc_row, gemini_row):
        if not _row_identity_is_extremely_safe_despite_course_id_conflict(
            doc_row,
            gemini_row,
            name_score=name_score,
        ):
            return 0.0

    score = 0.0
    score += name_score * 0.30

    if same_course_id is True:
        score += 0.34
    elif same_course_id is False:
        score -= 0.20

    same_grade = _same_grade(doc_row, gemini_row)

    if same_grade is True:
        score += 0.08
    elif same_grade is False:
        score -= 0.03

    if _credits_equal(doc_row.credit_completed, gemini_row.credit_completed):
        score += 0.07
    elif _credits_equal(doc_row.credit_attempted, gemini_row.credit_attempted):
        score += 0.05

    grade_level_match = _same_int(doc_row.grade_level, gemini_row.grade_level)
    year_match = _same_int(doc_row.year, gemini_row.year)
    month_match = _same_int(doc_row.month, gemini_row.month)

    if grade_level_match is True:
        score += 0.06
    elif grade_level_match is False:
        if visual_alignment_safe:
            score -= 0.02
        else:
            return 0.0

    if year_match is True:
        score += 0.06
    elif year_match is False:
        # An off-by-one academic year (2021 vs 2022 for "2021-2022") is the same
        # term under a different convention, not a real conflict. Only veto on a
        # genuine gap of 2+ years.
        doc_year_int = _year_to_int(doc_row.year)
        gem_year_int = _year_to_int(gemini_row.year)
        hard_year_conflict = (
            doc_year_int is not None
            and gem_year_int is not None
            and abs(doc_year_int - gem_year_int) >= 2
        )
        if visual_alignment_safe or not hard_year_conflict:
            score -= 0.02
        else:
            return 0.0

    if month_match is True:
        score += 0.10
    elif month_match is False:
        if visual_alignment_safe:
            score -= 0.02
        else:
            return 0.0

    school_score = _names_similar(doc_row.school_name, gemini_row.school_name)
    if school_score >= 0.90:
        score += 0.02

    score += _visual_alignment_score_bonus(doc_row, gemini_row)

    # Row order is intentionally tiny. It is a tie-breaker only.
    row_distance = abs((doc_row.row_index or 0) - (gemini_row.row_index or 0))

    if row_distance <= 1:
        score += 0.008
    elif row_distance <= 3:
        score += 0.004

    return max(0.0, min(round(score, 3), 1.0))


def _candidate_is_reasonable(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    score: float,
) -> bool:
    if score < MATCH_THRESHOLD:
        return False

    visual_alignment_safe = _visual_alignment_safely_links(doc_row, gemini_row)

    if not _term_context_compatible(doc_row, gemini_row) and not visual_alignment_safe:
        return False

    if _visual_alignment_conflicts(doc_row, gemini_row):
        return False

    name_score = _names_similar(doc_row.course_name, gemini_row.course_name)
    same_course_id = _same_course_id(doc_row, gemini_row)
    same_grade = _same_grade(doc_row, gemini_row)
    same_month = _same_int(doc_row.month, gemini_row.month)
    same_year = _same_int(doc_row.year, gemini_row.year)
    same_grade_level = _same_int(doc_row.grade_level, gemini_row.grade_level)
    same_credit = (
        _same_credit(doc_row.credit_completed, gemini_row.credit_completed)
        or _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
    )

    # Explicit term/block mismatches mean different transcript rows unless
    # optional geometry proves this is the same visual row. That narrow exception
    # allows continued-column term-context repair without changing counts.
    # An off-by-one academic year is NOT a mismatch (same term, different
    # start/end-year convention) — only a real 2+ year gap counts.
    if same_month is False or _year_hard_conflict(doc_row.year, gemini_row.year) or same_grade_level is False:
        if not visual_alignment_safe:
            return False

        if not (
            name_score >= 0.86
            and (
                same_credit is True
                or same_grade is True
                or _same_course_id(doc_row, gemini_row) is True
            )
        ):
            return False

    # Hard course-ID protection. If both rows have numeric IDs and the numbers
    # differ, do not match unless all other identity fields are extremely safe.
    if _course_id_numbers_conflict(doc_row, gemini_row):
        if not _row_identity_is_extremely_safe_despite_course_id_conflict(
            doc_row,
            gemini_row,
            name_score=name_score,
        ):
            return False

    if same_course_id is False and _same_name(doc_row, gemini_row) is False:
        return False

    strong_identity = same_course_id is True or name_score >= 0.88

    supporting_matches = 0

    if same_grade is True:
        supporting_matches += 1

    if same_credit is True:
        supporting_matches += 1

    if same_grade_level is True:
        supporting_matches += 1

    if same_year is True:
        supporting_matches += 1

    if same_month is True:
        supporting_matches += 1

    # When course IDs are missing on one side, require stronger term/value
    # support before trusting the pair.
    if same_course_id is None or same_course_id is False:
        return bool(name_score >= 0.90 and supporting_matches >= 3)

    if strong_identity and supporting_matches >= 1:
        return True

    if name_score >= 0.92 and supporting_matches >= 2:
        return True

    return False


def _candidate_priority(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    score: float,
) -> tuple[float, int, int, int, float]:
    row_distance = abs((doc_row.row_index or 0) - (gemini_row.row_index or 0))
    return (
        score,
        _visual_alignment_priority_component(doc_row, gemini_row),
        _term_context_match_count(doc_row, gemini_row),
        1 if _same_course_id(doc_row, gemini_row) is True else 0,
        -float(row_distance) / 1000.0,
    )


def _match_rows(
    document_ai_rows: list[NormalizedCourseRow],
    gemini_rows: list[NormalizedCourseRow],
) -> tuple[
    list[tuple[NormalizedCourseRow, NormalizedCourseRow, float]],
    list[NormalizedCourseRow],
    list[NormalizedCourseRow],
]:
    candidates: list[tuple[tuple[float, int, int, int, float], float, int, int]] = []

    for doc_index, doc_row in enumerate(document_ai_rows):
        for gemini_index, gemini_row in enumerate(gemini_rows):
            score = _score_match(doc_row, gemini_row)

            if _candidate_is_reasonable(doc_row, gemini_row, score):
                candidates.append(
                    (
                        _candidate_priority(doc_row, gemini_row, score),
                        score,
                        doc_index,
                        gemini_index,
                    )
                )

    candidates.sort(key=lambda item: item[0], reverse=True)

    used_doc_indexes: set[int] = set()
    used_gemini_indexes: set[int] = set()
    matched: list[tuple[NormalizedCourseRow, NormalizedCourseRow, float]] = []

    for _priority, score, doc_index, gemini_index in candidates:
        if doc_index in used_doc_indexes or gemini_index in used_gemini_indexes:
            continue

        doc_row = document_ai_rows[doc_index]
        gemini_row = gemini_rows[gemini_index]

        # Ambiguity guard: if another still-available candidate for the same
        # Doc AI row is essentially tied, do not let row order decide. Leaving
        # it source-only is safer than silently pairing the wrong term/course.
        best_alternative_score = 0.0
        for _alt_priority, alt_score, alt_doc_index, alt_gemini_index in candidates:
            if alt_doc_index == doc_index and alt_gemini_index == gemini_index:
                continue

            if alt_doc_index in used_doc_indexes or alt_gemini_index in used_gemini_indexes:
                continue

            if alt_doc_index == doc_index or alt_gemini_index == gemini_index:
                best_alternative_score = max(best_alternative_score, alt_score)

        if (
            best_alternative_score > 0
            and score < 0.90
            and score - best_alternative_score < ROW_CONTEXT_AMBIGUITY_MARGIN
            and _same_course_id(doc_row, gemini_row) is not True
        ):
            continue

        used_doc_indexes.add(doc_index)
        used_gemini_indexes.add(gemini_index)

        matched.append((doc_row, gemini_row, score))

    doc_only = [
        row
        for index, row in enumerate(document_ai_rows)
        if index not in used_doc_indexes
    ]

    gemini_only = [
        row
        for index, row in enumerate(gemini_rows)
        if index not in used_gemini_indexes
    ]

    matched.sort(
        key=lambda item: (
            item[0].year or item[1].year or 0,
            item[0].grade_level or item[1].grade_level or 0,
            item[0].month or item[1].month or 0,
            item[0].row_index or item[1].row_index or 0,
        )
    )

    doc_only.sort(
        key=lambda row: (
            row.year or 0,
            row.grade_level or 0,
            row.month or 0,
            row.row_index,
        )
    )

    gemini_only.sort(
        key=lambda row: (
            row.year or 0,
            row.grade_level or 0,
            row.month or 0,
            row.row_index or 0,
        )
    )

    return matched, doc_only, gemini_only


def _is_required_complete(row: NormalizedCourseRow) -> bool:
    # Non-St. Anthony required fields. Month is intentionally not required.
    # A wrong-column course name such as "5.00/5.00 B" does not count as a
    # valid course name.
    return bool(
        row.course_id
        and row.course_name
        and not _looks_like_wrong_column_course_name(row.course_name)
        and row.grade
        and row.grade_level is not None
        and row.year is not None
        and row.credit_attempted is not None
        and row.credit_completed is not None
    )


def _is_row_believable(row: NormalizedCourseRow) -> bool:
    if not row.course_name:
        return False

    if _looks_like_wrong_column_course_name(row.course_name):
        return False

    if row.grade and not _is_valid_grade(row.grade):
        return False

    if row.grade_level is not None and not _is_valid_grade_level(row.grade_level):
        return False

    if row.credit_attempted is not None and not _is_plausible_credit(row.credit_attempted):
        return False

    if row.credit_completed is not None and not _is_plausible_credit(row.credit_completed):
        return False

    return True


def _row_identity_extremely_safe_for_verifier(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    match_confidence: float | None,
    threshold: float,
) -> bool:
    if match_confidence is not None and match_confidence < threshold:
        return False

    if _same_int(doc_row.year, gemini_row.year) is False:
        return False

    if _same_int(doc_row.month, gemini_row.month) is False:
        return False

    if _same_int(doc_row.grade_level, gemini_row.grade_level) is False:
        return False

    if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
        return False

    attempted_match = _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
    completed_match = _same_credit(doc_row.credit_completed, gemini_row.credit_completed)

    if attempted_match is False and completed_match is False:
        return False

    return True


def _pick_text_field(
    field_name: str,
    doc_value: Any,
    gemini_value: Any,
    *,
    require_similarity: bool = False,
    gemini_confidence: float | None = None,
    doc_row: "NormalizedCourseRow | None" = None,
    gemini_row: "NormalizedCourseRow | None" = None,
    match_confidence: float | None = None,
) -> tuple[Any, str, bool, str | None]:
    gemini_is_confident = _gemini_confident(gemini_confidence)
    gemini_has_strong_proof = _gemini_has_strong_proof(gemini_confidence)

    if doc_value in (None, "") and gemini_value not in (None, ""):
        return _gemini_missing_field_auto_fill_decision(
            field_name=field_name,
            gemini_value=gemini_value,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=field_name in {"course_name"},
        )

    if gemini_value in (None, "") and doc_value not in (None, ""):
        return doc_value, "document_ai", False, None

    if doc_value in (None, "") and gemini_value in (None, ""):
        return None, "missing", True, f"{field_name} is missing from both sources."

    doc_text = str(doc_value).strip()
    gemini_text = str(gemini_value).strip()

    if doc_text == gemini_text:
        return doc_value, "both", False, None

    # Document AI is the default trusted source. Gemini may improve visible
    # course names, but only when it strongly proves the better value. If Gemini
    # cannot prove Document AI wrong, keep Document AI and do not send the row
    # to Needs Review just because the two text values differ.
    if field_name == "course_name":
        doc_norm = _normalize_course_name(doc_value)
        gemini_norm = _normalize_course_name(gemini_value)
        similarity = _names_similar(doc_value, gemini_value)

        doc_wrong_column = _looks_like_wrong_column_course_name(doc_value)
        gemini_wrong_column = _looks_like_wrong_column_course_name(gemini_value)

        if doc_wrong_column and not gemini_wrong_column and gemini_text:
            return _gemini_missing_field_auto_fill_decision(
                field_name="course_name",
                gemini_value=gemini_value,
                gemini_confidence=gemini_confidence,
                doc_row=doc_row,
                gemini_row=gemini_row,
                match_confidence=match_confidence,
                high_risk=True,
            )

        if gemini_wrong_column and not doc_wrong_column and doc_text:
            return doc_value, "document_ai_gemini_course_name_wrong_column", False, None

        if doc_norm and gemini_norm and doc_norm == gemini_norm:
            if len(gemini_text) > len(doc_text) and _gemini_missing_field_confident(gemini_confidence):
                return gemini_value, "gemini_more_complete_normalized_match_92", False, None

            return doc_value, "both_normalized_document_ai_kept", False, None

        if (
            _gemini_missing_field_confident(gemini_confidence)
            and gemini_norm
            and len(gemini_norm) >= 4
            and similarity >= COURSE_NAME_GEMINI_AUTO_FIX_SIMILARITY_THRESHOLD
        ):
            return gemini_value, "gemini_confident_92_course_name_auto_fix", False, None

        if (
            _gemini_missing_field_confident(gemini_confidence)
            and gemini_norm
            and doc_norm
            and len(gemini_norm) >= len(doc_norm) + 8
            and similarity >= 0.80
        ):
            return gemini_value, "gemini_confident_92_more_complete_course_name_auto_fill", False, None

        return doc_value, "document_ai_default_course_name_kept", False, None

    if require_similarity:
        similarity = _names_similar(doc_value, gemini_value)

        if similarity >= 0.92:
            return doc_value, "both_similar_document_ai_kept", False, None

    if gemini_has_strong_proof and _has_value(gemini_value):
        # For non-course-name text fields, Gemini must meet the same 92% rule
        # before it can replace a usable Document AI value.
        if _gemini_missing_field_confident(gemini_confidence):
            return gemini_value, "gemini_confident_92_auto_fix", False, None

    return doc_value, "document_ai_default_kept", False, None



def _pick_course_id(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    match_confidence: float | None = None,
    course_id_scan_evidence: dict[str, Any] | None = None,
) -> tuple[Any, str, bool, str | None]:
    """
    Course ID decision rule using calculated proof plus safe OCR majority.

    - Valid Document AI course ID wins by default.
    - Gemini/verifier self-confidence alone cannot overwrite Document AI.
    - If Document AI OCR visual-row text confirms the same row and exposes a
      printed Course ID, that OCR Course ID can act as the third evidence
      source for a safe majority / repair.
    - calculated_proof < 85%:
        keep Document AI, allow completion.
    - calculated_proof 85%-98%:
        keep Document AI value, send Needs Review.
    - calculated_proof >= 98% AND row identity is extremely safe:
        use Gemini/verifier, allow completion.
    """

    doc_id = doc_row.course_id
    gemini_id = gemini_row.course_id

    doc_valid = _is_valid_course_id_value(doc_id)
    gemini_valid = _is_valid_course_id_value(gemini_id)

    if not doc_valid and gemini_valid:
        ocr_choice = _select_course_id_from_ocr_majority(
            doc_row=doc_row,
            gemini_row=gemini_row,
            doc_id=doc_id,
            gemini_id=gemini_id,
        )

        if ocr_choice is not None:
            return ocr_choice

        return _gemini_missing_field_auto_fill_decision(
            field_name="course_id",
            gemini_value=gemini_id,
            gemini_confidence=gemini_row.confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=True,
        )

    if doc_valid and not gemini_valid:
        ocr_choice = _select_course_id_from_ocr_majority(
            doc_row=doc_row,
            gemini_row=gemini_row,
            doc_id=doc_id,
            gemini_id=gemini_id,
        )

        if ocr_choice is not None:
            return ocr_choice

        return doc_id, "document_ai", False, None

    if not doc_valid and not gemini_valid:
        ocr_choice = _select_course_id_from_ocr_majority(
            doc_row=doc_row,
            gemini_row=gemini_row,
            doc_id=doc_id,
            gemini_id=gemini_id,
        )

        if ocr_choice is not None:
            return ocr_choice

        return None, "missing", True, "course_id is missing or invalid from both sources."

    doc_text = str(doc_id).strip()
    gemini_text = str(gemini_id).strip()

    if doc_text.upper() == gemini_text.upper():
        return doc_id, "both", False, None

    # Evidence-backed cleanup for same numeric ID with noisy/expanded prefix.
    cleaner_choice = _choose_cleaner_same_number_course_id(doc_row, gemini_row)

    if cleaner_choice is not None:
        value, source = cleaner_choice
        return value, source, False, None

    # Safe 3-source majority / OCR visual-row repair.
    #
    # This is intentionally before focused verifier evidence because
    # document_ai_ocr_row_text is row-local text from the actual PDF visual row.
    # It fixes cases like Gemini saving "p 3616 French III" while OCR row text
    # shows "p 9120 French III A- 5.00 5.00".
    ocr_choice = _select_course_id_from_ocr_majority(
        doc_row=doc_row,
        gemini_row=gemini_row,
        doc_id=doc_id,
        gemini_id=gemini_id,
    )

    if ocr_choice is not None:
        return ocr_choice

    verifier_id = _course_id_scan_proof_id(course_id_scan_evidence)
    calculated_proof = _calculated_course_id_proof_score(
        doc_row=doc_row,
        gemini_row=gemini_row,
        course_id_scan_evidence=course_id_scan_evidence,
        match_confidence=match_confidence,
        doc_course_id=doc_id,
        gemini_course_id=gemini_id,
    )

    verifier_row_safe = _row_identity_extremely_safe_for_verifier(
        doc_row,
        gemini_row,
        match_confidence=match_confidence,
        threshold=COURSE_ID_VERIFIER_EXTREME_ROW_MATCH_THRESHOLD,
    )

    if verifier_id and _course_ids_equivalent(verifier_id, doc_id):
        return doc_id, "document_ai_course_id_scan_confirmed", False, None

    if verifier_id and _course_ids_equivalent(verifier_id, gemini_id):
        if (
            _calculated_proof_can_auto_override(calculated_proof)
            and verifier_row_safe
        ):
            return (
                gemini_id,
                "gemini_course_id_calculated_proof_auto_override",
                False,
                None,
            )

        if _calculated_proof_in_middle_band(calculated_proof):
            return doc_id, "document_ai", True, (
                f"Course ID needs review: Document AI says {doc_text}; "
                f"Gemini/verifier says {gemini_text}; calculated proof is "
                f"{_format_confidence_percent(calculated_proof)}. "
                "This is not safe enough to auto-overwrite."
            )

        return (
            doc_id,
            "document_ai_course_id_conflict_kept_weak_calculated_proof",
            False,
            None,
        )

    if verifier_id:
        if _calculated_proof_in_middle_band(calculated_proof) or _calculated_proof_can_auto_override(calculated_proof):
            return doc_id, "document_ai", True, (
                f"Course ID verifier produced a third value: Document AI says {doc_text}; "
                f"Gemini says {gemini_text}; verifier says {verifier_id}; calculated proof is "
                f"{_format_confidence_percent(calculated_proof)}."
            )

        return (
            doc_id,
            "document_ai_course_id_conflict_kept_weak_verifier_third_value",
            False,
            None,
        )

    return doc_id, "document_ai_course_id_conflict_kept_no_verifier_proof", False, None


def _pick_grade(
    doc_value: Any,
    gemini_value: Any,
    *,
    gemini_confidence: float | None = None,
    match_confidence: float | None = None,
    allow_confident_conflict_auto_resolve: bool = True,
    grade_scan_evidence: dict[str, Any] | None = None,
    doc_row: NormalizedCourseRow | None = None,
    gemini_row: NormalizedCourseRow | None = None,
) -> tuple[Any, str, bool, str | None]:
    """
    Grade decision rule using calculated proof.

    A valid Document AI grade wins by default. Gemini/verifier can only force
    review or overwrite when calculated proof is strong enough. This avoids
    trusting a self-reported 100% verifier answer that read the wrong row.
    """

    doc_grade = _normalize_grade(doc_value)
    gemini_grade = _normalize_grade(gemini_value)

    scan_grade_value = _grade_scan_proof_grade(grade_scan_evidence)
    scan_grade = _normalize_grade(scan_grade_value)

    doc_valid = _is_valid_grade(doc_grade)
    gemini_valid = _is_valid_grade(gemini_grade)
    scan_valid = _is_valid_grade(scan_grade)

    calculated_proof = _calculated_grade_proof_score(
        doc_row=doc_row,
        gemini_row=gemini_row,
        grade_scan_evidence=grade_scan_evidence,
        match_confidence=match_confidence,
        doc_grade=doc_grade,
        gemini_grade=gemini_grade,
    )

    verifier_row_safe = bool(
        allow_confident_conflict_auto_resolve
        and doc_row is not None
        and gemini_row is not None
        and _row_identity_extremely_safe_for_verifier(
            doc_row,
            gemini_row,
            match_confidence=match_confidence,
            threshold=GRADE_VERIFIER_EXTREME_ROW_MATCH_THRESHOLD,
        )
    )

    if not doc_valid and gemini_valid:
        missing_grade_decision = _gemini_missing_field_auto_fill_decision(
            field_name="grade",
            gemini_value=gemini_value,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=True,
        )

        # Focused grade-scan proof can also satisfy the missing-grade rule when
        # it agrees with Gemini and the row identity is safe enough.
        if missing_grade_decision[2] and scan_valid and _base_grade(scan_grade) == _base_grade(gemini_grade):
            scan_proof = calculated_proof
            if _coerce_float(scan_proof) is not None and _coerce_float(scan_proof) >= GEMINI_MISSING_FIELD_AUTO_FILL_CONFIDENCE_THRESHOLD:
                return gemini_value, "gemini_grade_scan_92_auto_fill_missing_grade", False, None

        return missing_grade_decision

    if doc_valid and not gemini_valid:
        return doc_value, "document_ai", False, None

    if not doc_valid and not gemini_valid:
        return None, "missing", True, "grade is missing or invalid from both sources."

    doc_and_gemini_same = (
        doc_grade == gemini_grade
        or _base_grade(doc_grade) == _base_grade(gemini_grade)
    )

    if doc_and_gemini_same:
        if scan_valid and not (
            scan_grade == doc_grade
            or _base_grade(scan_grade) == _base_grade(doc_grade)
        ):
            if _calculated_proof_in_middle_band(calculated_proof) or (
                _calculated_proof_can_auto_override(calculated_proof)
                and not verifier_row_safe
            ):
                return doc_value, "both_grade_scan_disagreed_but_document_ai_kept", False, None

            # Weak calculated proof: verifier alone did not prove both extractors wrong.
            return doc_value, "both", False, None

        return doc_value, "both", False, None

    if doc_valid and gemini_valid:
        if scan_valid:
            verifier_matches_doc = (
                scan_grade == doc_grade
                or _base_grade(scan_grade) == _base_grade(doc_grade)
            )
            verifier_matches_gemini = (
                scan_grade == gemini_grade
                or _base_grade(scan_grade) == _base_grade(gemini_grade)
            )

            if verifier_matches_doc:
                return doc_value, "document_ai_grade_scan_confirmed", False, None

            if verifier_matches_gemini:
                if (
                    _calculated_proof_can_auto_override(calculated_proof)
                    and verifier_row_safe
                ):
                    return (
                        scan_grade_value or gemini_value,
                        "gemini_grade_calculated_proof_auto_override",
                        False,
                        None,
                    )

                if _calculated_proof_in_middle_band(calculated_proof):
                    return doc_value, "document_ai_grade_conflict_kept_calculated_proof_below_override", False, None

                return (
                    doc_value,
                    "document_ai_grade_conflict_kept_weak_calculated_proof",
                    False,
                    None,
                )

            if _calculated_proof_in_middle_band(calculated_proof) or _calculated_proof_can_auto_override(calculated_proof):
                return doc_value, "document_ai_grade_conflict_kept_verifier_third_value_below_override", False, None

            return (
                doc_value,
                "document_ai_grade_conflict_kept_weak_verifier_third_value",
                False,
                None,
            )

        return doc_value, "document_ai_grade_conflict_kept_no_verifier_proof", False, None

    return doc_value if doc_valid else gemini_value, "document_ai" if doc_valid else "gemini", False, None


def _pick_grade_level(
    doc_value: Any,
    gemini_value: Any,
    *,
    gemini_confidence: float | None = None,
    doc_row: "NormalizedCourseRow | None" = None,
    gemini_row: "NormalizedCourseRow | None" = None,
    match_confidence: float | None = None,
) -> tuple[int | None, str, bool, str | None]:
    doc_int = _coerce_int(doc_value)
    gemini_int = _coerce_int(gemini_value)
    gemini_has_strong_proof = _gemini_has_strong_proof(gemini_confidence)

    if doc_int is None and gemini_int is not None:
        return _gemini_missing_field_auto_fill_decision(
            field_name="grade_level",
            gemini_value=gemini_int,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=False,
        )

    if doc_int is not None and gemini_int is None:
        needs_review = not _is_valid_grade_level(doc_int)
        reason = (
            "grade_level from Document AI is outside expected range."
            if needs_review
            else None
        )
        return doc_int, "document_ai", needs_review, reason

    if doc_int is None and gemini_int is None:
        return None, "missing", True, "grade_level is missing from both sources."

    doc_valid = _is_valid_grade_level(doc_int)
    gemini_valid = _is_valid_grade_level(gemini_int)

    if doc_int == gemini_int:
        return doc_int, "both", False, None

    if not doc_valid and gemini_valid:
        return _gemini_missing_field_auto_fill_decision(
            field_name="grade_level",
            gemini_value=gemini_int,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=False,
        )

    if doc_valid and not gemini_valid:
        return doc_int, "document_ai_gemini_invalid", False, None

    if doc_valid:
        if _gemini_can_repair_document_ai_context_field(
            field_name="grade_level",
            doc_value=doc_int,
            gemini_value=gemini_int,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ):
            return gemini_int, "gemini_confident_92_document_ai_grade_level_context_repair", False, None

        # Valid Document AI grade level wins by default. Gemini disagreement
        # does not force Needs Review unless Document AI is invalid/missing.
        return doc_int, "document_ai_default_grade_level_kept", False, None

    if gemini_has_strong_proof and gemini_valid:
        return gemini_int, "gemini_strong_proof_auto_fill", False, None

    return doc_int, "grade_level_doubt_document_ai_kept", True, (
        "grade_level differs between Document AI and Gemini."
    )


def _pick_int_field(
    field_name: str,
    doc_value: Any,
    gemini_value: Any,
    *,
    gemini_confidence: float | None = None,
    doc_row: "NormalizedCourseRow | None" = None,
    gemini_row: "NormalizedCourseRow | None" = None,
    match_confidence: float | None = None,
) -> tuple[int | None, str, bool, str | None]:
    doc_int = _coerce_int(doc_value)
    gemini_int = _coerce_int(gemini_value)

    if doc_int is None and gemini_int is not None:
        return _gemini_missing_field_auto_fill_decision(
            field_name=field_name,
            gemini_value=gemini_int,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=False,
        )

    if doc_int is not None and gemini_int is None:
        return doc_int, "document_ai", False, None

    if doc_int is None and gemini_int is None:
        return None, "missing", True, f"{field_name} is missing from both sources."

    if doc_int == gemini_int:
        return doc_int, "both", False, None

    # For required integer fields like year, keep Document AI by default when it
    # has a usable value. Gemini can repair a bad/misattached Document AI
    # context value only when it has >=92% confidence and the same-row rescue
    # checks prove identity by name/grade/credits.
    if doc_int is not None:
        if _gemini_can_repair_document_ai_context_field(
            field_name=field_name,
            doc_value=doc_int,
            gemini_value=gemini_int,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ):
            return gemini_int, f"gemini_confident_92_document_ai_{field_name}_context_repair", False, None

        return doc_int, f"document_ai_default_{field_name}_kept", False, None

    return gemini_int, "gemini", False, None


def _row_context_text(row: NormalizedCourseRow | None) -> str:
    if row is None:
        return ""

    parts: list[str] = []

    for value in [
        row.raw_payload,
        row.course_name,
        row.school_name,
        row.month,
        row.year,
        row.grade_level,
    ]:
        if value not in (None, "", [], {}):
            parts.append(str(value))

    return " ".join(parts).lower()


def _raw_context_mentions_month_or_term(row: NormalizedCourseRow | None) -> bool:
    text = _row_context_text(row)

    if not text:
        return False

    month_patterns = [
        r"\bmonth\b",
        r"\bterm_month\b",
        r"\bterm month\b",
        r"\bfall\b",
        r"\bspring\b",
        r"\bsummer\b",
        r"\bsemester\b",
        r"\bsem\s*1\b",
        r"\bsem\s*2\b",
        r"\bgrade\s+\d{1,2}\s+(fall|spring|summer)\b",
        r"\b(fall|spring|summer)\s+20\d{2}\b",
    ]

    return any(re.search(pattern, text) for pattern in month_patterns)


def _month_expected_for_rows(
    doc_row: NormalizedCourseRow | None,
    gemini_row: NormalizedCourseRow | None,
) -> bool:
    # If either extractor found a month, the transcript row clearly had
    # month/term context available.
    if doc_row is not None and doc_row.month is not None:
        return True

    if gemini_row is not None and gemini_row.month is not None:
        return True

    # Otherwise, require month only when the raw context clearly mentions
    # month/term/semester. This prevents schools like St. Anthony from being
    # blocked by month, and avoids false review flags when month is not printed.
    return (
        _raw_context_mentions_month_or_term(doc_row)
        or _raw_context_mentions_month_or_term(gemini_row)
    )



def _pick_month_field(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    match_confidence: float | None = None,
) -> tuple[int | None, str, bool, str | None]:
    # Month is important for matching, but not something we should advertise as
    # a user-facing Gemini fix. Matching already rejects explicit Month 1 vs
    # Month 6 conflicts. For the final value, keep Document AI if it has month;
    # let Gemini fill only when Document AI is missing.
    doc_month = _month_to_int(doc_row.month)
    gemini_month = _month_to_int(gemini_row.month)

    if doc_month is not None and gemini_month is not None:
        if doc_month == gemini_month:
            return doc_month, "both", False, None

        # This should be rare because month mismatch normally blocks matching.
        # If the row is a high-confidence rescue where Document AI attached the
        # course to the wrong term, allow Gemini to repair the month.
        if _gemini_can_repair_document_ai_context_field(
            field_name="month",
            doc_value=doc_month,
            gemini_value=gemini_month,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ):
            return gemini_month, "gemini_confident_92_document_ai_month_context_repair", False, None

        return doc_month, "document_ai_default_month_kept", False, None

    if doc_month is not None:
        return doc_month, "document_ai_fallback_optional", False, None

    if gemini_month is not None:
        value, source, needs_review, reason = _gemini_missing_field_auto_fill_decision(
            field_name="month",
            gemini_value=gemini_month,
            gemini_confidence=gemini_row.confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=False,
        )

        if needs_review and not _month_expected_for_rows(doc_row, gemini_row):
            # Month can be optional for some formats. Fill it for visibility,
            # but do not block completion when the transcript format did not
            # require a month/term field.
            return value, "gemini_filled_missing_month_optional_low_confidence", False, None

        return value, source, needs_review, reason

    if _month_expected_for_rows(doc_row, gemini_row):
        return None, "missing_expected_month", True, (
            "Month/term is missing even though the raw row context indicates a month/term field is expected."
        )

    return None, "missing_optional", False, None

def _pick_credit(
    field_name: str,
    doc_value: Any,
    gemini_value: Any,
    *,
    gemini_confidence: float | None = None,
    doc_row: "NormalizedCourseRow | None" = None,
    gemini_row: "NormalizedCourseRow | None" = None,
    match_confidence: float | None = None,
) -> tuple[float | None, str, bool, str | None]:
    doc_float = _coerce_float(doc_value)
    gemini_float = _coerce_float(gemini_value)

    if doc_float is None and gemini_float is not None:
        return _gemini_missing_field_auto_fill_decision(
            field_name=field_name,
            gemini_value=gemini_float,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=False,
        )

    if doc_float is not None and gemini_float is None:
        if _is_bad_credit(doc_float):
            return doc_float, "document_ai_bad_credit", True, (
                f"{field_name} from Document AI looks too high for one course."
            )

        return doc_float, "document_ai", False, None

    if doc_float is None and gemini_float is None:
        return None, "missing", True, f"{field_name} is missing from both sources."

    doc_bad = _is_bad_credit(doc_float)
    gemini_bad = _is_bad_credit(gemini_float)

    if _credits_equal(doc_float, gemini_float):
        return doc_float, "both", False, None

    if doc_bad and not gemini_bad and gemini_float is not None:
        return _gemini_missing_field_auto_fill_decision(
            field_name=field_name,
            gemini_value=gemini_float,
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
            high_risk=False,
        )

    if not doc_bad:
        # Valid Document AI credits win by default, including 0.0. Gemini must
        # not force Needs Review just because it read a different credit value.
        return doc_float, f"document_ai_default_{field_name}_kept", False, None

    return doc_float, "document_ai_bad_credit", True, (
        f"{field_name} from Document AI looks too high for one course."
    )


def _has_severe_identity_conflict(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> bool:
    same_course_id = _same_course_id(doc_row, gemini_row)
    same_name = _same_name(doc_row, gemini_row)
    name_score = _names_similar(doc_row.course_name, gemini_row.course_name)

    if same_course_id is False and same_name is False:
        return True

    if (
        same_course_id is False
        and doc_row.course_number
        and gemini_row.course_number
        and name_score < 0.92
    ):
        return True

    return False



def _source_label_uses_gemini(value: Any) -> bool:
    return "gemini" in str(value or "").strip().lower() or str(value or "").strip().lower() == "gem"


def _source_label_uses_document_ai(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return (
        "document_ai" in normalized
        or "doc_ai" in normalized
        or normalized.startswith("doc")
        or normalized == "both"
    )


def _row_course_number_name_conflicts_with_source_history(
    row: NormalizedCourseRow | None,
    source_rows: list[NormalizedCourseRow] | None,
) -> bool:
    """
    Detect an internally suspicious source row.

    Example Mayfair failure:
      one Gemini row says course number 7496 is "Intgtd Math I",
      while other Gemini rows say 7496 is "Math Analysis H".

    In that case Gemini likely borrowed the course id/grade from a nearby row.
    The row can still be displayed, but it must not be trusted silently.
    """

    if row is None or not source_rows:
        return False

    if not row.course_number or not row.course_name:
        return False

    comparable_rows = [
        candidate
        for candidate in source_rows
        if candidate is not row
        and candidate.row_id != row.row_id
        and candidate.course_number
        and candidate.course_number == row.course_number
        and candidate.course_name
    ]

    if not comparable_rows:
        return False

    matching_name_count = 0
    conflicting_name_count = 0

    for candidate in comparable_rows:
        if _course_names_same_identity(row.course_name, candidate.course_name):
            matching_name_count += 1
        else:
            conflicting_name_count += 1

    return bool(conflicting_name_count > matching_name_count)


def _matched_high_risk_gemini_fill_is_safe(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    match_confidence: float | None,
    all_gemini_rows: list[NormalizedCourseRow] | None = None,
) -> bool:
    """
    Decide whether Gemini can safely fill a high-risk field when Doc AI is
    missing that field.

    High-risk fields are course_id and grade. For scanned Mayfair/LBUSD rows,
    Gemini can sometimes read the course id or grade from the row above/below.
    So a normal match is not enough; the row must be very safe and the Gemini
    course number/name combination must not conflict with other Gemini rows.
    """

    if match_confidence is not None and match_confidence < HIGH_RISK_GEMINI_FILL_MATCH_THRESHOLD:
        return False

    if _same_int(doc_row.year, gemini_row.year) is False:
        return False

    if _same_int(doc_row.month, gemini_row.month) is False:
        return False

    if _same_int(doc_row.grade_level, gemini_row.grade_level) is False:
        return False

    if doc_row.course_name and gemini_row.course_name:
        if not _course_names_same_identity(doc_row.course_name, gemini_row.course_name):
            return False

    if _course_id_numbers_conflict(doc_row, gemini_row):
        return False

    if _row_course_number_name_conflicts_with_source_history(gemini_row, all_gemini_rows):
        return False

    # Require at least two non-row-order anchors beyond just a loose name match.
    anchors = 0

    if _same_int(doc_row.year, gemini_row.year) is True:
        anchors += 1

    if _same_int(doc_row.month, gemini_row.month) is True:
        anchors += 1

    if _same_int(doc_row.grade_level, gemini_row.grade_level) is True:
        anchors += 1

    if (
        _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted) is True
        or _same_credit(doc_row.credit_completed, gemini_row.credit_completed) is True
    ):
        anchors += 1

    if _same_course_id(doc_row, gemini_row) is True:
        anchors += 1

    return anchors >= 3


def _prefer_document_ai_for_count_owner_high_risk_fields(
    *,
    final_values: dict[str, Any],
    doc_row: NormalizedCourseRow,
) -> None:
    """
    When raw counts are equal or Document AI controls the final count, do not
    let Gemini silently replace valid Document AI high-risk values.

    This keeps the count-owner rule intact while preventing mixed rows like:
      course_id from Gemini's later row + course name/term from Document AI.
    """

    field_decisions = final_values.setdefault("field_decisions", {})

    if _is_valid_course_id_value(doc_row.course_id):
        source = field_decisions.get("course_id")
        if _source_label_uses_gemini(source) and not _source_label_uses_document_ai(source):
            final_values["course_id"] = doc_row.course_id
            field_decisions["course_id"] = "document_ai_count_owner_high_risk_default"

    if doc_row.course_name and not _looks_like_wrong_column_course_name(doc_row.course_name):
        source = field_decisions.get("course_name")
        if _source_label_uses_gemini(source) and not _source_label_uses_document_ai(source):
            final_values["course_name"] = doc_row.course_name
            field_decisions["course_name"] = "document_ai_count_owner_high_risk_default"

    if _is_valid_grade(doc_row.grade):
        source = field_decisions.get("grade")
        if _source_label_uses_gemini(source) and not _source_label_uses_document_ai(source):
            final_values["grade"] = doc_row.grade
            field_decisions["grade"] = "document_ai_count_owner_high_risk_default"


def _append_unsafe_gemini_fill_review_reasons(
    *,
    review_reasons: list[str],
    field_decisions: dict[str, str],
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    match_confidence: float | None,
    all_gemini_rows: list[NormalizedCourseRow] | None,
) -> None:
    """
    Keep final row count unchanged, but force Needs Review when Gemini supplied
    high-risk values that are not safe enough to trust automatically.
    """

    gemini_internal_conflict = _row_course_number_name_conflicts_with_source_history(
        gemini_row,
        all_gemini_rows,
    )

    if gemini_internal_conflict and (
        _source_label_uses_gemini(field_decisions.get("course_id"))
        or _source_label_uses_gemini(field_decisions.get("grade"))
    ):
        review_reasons.append(
            "Gemini supplied a high-risk field, but this Gemini row's course ID/name combination conflicts with other Gemini rows that share the same course number."
        )

    if _source_label_uses_gemini(field_decisions.get("course_id")):
        course_id_fill_safe = (
            _matched_high_risk_gemini_fill_is_safe(
                doc_row,
                gemini_row,
                match_confidence=match_confidence,
                all_gemini_rows=all_gemini_rows,
            )
            or _gemini_confident_rescue_fill_is_safe(
                doc_row,
                gemini_row,
                match_confidence=match_confidence,
            )
        )

        if not course_id_fill_safe:
            review_reasons.append(
                "Course ID was filled from Gemini, but row identity is not safe enough for automatic acceptance."
            )

    if _source_label_uses_gemini(field_decisions.get("grade")):
        grade_fill_safe = (
            _matched_high_risk_gemini_fill_is_safe(
                doc_row,
                gemini_row,
                match_confidence=match_confidence,
                all_gemini_rows=all_gemini_rows,
            )
            or _gemini_confident_rescue_fill_is_safe(
                doc_row,
                gemini_row,
                match_confidence=match_confidence,
            )
        )

        if not grade_fill_safe:
            review_reasons.append(
                "Grade was filled from Gemini, but row identity is not safe enough for automatic acceptance."
            )

# Fields that must never, by themselves, send a row to manual review:
#  - credit_attempted: not used in any GPA/A-G/index calculation (GPA uses
#    credit_completed) and it already falls back to credit_completed.
#  - month / school_name: not used in any admission decision.
_NON_DECISION_REVIEW_FIELDS = {"credit_attempted", "month", "school_name"}

# Fields that some transcript formats simply don't print per course. When BOTH
# sources lack one, the column isn't there (e.g. Mayfair has no per-course grade
# level), so it's a format characteristic — not an extraction error worth review.
_FORMAT_OPTIONAL_REVIEW_FIELDS = {"grade_level", "month", "school_name"}

# Fields where, when Document AI simply MISSED the value but Gemini supplies it,
# we fill from Gemini rather than send to manual review. Genuine CONFLICTS
# (both present but different) use a different reason and still block — only the
# one-sided "is missing/invalid" case is auto-filled here.
_GEMINI_FILLABLE_FIELDS = {"course_id", "grade", "credit_completed"}


def _is_soft_review_reason(field_name: str, reason: str | None) -> bool:
    """A review reason that should NOT block (no manual review needed)."""
    if field_name in _NON_DECISION_REVIEW_FIELDS:
        return True
    if (
        field_name in _FORMAT_OPTIONAL_REVIEW_FIELDS
        and reason
        and "missing from both sources" in reason
    ):
        return True
    if (
        field_name in _GEMINI_FILLABLE_FIELDS
        and reason
        and "is missing/invalid" in reason
    ):
        return True
    return False


def _build_final_from_matched_rows(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    match_confidence: float | None = None,
    count_owner_source: str | None = None,
    all_document_ai_rows: list[NormalizedCourseRow] | None = None,
    all_gemini_rows: list[NormalizedCourseRow] | None = None,
) -> dict[str, Any]:
    review_reasons: list[str] = []
    field_decisions: dict[str, str] = {}
    gemini_confidence = gemini_row.confidence
    severe_identity_conflict = _has_severe_identity_conflict(doc_row, gemini_row)
    course_id_numeric_conflict = bool(
        doc_row.course_number
        and gemini_row.course_number
        and doc_row.course_number != gemini_row.course_number
    )

    grade_scan_evidence = _extract_grade_scan_evidence(gemini_row)
    course_id_scan_evidence = _extract_course_id_scan_evidence(gemini_row)
    allow_grade_scan_auto_fix = (
        not severe_identity_conflict
        and not course_id_numeric_conflict
    )

    safe_gemini_confidence = (
        None
        if severe_identity_conflict or course_id_numeric_conflict
        else gemini_confidence
    )
    safe_gemini_grade_confidence = _effective_gemini_grade_confidence(
        gemini_confidence=safe_gemini_confidence,
        grade_scan_evidence=grade_scan_evidence,
        allow_grade_scan=allow_grade_scan_auto_fix,
    )
    # safe_gemini_grade_confidence is retained for diagnostics/future tuning.
    # Main Gemini confidence alone cannot overwrite a valid Document AI grade;
    # only focused grade-scan/verifier evidence can do that.

    # Do not add a generic course-name/ID conflict review reason here.
    # Course ID mismatch is handled precisely by _pick_course_id().
    # Course name mismatch is allowed to be auto-fixed from Gemini when safe.

    def collect(field_name: str, decision: tuple[Any, str, bool, str | None]):
        value, source, needs_review, reason = decision
        field_decisions[field_name] = source

        # Non-decision fields (credit_attempted/month/school_name) and
        # format-absent columns (e.g. grade level missing from BOTH sources)
        # don't warrant manual review — keep the value, drop the blocking reason.
        if needs_review and reason and not _is_soft_review_reason(field_name, reason):
            review_reasons.append(reason)

        return value

    course_id = collect(
        "course_id",
        _pick_course_id(
            doc_row,
            gemini_row,
            match_confidence=match_confidence,
            course_id_scan_evidence=course_id_scan_evidence,
        ),
    )

    course_name = collect(
        "course_name",
        _pick_text_field(
            "course_name",
            doc_row.course_name,
            gemini_row.course_name,
            require_similarity=True,
            # Use original Gemini confidence for course names. Even when course_id
            # has a doubt, Gemini can still provide the better visible subject name.
            gemini_confidence=gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ),
    )

    if course_name and _looks_like_wrong_column_course_name(course_name):
        review_reasons.append(
            "Final course_name looks like credit/grade text instead of a real course name."
        )

    grade = collect(
        "grade",
        _pick_grade(
            doc_row.grade,
            gemini_row.grade,
            gemini_confidence=safe_gemini_confidence,
            match_confidence=match_confidence,
            allow_confident_conflict_auto_resolve=allow_grade_scan_auto_fix,
            grade_scan_evidence=grade_scan_evidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
        ),
    )

    grade_level = collect(
        "grade_level",
        _pick_grade_level(
            doc_row.grade_level,
            gemini_row.grade_level,
            gemini_confidence=safe_gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ),
    )

    month = collect("month", _pick_month_field(doc_row, gemini_row, match_confidence=match_confidence))

    year = collect(
        "year",
        _pick_int_field(
            "year",
            doc_row.year,
            gemini_row.year,
            gemini_confidence=safe_gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ),
    )

    school_name = collect(
        "school_name",
        _pick_text_field(
            "school_name",
            doc_row.school_name,
            gemini_row.school_name,
            require_similarity=False,
            gemini_confidence=safe_gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ),
    )

    credit_attempted = collect(
        "credit_attempted",
        _pick_credit(
            "credit_attempted",
            doc_row.credit_attempted,
            gemini_row.credit_attempted,
            gemini_confidence=safe_gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ),
    )

    credit_completed = collect(
        "credit_completed",
        _pick_credit(
            "credit_completed",
            doc_row.credit_completed,
            gemini_row.credit_completed,
            gemini_confidence=safe_gemini_confidence,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_confidence=match_confidence,
        ),
    )

    final_values_snapshot = {
        "course_id": course_id,
        "course_name": course_name,
        "grade": grade,
        "grade_level": grade_level,
        "month": month,
        "year": year,
        "school_name": school_name,
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "field_decisions": field_decisions,
    }

    if count_owner_source == "document_ai":
        _prefer_document_ai_for_count_owner_high_risk_fields(
            final_values=final_values_snapshot,
            doc_row=doc_row,
        )
        course_id = final_values_snapshot["course_id"]
        course_name = final_values_snapshot["course_name"]
        grade = final_values_snapshot["grade"]
        field_decisions = final_values_snapshot["field_decisions"]

    _append_unsafe_gemini_fill_review_reasons(
        review_reasons=review_reasons,
        field_decisions=field_decisions,
        doc_row=doc_row,
        gemini_row=gemini_row,
        match_confidence=match_confidence,
        all_gemini_rows=all_gemini_rows,
    )

    if not course_id:
        review_reasons.append("Final course_id is missing.")

    if not course_name:
        review_reasons.append("Final course_name is missing.")

    if not grade:
        review_reasons.append("Final grade is missing.")

    # grade_level is format-optional (some transcripts don't print it) and
    # credit_attempted is not used in any calculation — neither blocks review.
    if year is None:
        review_reasons.append("Final year is missing.")

    if credit_completed is None:
        review_reasons.append("Final credit_completed is missing.")

    needs_review = bool(review_reasons)

    return {
        "course_id": course_id,
        "course_name": course_name,
        "grade": grade,
        "grade_level": grade_level,
        "month": month,
        "year": year,
        "school_name": school_name,
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "needs_review": needs_review,
        "review_status": "needs_review" if needs_review else "auto_resolved",
        "review_reason": "; ".join(dict.fromkeys(review_reasons)) or None,
        "resolution_reason": "matched_needs_review" if needs_review else "matched_auto_resolved",
        "field_decisions": field_decisions,
        "final_source": "merged",
    }




def _source_only_gemini_can_auto_resolve_without_geometry(
    row: NormalizedCourseRow,
    *,
    force_review_reason: str | None = None,
) -> tuple[bool, str | None]:
    """
    Narrow fallback for complete, high-confidence Gemini-only rows when PDF
    geometry is unavailable.

    This fallback is intentionally small and conservative:
    - It only applies to Gemini-only rows that are already complete, believable,
      and very high confidence.
    - It does not change matching, count ownership, matched rows, Doc-AI-only
      rows, St. Anthony rules, or extractor output.
    - If deterministic geometry is unavailable, a clean Gemini-only row can
      complete instead of being sent to Needs Review only because geometry/OCR
      could not attach.
    - Focused scan/verifier disagreement blocks auto-resolve only when it
      produces a strong contradictory value. A generic "scan disagrees" flag by
      itself is not enough, because those flags can be false positives on dense
      Mayfair/LBUSD rows.
    """
    if force_review_reason not in (None, ""):
        return False, "another reconciliation rule already marked this row for review"

    if not _is_required_complete(row):
        return False, "row is missing one or more required fields"

    if not _is_row_believable(row):
        return False, "row has one or more values that are not believable"

    confidence = _coerce_float(row.confidence)
    if confidence is None or confidence < 0.98:
        return False, "Gemini confidence is below the 98% fallback threshold"

    if row.course_name and _looks_like_wrong_column_course_name(row.course_name):
        return False, "course name looks like credit/grade text"

    if not row.course_id or not _is_valid_course_id_value(row.course_id):
        return False, "course ID is missing or invalid"

    if not row.course_name or not _is_valid_course_name(row.course_name):
        return False, "course name is missing or invalid"

    payload = _raw_payload_dict(row.raw_payload)

    # If OCR visual-row text is present, require it to confirm the same row.
    # If OCR text is absent, do not penalize the row for missing optional OCR.
    ocr_text = payload.get("document_ai_ocr_row_text")
    if ocr_text not in (None, ""):
        ocr_confirmed, ocr_reason = _source_only_gemini_ocr_confirmation_result(row)
        if not ocr_confirmed:
            return False, ocr_reason or "OCR row text did not confirm this row"

    # Course-ID scan/verifier can block this fallback only when it gives a
    # strong, specific, contradictory course ID. Do not block only because
    # course_id_scan_agrees_with_main is False; that flag can be wrong when the
    # verifier looked at a nearby dense-column row.
    course_id_evidence = _extract_course_id_scan_evidence(row)
    verifier_course_id = _course_id_scan_proof_id(course_id_evidence)
    verifier_course_id_confidence = _course_id_scan_proof_confidence(course_id_evidence)
    verifier_course_id_match_component = _normalized_match_score_component(
        course_id_evidence.get("match_score")
    ) if course_id_evidence else 0.0

    if (
        verifier_course_id
        and verifier_course_id_confidence is not None
        and verifier_course_id_confidence >= 0.99
        and verifier_course_id_match_component >= 0.92
        and not _course_ids_equivalent(verifier_course_id, row.course_id)
    ):
        return (
            False,
            "Course-ID verifier strongly disagrees with the saved Gemini-only course ID",
        )

    # Grade scan/verifier can block this fallback only when it gives a strong,
    # specific, contradictory grade. Do not block only because grade_scan_changed
    # or grade_scan_disagreement_count is set.
    grade_evidence = _extract_grade_scan_evidence(row)
    verifier_grade = _grade_scan_proof_grade(grade_evidence)
    verifier_grade_confidence = _grade_scan_proof_confidence(grade_evidence)
    verifier_grade_match_component = _normalized_match_score_component(
        grade_evidence.get("match_score")
    ) if grade_evidence else 0.0

    if (
        verifier_grade
        and verifier_grade_confidence is not None
        and verifier_grade_confidence >= 0.99
        and verifier_grade_match_component >= 0.92
        and _is_valid_grade(verifier_grade)
        and _is_valid_grade(row.grade)
        and _base_grade(verifier_grade) != _base_grade(row.grade)
    ):
        return (
            False,
            "Grade verifier strongly disagrees with the saved Gemini-only grade",
        )

    return True, None


def _source_only_gemini_ocr_confirmation_result(
    row: NormalizedCourseRow,
) -> tuple[bool, str | None]:
    """
    Safe fallback for Gemini-only Mayfair/LBUSD rows when the new Document AI
    OCR visual-row evidence is present but the older geometry_canonical_row key
    is absent.

    This is intentionally narrow and only affects source-only Gemini rows.
    It does not change counts, matched-row decisions, Document-AI-only rows,
    St. Anthony logic, or any extractor output.

    If OCR row text confirms the same title plus grade/credits and exposes a
    different start-of-row Course ID, the row is still considered confirmed
    because _build_final_from_single_source() will repair the final Course ID
    from the OCR visual row.
    """

    payload = _raw_payload_dict(row.raw_payload)

    if not payload:
        return False, "No OCR payload was available for this Gemini-only row."

    row_text = payload.get("document_ai_ocr_row_text")

    if row_text in (None, ""):
        return False, "No Document AI OCR visual-row text was attached to this Gemini-only row."

    ocr_bundle = _ocr_term_bundle_for_row(row)

    if not ocr_bundle:
        return (
            False,
            "Document AI OCR visual-row text did not safely confirm this Gemini-only row identity and term bundle.",
        )

    if _same_int(row.grade_level, ocr_bundle.get("grade_level")) is False:
        return False, "OCR section grade year does not match the Gemini-only row grade year."

    if _same_int(row.month, ocr_bundle.get("month")) is False:
        return False, "OCR section month does not match the Gemini-only row month."

    if _same_int(row.year, ocr_bundle.get("year")) is False:
        return False, "OCR section year does not match the Gemini-only row year."

    text_value = str(row_text).strip()
    text_upper = text_value.upper()

    visible_course_id = _extract_visible_course_id_from_ocr_row_text(text_value)
    visible_course_id_ok = bool(
        visible_course_id
        and _is_valid_course_id_value(visible_course_id)
        and (
            _course_ids_equivalent(visible_course_id, row.course_id)
            or _course_id_ocr_row_text_confirms_same_course(
                row_text=text_value,
                row=row,
                visible_course_id=visible_course_id,
            )
        )
    )

    course_number = row.course_number
    course_number_ok = bool(
        course_number
        and re.search(rf"\b{re.escape(str(course_number))}\b", text_upper)
    )

    course_name_ok = False
    if row.course_name not in (None, ""):
        course_name_ok = (
            _names_similar(text_value, row.course_name) >= 0.55
            or _names_token_similar(text_value, row.course_name, threshold=0.45)
        )

    if not (visible_course_id_ok or course_number_ok or course_name_ok):
        return (
            False,
            "OCR visual-row text does not contain the Gemini-only course ID or course title strongly enough.",
        )

    grade_ok = False
    base_grade = _base_grade(row.grade)
    if base_grade:
        grade_ok = bool(re.search(rf"\b{re.escape(base_grade)}[+-]?\b", text_upper))

    credit_ok = False
    for credit in (row.credit_attempted, row.credit_completed):
        credit_float = _coerce_float(credit)
        if credit_float is None:
            continue

        if abs(credit_float - int(credit_float)) < 0.01:
            credit_pattern = str(int(credit_float))
        else:
            credit_pattern = str(credit_float)

        if re.search(rf"\b{re.escape(credit_pattern)}(?:\.0{{1,2}})?\b", text_value):
            credit_ok = True
            break

    if not (grade_ok or credit_ok):
        return (
            False,
            "OCR visual-row text does not confirm the Gemini-only grade or credits.",
        )

    return True, None


def _source_only_gemini_geometry_confirmation_result(
    row: NormalizedCourseRow,
) -> tuple[bool, str | None]:
    """
    Guardrail for Mayfair/LBUSD Gemini-only rows.

    Gemini-only rows can be real missing rows, but on dense 3-column/continued
    transcripts they can also be shifted composites, for example a course ID
    from one visual row paired with the title from another row. Confidence by
    itself is not enough to auto-complete those rows.

    Existing deterministic geometry confirmation remains the first path.
    The only added behavior is a safe fallback: if older geometry_canonical_row
    is absent but Document AI OCR visual-row text and section bundle confirm the
    same row, the Gemini-only row can auto-resolve.
    """

    alignment = row.alignment if isinstance(row.alignment, dict) else {}
    geometry_row = alignment.get("geometry_canonical_row")

    if not isinstance(geometry_row, dict):
        ocr_confirmed, ocr_failure_reason = _source_only_gemini_ocr_confirmation_result(row)

        if ocr_confirmed:
            return True, None

        return (
            False,
            "No deterministic PDF geometry row was attached to this Gemini-only row. "
            + str(ocr_failure_reason or ""),
        )

    match_score = _coerce_float(alignment.get("geometry_match_score"))

    if match_score is None or match_score < TRANSCRIPT_GEOMETRY_STRONG_MATCH_THRESHOLD:
        return (
            False,
            "The deterministic PDF geometry match is not strong enough to auto-accept this Gemini-only row.",
        )

    geometry_course_name = geometry_row.get("course_name")
    geometry_course_id = geometry_row.get("course_id")
    geometry_course_number = str(geometry_row.get("course_number") or _course_number_from_raw(geometry_course_id) or "")
    geometry_grade = geometry_row.get("grade")
    geometry_grade_level = _coerce_int(geometry_row.get("grade_level"))
    geometry_month = _month_to_int(geometry_row.get("month"))
    geometry_year = _year_to_int(geometry_row.get("year"))
    geometry_credit_attempted = _coerce_float(geometry_row.get("credit_attempted"))
    geometry_credit_completed = _coerce_float(geometry_row.get("credit_completed"))

    if row.course_name and geometry_course_name:
        if not _course_names_same_identity(row.course_name, geometry_course_name):
            return (
                False,
                "The Gemini-only course title does not match the deterministic PDF visual row title.",
            )

    if row.course_number and geometry_course_number:
        if row.course_number != geometry_course_number:
            return (
                False,
                "The Gemini-only course ID number does not match the deterministic PDF visual row course ID.",
            )

    if row.grade and geometry_grade:
        if _base_grade(row.grade) != _base_grade(geometry_grade):
            return (
                False,
                "The Gemini-only grade does not match the deterministic PDF visual row grade.",
            )

    if row.grade_level is not None and geometry_grade_level is not None:
        if row.grade_level != geometry_grade_level:
            return (
                False,
                "The Gemini-only grade year does not match the deterministic PDF visual row grade year.",
            )

    if row.year is not None and geometry_year is not None:
        if row.year != geometry_year:
            return (
                False,
                "The Gemini-only academic year does not match the deterministic PDF visual row year.",
            )

    if row.month is not None and geometry_month is not None:
        if row.month != geometry_month:
            return (
                False,
                "The Gemini-only month/term does not match the deterministic PDF visual row month/term.",
            )

    attempted_match = _same_credit(row.credit_attempted, geometry_credit_attempted)
    completed_match = _same_credit(row.credit_completed, geometry_credit_completed)

    if attempted_match is False and completed_match is False:
        return (
            False,
            "The Gemini-only credits do not match the deterministic PDF visual row credits.",
        )

    if not geometry_course_name and not geometry_course_id:
        return (
            False,
            "The deterministic PDF geometry row did not include enough course identity evidence.",
        )

    return True, None


def _build_final_from_single_source(
    row: NormalizedCourseRow,
    *,
    source: str,
    force_review_reason: str | None = None,
) -> dict[str, Any]:
    review_reasons: list[str] = []

    complete = _is_required_complete(row)
    believable = _is_row_believable(row)

    final_course_id = row.course_id
    final_course_id_source = source

    # Source-only Gemini can be complete but still carry a shifted Course ID.
    # If Document AI OCR visual-row text confirms the same course title plus
    # grade/credits, use the printed Course ID from that exact OCR row.
    if source == "gemini":
        ocr_course_id_choice = _source_only_gemini_course_id_ocr_repair(row)

        if ocr_course_id_choice is not None:
            final_course_id, final_course_id_source = ocr_course_id_choice

    if force_review_reason:
        review_reasons.append(force_review_reason)

    if not complete:
        review_reasons.append(
            f"{source} row is missing course ID, valid course name, grade, grade level, year, or credits."
        )

    if final_course_id in (None, ""):
        review_reasons.append(f"{source} final course ID is missing.")

    if final_course_id not in (None, "") and not _is_valid_course_id_value(final_course_id):
        review_reasons.append(f"{source} final course ID is invalid.")

    if row.course_name and _looks_like_wrong_column_course_name(row.course_name):
        review_reasons.append(
            f"{source} course name looks like credit/grade text instead of a real course name."
        )

    if not believable:
        review_reasons.append(
            f"{source} row has one or more values that need review."
        )

    if source == "gemini":
        confidence = row.confidence

        if confidence is None or confidence < HIGH_CONFIDENCE_THRESHOLD:
            review_reasons.append(
                "Gemini-only row is below the 70% confidence threshold."
            )

        # Do not auto-complete source-only Gemini rows on dense Mayfair/LBUSD
        # transcripts unless deterministic row geometry confirms the exact
        # visual row. This prevents shifted composites such as a course ID from
        # one row being paired with the title from another row. St. Anthony is
        # excluded because it has a separate no-course-ID layout and dedicated
        # reconciliation rules below.
        if not _is_st_anthony_row(row):
            geometry_confirmed, geometry_failure_reason = _source_only_gemini_geometry_confirmation_result(row)

            if not geometry_confirmed:
                soft_confirmed, soft_failure_reason = _source_only_gemini_can_auto_resolve_without_geometry(
                    row,
                    force_review_reason=force_review_reason,
                )

                if soft_confirmed:
                    # Safe fallback accepted this Gemini-only row.
                    # Do not mutate NormalizedCourseRow here; final field_decisions
                    # are built in this return payload.
                    pass
                else:
                    review_reasons.append(
                        "Gemini-only row needs review because deterministic PDF row geometry "
                        "did not confirm the course ID/title/term as one visual row. "
                        + str(geometry_failure_reason or "")
                        + " Fallback check: "
                        + str(soft_failure_reason or "not eligible")
                    )

    needs_review = bool(review_reasons)

    if source == "document_ai":
        resolution_reason = (
            "document_ai_only_needs_review"
            if needs_review
            else "accepted_document_ai_only"
        )
    else:
        resolution_reason = (
            "gemini_only_needs_review"
            if needs_review
            else "accepted_gemini_only"
        )

    return {
        "course_id": final_course_id,
        "course_name": row.course_name,
        "grade": row.grade,
        "grade_level": row.grade_level,
        "month": row.month,
        "year": row.year,
        "school_name": row.school_name,
        "credit_attempted": row.credit_attempted,
        "credit_completed": row.credit_completed,
        "needs_review": needs_review,
        "review_status": "needs_review" if needs_review else "auto_resolved",
        "review_reason": "; ".join(dict.fromkeys(review_reasons)) or None,
        "resolution_reason": resolution_reason,
        "field_decisions": {
            "course_id": final_course_id_source,
            "course_name": source,
            "grade": source,
            "grade_level": source,
            "month": source,
            "year": source,
            "school_name": source,
            "credit_attempted": source,
            "credit_completed": source,
        },
        "final_source": source,
    }


def _build_field_differences(
    doc_row: NormalizedCourseRow | None,
    gemini_row: NormalizedCourseRow | None,
) -> dict[str, dict[str, Any]]:
    if doc_row is None or gemini_row is None:
        return {}

    differences: dict[str, dict[str, Any]] = {}

    checks = {
        "course_id": (
            doc_row.course_id,
            gemini_row.course_id,
            _same_course_id(doc_row, gemini_row),
        ),
        "course_name": (
            doc_row.course_name,
            gemini_row.course_name,
            _same_name(doc_row, gemini_row),
        ),
        "letter_grade": (
            doc_row.grade,
            gemini_row.grade,
            _same_grade(doc_row, gemini_row),
        ),
        "grade_level": (
            doc_row.grade_level,
            gemini_row.grade_level,
            _same_int(doc_row.grade_level, gemini_row.grade_level),
        ),
        # Month is intentionally excluded from field differences.
        "year": (
            doc_row.year,
            gemini_row.year,
            _same_int(doc_row.year, gemini_row.year),
        ),
        "credit_attempted": (
            doc_row.credit_attempted,
            gemini_row.credit_attempted,
            _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted),
        ),
        "credit_completed": (
            doc_row.credit_completed,
            gemini_row.credit_completed,
            _same_credit(doc_row.credit_completed, gemini_row.credit_completed),
        ),
    }

    for field_name, (doc_value, gemini_value, is_match) in checks.items():
        if is_match is False:
            differences[field_name] = {
                "document_ai": doc_value,
                "gemini": gemini_value,
            }

    return differences


def _doc_ai_row_needs_gemini_rescue(row: NormalizedCourseRow) -> bool:
    return bool(
        not row.course_id
        or not _is_valid_course_id_value(row.course_id)
        or not row.course_name
        or _looks_like_wrong_column_course_name(row.course_name)
    )


def _rescue_context_compatible(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> bool:
    # Normal case: no explicit context conflicts.
    year_mismatch = _same_int(doc_row.year, gemini_row.year) is False
    month_mismatch = _same_int(doc_row.month, gemini_row.month) is False
    grade_level_mismatch = _same_int(doc_row.grade_level, gemini_row.grade_level) is False

    if not year_mismatch and not month_mismatch and not grade_level_mismatch:
        return True

    # Rescue case: Document AI sometimes attaches an incomplete Mayfair/LBUSD
    # row to the wrong term/year/grade block. Allow Gemini to rescue only when
    # Gemini is >=92% confident and row identity is proven by course name, grade,
    # credits, no course-number conflict, and close row order.
    return _gemini_confident_rescue_fill_is_safe(
        doc_row,
        gemini_row,
        match_confidence=GEMINI_MISSING_FIELD_RESCUE_MATCH_THRESHOLD,
    )



def _doc_ai_only_rescue_score(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> float:
    if not _doc_ai_row_needs_gemini_rescue(doc_row):
        return 0.0

    if not _rescue_context_compatible(doc_row, gemini_row):
        return 0.0

    if gemini_row.course_name and _looks_like_wrong_column_course_name(gemini_row.course_name):
        return 0.0

    score = 0.0

    if doc_row.course_name and not _looks_like_wrong_column_course_name(doc_row.course_name):
        score += _names_similar(doc_row.course_name, gemini_row.course_name) * 0.30
    elif gemini_row.course_name:
        score += 0.18

    if _same_int(doc_row.year, gemini_row.year) is True:
        score += 0.16

    if _same_int(doc_row.month, gemini_row.month) is True:
        score += 0.14

    if _same_int(doc_row.grade_level, gemini_row.grade_level) is True:
        score += 0.14

    if (
        _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted) is True
        or _same_credit(doc_row.credit_completed, gemini_row.credit_completed) is True
    ):
        score += 0.18

    if doc_row.grade and gemini_row.grade and _same_grade(doc_row, gemini_row) is True:
        score += 0.08

    row_distance = abs((doc_row.row_index or 0) - (gemini_row.row_index or 0))

    if row_distance <= 2:
        score += 0.08
    elif row_distance <= 5:
        score += 0.04

    if gemini_row.course_id and _is_valid_course_id_value(gemini_row.course_id):
        score += 0.04

    return max(0.0, min(round(score, 3), 1.0))


def _rescue_doc_ai_only_rows_with_gemini(
    doc_only_rows: list[NormalizedCourseRow],
    gemini_only_rows: list[NormalizedCourseRow],
) -> tuple[
    list[tuple[NormalizedCourseRow, NormalizedCourseRow, float]],
    list[NormalizedCourseRow],
    list[NormalizedCourseRow],
]:
    """
    Pair bad Doc-AI-only rows with unmatched Gemini rows when safe.

    This fixes cases where Document AI created a source-only row with missing
    course ID or wrong-column course name such as "5.00/5.00 B", but Gemini
    extracted the real course ID/name for that same row.
    """

    rescue_candidates: list[tuple[float, int, int]] = []

    for doc_index, doc_row in enumerate(doc_only_rows):
        for gemini_index, gemini_row in enumerate(gemini_only_rows):
            score = _doc_ai_only_rescue_score(doc_row, gemini_row)

            if score >= 0.62:
                rescue_candidates.append((score, doc_index, gemini_index))

    rescue_candidates.sort(key=lambda item: item[0], reverse=True)

    used_doc_indexes: set[int] = set()
    used_gemini_indexes: set[int] = set()
    rescued_matches: list[tuple[NormalizedCourseRow, NormalizedCourseRow, float]] = []

    for score, doc_index, gemini_index in rescue_candidates:
        if doc_index in used_doc_indexes or gemini_index in used_gemini_indexes:
            continue

        used_doc_indexes.add(doc_index)
        used_gemini_indexes.add(gemini_index)
        rescued_matches.append(
            (
                doc_only_rows[doc_index],
                gemini_only_rows[gemini_index],
                score,
            )
        )

    remaining_doc_only = [
        row
        for index, row in enumerate(doc_only_rows)
        if index not in used_doc_indexes
    ]
    remaining_gemini_only = [
        row
        for index, row in enumerate(gemini_only_rows)
        if index not in used_gemini_indexes
    ]

    return rescued_matches, remaining_doc_only, remaining_gemini_only



def _select_course_count_owner(
    *,
    document_ai_count: int,
    gemini_count: int,
) -> str:
    """
    Decide which extractor controls the final row count.

    This is different from field-level trust.

    - If Gemini extracted more rows, final count follows Gemini count.
    - If Document AI extracted more rows, final count follows Document AI count.
    - If counts are equal, default to Document AI for stability.
    """

    if gemini_count > document_ai_count:
        return "gemini"

    return "document_ai"



def _select_primary_source(
    *,
    document_ai_count: int,
    gemini_count: int,
) -> str:
    """
    Select the default trusted source for field conflicts.

    This does NOT decide the final row count anymore.

    Final rows are created from:
      - matched Document AI + Gemini rows
      - safe Document-AI-only rows
      - safe Gemini-only rows

    Document AI remains the default value winner for matched field conflicts
    unless Gemini/verifier has calculated proof. Gemini can still add extra
    source-only rows when Document AI missed them.
    """

    if document_ai_count > 0:
        return "document_ai"

    if gemini_count > 0:
        return "gemini"

    return "document_ai"


def _source_only_duplicate_signature(row: NormalizedCourseRow) -> tuple[Any, ...]:
    return (
        row.course_number or str(row.course_id or "").strip().upper(),
        _normalize_course_name(row.course_name),
        _base_grade(row.grade),
        _coerce_int(row.grade_level),
        _year_to_int(row.year),
        _month_to_int(row.month),
        round(_coerce_float(row.credit_attempted) or -1, 3),
        round(_coerce_float(row.credit_completed) or -1, 3),
    )


def _source_only_duplicate_review_reason(
    row: NormalizedCourseRow,
    seen_signatures: set[tuple[Any, ...]],
) -> str | None:
    """
    Duplicate guard for source-only rows.

    A repeated complete/believable course row is not automatically wrong. Some
    transcripts legitimately repeat similar courses/terms, and equal Doc AI /
    Gemini raw counts should not create a Needs Review row only because a source
    signature appeared twice. Only use this as a review reason when the repeated
    row is already incomplete or suspicious.
    """
    signature = _source_only_duplicate_signature(row)

    if signature in seen_signatures:
        if _is_required_complete(row) and _is_row_believable(row):
            return None

        return (
            "Possible repeated source-only duplicate row with the same course ID, "
            "course name, grade, grade year, year, month, and credits."
        )

    seen_signatures.add(signature)
    return None


def _combine_review_reasons(*reasons: str | None) -> str | None:
    clean_reasons = [
        str(reason).strip()
        for reason in reasons
        if reason and str(reason).strip()
    ]

    if not clean_reasons:
        return None

    return " ".join(clean_reasons)


def _source_only_context_matches(
    left: NormalizedCourseRow,
    right: NormalizedCourseRow,
) -> bool:
    # For a conflict gate we want a reasonably strict context match.
    year_match = _same_int(left.year, right.year)
    month_match = _same_int(left.month, right.month)
    grade_level_match = _same_int(left.grade_level, right.grade_level)

    if year_match is False:
        return False

    if month_match is False:
        return False

    if grade_level_match is False:
        return False

    # Require at least year + one of month/grade-level when available, so we do
    # not compare unrelated repeated courses across the whole transcript.
    matched_context_count = sum(
        1
        for value in [year_match, month_match, grade_level_match]
        if value is True
    )

    return matched_context_count >= 2


def _source_only_credits_compatible(
    left: NormalizedCourseRow,
    right: NormalizedCourseRow,
) -> bool:
    attempted_match = _same_credit(left.credit_attempted, right.credit_attempted)
    completed_match = _same_credit(left.credit_completed, right.credit_completed)

    if attempted_match is False:
        return False

    if completed_match is False:
        return False

    return True


def _source_only_course_id_verifier_confirms_row(row: NormalizedCourseRow) -> bool:
    """
    Source-only Gemini row can survive a nearby Doc AI conflict only when the
    focused Course ID verifier confirms that exact Gemini row with strong
    calculated proof. Without match_score evidence, raw confidence=1.0 is not
    enough.
    """

    evidence = _extract_course_id_scan_evidence(row)
    verifier_id = _course_id_scan_proof_id(evidence)
    verifier_confidence = _course_id_scan_proof_confidence(evidence)

    if not verifier_id or verifier_confidence is None:
        return False

    simple_proof = round(
        verifier_confidence
        * _normalized_match_score_component(evidence.get("match_score")),
        4,
    )

    return bool(
        _calculated_proof_can_auto_override(simple_proof)
        and _course_ids_equivalent(verifier_id, row.course_id)
    )


def _source_only_grade_verifier_confirms_row(row: NormalizedCourseRow) -> bool:
    """
    Source-only Gemini row can survive a nearby Doc AI grade conflict only when
    the focused grade verifier confirms that exact Gemini row with strong
    calculated proof. Without match_score evidence, raw confidence=1.0 is not
    enough.
    """

    evidence = _extract_grade_scan_evidence(row)
    verifier_grade = _grade_scan_proof_grade(evidence)
    verifier_confidence = _grade_scan_proof_confidence(evidence)

    if not verifier_grade or verifier_confidence is None:
        return False

    simple_proof = round(
        verifier_confidence
        * _normalized_match_score_component(evidence.get("match_score")),
        4,
    )

    row_grade = _normalize_grade(row.grade)
    verifier_grade_normalized = _normalize_grade(verifier_grade)

    return bool(
        _calculated_proof_can_auto_override(simple_proof)
        and _is_valid_grade(row_grade)
        and _is_valid_grade(verifier_grade_normalized)
        and _base_grade(row_grade) == _base_grade(verifier_grade_normalized)
    )


def _gemini_only_suppression_reason(reason: str | None) -> bool:
    return bool(reason and str(reason).startswith("__SUPPRESS_GEMINI_ONLY_KEEP_DOC_AI__:"))


def _strip_gemini_only_suppression_prefix(reason: str | None) -> str | None:
    if not reason:
        return reason

    text_value = str(reason)

    if text_value.startswith("__SUPPRESS_GEMINI_ONLY_KEEP_DOC_AI__:"):
        return text_value[len("__SUPPRESS_GEMINI_ONLY_KEEP_DOC_AI__:"):].strip()

    return reason


def _gemini_only_conflict_review_reason(
    gemini_row: NormalizedCourseRow,
    document_ai_rows: list[NormalizedCourseRow],
) -> str | None:
    """
    Handle unsafe Gemini-only duplicates.

    Important rule:
    A Gemini-only row is not allowed to create a Needs Review row only because
    Gemini disagrees with Document AI. If a nearby complete Document AI row
    exists and Gemini cannot prove Document AI wrong, suppress the Gemini-only
    duplicate and keep Document AI.

    Gemini-only can remain/auto-resolve only when focused verifier evidence
    confirms Gemini at the required auto-override confidence.
    """

    gemini_number = _course_number_from_raw(gemini_row.course_id)

    for doc_row in document_ai_rows:
        if not _source_only_context_matches(gemini_row, doc_row):
            continue

        if not _source_only_credits_compatible(gemini_row, doc_row):
            continue

        if not _course_names_same_identity(gemini_row.course_name, doc_row.course_name):
            continue

        doc_number = _course_number_from_raw(doc_row.course_id)
        numbers_differ = bool(
            gemini_number
            and doc_number
            and gemini_number != doc_number
        )

        gemini_grade = _normalize_grade(gemini_row.grade)
        doc_grade = _normalize_grade(doc_row.grade)
        grades_differ = bool(
            _is_valid_grade(gemini_grade)
            and _is_valid_grade(doc_grade)
            and _base_grade(gemini_grade) != _base_grade(doc_grade)
        )

        if not numbers_differ and not grades_differ:
            continue

        course_id_proved = (
            numbers_differ
            and not grades_differ
            and _source_only_course_id_verifier_confirms_row(gemini_row)
        )
        grade_proved = (
            grades_differ
            and not numbers_differ
            and _source_only_grade_verifier_confirms_row(gemini_row)
        )

        # Gemini proved this source-only conflict is correct. Allow the row to
        # continue; _build_final_from_single_source can then auto-resolve it if
        # all required fields are clean.
        if course_id_proved or grade_proved:
            continue

        conflict_bits: list[str] = []

        if numbers_differ:
            conflict_bits.append(
                f"course ID {gemini_row.course_id} conflicts with Document AI {doc_row.course_id}"
            )

        if grades_differ:
            conflict_bits.append(
                f"grade {gemini_grade} conflicts with Document AI {doc_grade}"
            )

        return (
            "__SUPPRESS_GEMINI_ONLY_KEEP_DOC_AI__: "
            "Gemini-only row was suppressed because it conflicts with a nearby "
            "valid Document AI row and Gemini/verifier did not prove Document AI "
            "wrong: "
            + "; ".join(conflict_bits)
            + "."
        )

    return None


# ---------------------------------------------------------------------------
# St. Anthony helpers
# ---------------------------------------------------------------------------

def _is_st_anthony_text(value: Any) -> bool:
    normalized = _normalize_text(value)

    return (
        "ST ANTHONY" in normalized
        or "SAINT ANTHONY" in normalized
    )


def _is_st_anthony_row(row: NormalizedCourseRow | None) -> bool:
    if row is None:
        return False

    text = " ".join(
        str(value or "")
        for value in [
            row.school_name,
            row.course_name,
            row.raw_payload,
        ]
    )

    return _is_st_anthony_text(text)


def _infer_st_anthony_grade_levels(
    rows: list[NormalizedCourseRow],
) -> dict[int, int]:
    years = sorted(
        {
            row.year
            for row in rows
            if row.year is not None
        }
    )

    grade_by_year: dict[int, int] = {}

    for index, year in enumerate(years):
        grade_by_year[year] = min(12, 9 + index)

    return grade_by_year


def _build_st_anthony_final_from_doc_row(
    row: NormalizedCourseRow,
    *,
    inferred_grade_level: int | None,
) -> dict[str, Any]:
    review_reasons: list[str] = []

    grade_level = row.grade_level if row.grade_level is not None else inferred_grade_level

    # St. Anthony/Saint Anthony:
    # - course_id is not required
    # - month is not required
    # - credits ARE required
    # - do not default missing credits to 5.0
    credit_attempted = row.credit_attempted
    credit_completed = row.credit_completed

    if not row.course_name:
        review_reasons.append("St. Anthony course name is missing.")

    if not row.grade or not _is_valid_grade(row.grade):
        review_reasons.append("St. Anthony grade is missing or invalid.")

    if grade_level is None:
        review_reasons.append("St. Anthony grade year is missing.")

    if row.year is None:
        review_reasons.append("St. Anthony academic year is missing.")

    if credit_attempted is None:
        review_reasons.append("St. Anthony attempted credits are missing.")
    elif not _is_plausible_credit(credit_attempted):
        review_reasons.append("St. Anthony attempted credits look invalid.")

    if credit_completed is None:
        review_reasons.append("St. Anthony completed credits are missing.")
    elif not _is_plausible_credit(credit_completed):
        review_reasons.append("St. Anthony completed credits look invalid.")

    needs_review = bool(review_reasons)

    return {
        "course_id": None,
        "course_name": row.course_name,
        "grade": row.grade,
        "grade_level": grade_level,
        "month": None,
        "year": row.year,
        "school_name": row.school_name,
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "needs_review": needs_review,
        "review_status": "needs_review" if needs_review else "auto_resolved",
        "review_reason": "; ".join(dict.fromkeys(review_reasons)) or None,
        "resolution_reason": (
            "st_anthony_document_ai_needs_review"
            if needs_review
            else "accepted_st_anthony_document_ai_only"
        ),
        "field_decisions": {
            "course_id": "not_applicable_st_anthony",
            "course_name": "document_ai" if row.course_name else "missing",
            "grade": "document_ai" if row.grade else "missing",
            "grade_level": (
                "document_ai"
                if row.grade_level is not None
                else "inferred_from_st_anthony_year"
                if grade_level is not None
                else "missing"
            ),
            "month": "not_applicable_st_anthony",
            "year": "document_ai" if row.year is not None else "missing",
            "school_name": "document_ai" if row.school_name else "missing",
            "credit_attempted": (
                "document_ai" if credit_attempted is not None else "missing"
            ),
            "credit_completed": (
                "document_ai" if credit_completed is not None else "missing"
            ),
        },
        "final_source": "document_ai",
    }



def _st_anthony_score_match(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> float:
    # St. Anthony has no course ID and no month, so row validation is based on
    # subject name, grade, credits, grade year, academic year, and weak row order.
    score = 0.0

    name_score = _names_similar(doc_row.course_name, gemini_row.course_name)
    score += name_score * 0.42

    same_grade = _same_grade(doc_row, gemini_row)
    if same_grade is True:
        score += 0.18
    elif same_grade is False:
        score -= 0.05

    if _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted) is True:
        score += 0.10

    if _same_credit(doc_row.credit_completed, gemini_row.credit_completed) is True:
        score += 0.10

    if _same_int(doc_row.grade_level, gemini_row.grade_level) is True:
        score += 0.08
    elif _same_int(doc_row.grade_level, gemini_row.grade_level) is False:
        score -= 0.03

    if _same_int(doc_row.year, gemini_row.year) is True:
        score += 0.08
    elif _same_int(doc_row.year, gemini_row.year) is False:
        score -= 0.03

    row_distance = abs((doc_row.row_index or 0) - (gemini_row.row_index or 0))

    if row_distance == 0:
        score += 0.04
    elif row_distance <= 2:
        score += 0.02
    elif row_distance > 8:
        score -= 0.04

    return max(0.0, min(round(score, 3), 1.0))


def _st_anthony_candidate_is_reasonable(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    score: float,
) -> bool:
    if score < 0.58:
        return False

    name_score = _names_similar(doc_row.course_name, gemini_row.course_name)

    if name_score < 0.82:
        return False

    supporting_matches = 0

    if _same_grade(doc_row, gemini_row) is True:
        supporting_matches += 1

    if (
        _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted) is True
        or _same_credit(doc_row.credit_completed, gemini_row.credit_completed) is True
    ):
        supporting_matches += 1

    if _same_int(doc_row.grade_level, gemini_row.grade_level) is True:
        supporting_matches += 1

    if _same_int(doc_row.year, gemini_row.year) is True:
        supporting_matches += 1

    return supporting_matches >= 1


def _match_st_anthony_rows(
    document_ai_rows: list[NormalizedCourseRow],
    gemini_rows: list[NormalizedCourseRow],
) -> tuple[
    list[tuple[NormalizedCourseRow, NormalizedCourseRow, float]],
    list[NormalizedCourseRow],
    list[NormalizedCourseRow],
]:
    candidates: list[tuple[float, int, int, int]] = []

    for doc_index, doc_row in enumerate(document_ai_rows):
        for gemini_index, gemini_row in enumerate(gemini_rows):
            score = _st_anthony_score_match(doc_row, gemini_row)

            if _st_anthony_candidate_is_reasonable(doc_row, gemini_row, score):
                row_distance = abs((doc_row.row_index or 0) - (gemini_row.row_index or 0))
                candidates.append((score, -row_distance, doc_index, gemini_index))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    used_doc_indexes: set[int] = set()
    used_gemini_indexes: set[int] = set()
    matched: list[tuple[NormalizedCourseRow, NormalizedCourseRow, float]] = []

    for score, _negative_distance, doc_index, gemini_index in candidates:
        if doc_index in used_doc_indexes or gemini_index in used_gemini_indexes:
            continue

        used_doc_indexes.add(doc_index)
        used_gemini_indexes.add(gemini_index)
        matched.append((document_ai_rows[doc_index], gemini_rows[gemini_index], score))

    doc_only = [
        row
        for index, row in enumerate(document_ai_rows)
        if index not in used_doc_indexes
    ]

    gemini_only = [
        row
        for index, row in enumerate(gemini_rows)
        if index not in used_gemini_indexes
    ]

    matched.sort(
        key=lambda item: (
            item[0].year or 0,
            item[0].grade_level or 0,
            item[0].row_index or 0,
        )
    )

    doc_only.sort(
        key=lambda row: (
            row.year or 0,
            row.grade_level or 0,
            row.row_index or 0,
        )
    )

    gemini_only.sort(
        key=lambda row: (
            row.year or 0,
            row.grade_level or 0,
            row.row_index or 0,
        )
    )

    return matched, doc_only, gemini_only


def _pick_st_anthony_name(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> tuple[Any, str, bool, str | None]:
    if doc_row.course_name and gemini_row.course_name:
        name_score = _names_similar(doc_row.course_name, gemini_row.course_name)

        if name_score >= 0.88:
            return doc_row.course_name, "both", False, None

        return doc_row.course_name, "document_ai_name_doubt", True, (
            f"St. Anthony course name differs: Document AI says {doc_row.course_name}; "
            f"Gemini says {gemini_row.course_name}."
        )

    if doc_row.course_name:
        return doc_row.course_name, "document_ai", False, None

    if gemini_row.course_name:
        return gemini_row.course_name, "gemini", False, None

    return None, "missing", True, "St. Anthony course name is missing from both sources."


def _pick_st_anthony_grade(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
) -> tuple[Any, str, bool, str | None]:
    doc_grade = _normalize_grade(doc_row.grade)
    gemini_grade = _normalize_grade(gemini_row.grade)

    if doc_grade and gemini_grade:
        if doc_grade == gemini_grade:
            return doc_row.grade, "both", False, None

        if _base_grade(doc_grade) == _base_grade(gemini_grade):
            return doc_row.grade, "same_base_grade_document_ai_kept", False, None

        return doc_row.grade, "document_ai_grade_doubt", True, (
            f"St. Anthony grade differs: Document AI says {doc_grade}; Gemini says {gemini_grade}."
        )

    if doc_grade:
        return doc_row.grade, "document_ai", False, None

    if gemini_grade:
        return gemini_row.grade, "gemini", False, None

    return None, "missing", True, "St. Anthony grade is missing from both sources."


def _pick_st_anthony_int(
    field_name: str,
    doc_value: Any,
    gemini_value: Any,
) -> tuple[int | None, str, bool, str | None]:
    doc_int = _coerce_int(doc_value)
    gemini_int = _coerce_int(gemini_value)

    if doc_int is not None and gemini_int is not None:
        if doc_int == gemini_int:
            return doc_int, "both", False, None

        if field_name == "grade_level":
            # St. Anthony grade level often comes from section/year inference.
            # A Doc AI vs Gemini grade-level conflict should not block
            # completion. Prefer Gemini when it is a valid grade level, then
            # fall back to the inferred/Document AI value. Use a non-Gemini
            # display source label so frontend does not advertise this as a
            # Gemini correction.
            if _is_valid_grade_level(gemini_int):
                return gemini_int, "st_anthony_resolved", False, None

            if _is_valid_grade_level(doc_int):
                return doc_int, "st_anthony_resolved", False, None

        return doc_int, f"document_ai_{field_name}_doubt", True, (
            f"St. Anthony {field_name} differs: Document AI says {doc_int}; Gemini says {gemini_int}."
        )

    if doc_int is not None:
        return doc_int, "document_ai", False, None

    if gemini_int is not None:
        if field_name == "grade_level" and _is_valid_grade_level(gemini_int):
            return gemini_int, "st_anthony_resolved", False, None

        return gemini_int, "gemini", False, None

    return None, "missing", True, f"St. Anthony {field_name} is missing from both sources."


def _pick_st_anthony_credit(
    field_name: str,
    doc_value: Any,
    gemini_value: Any,
) -> tuple[float | None, str, bool, str | None]:
    doc_float = _coerce_float(doc_value)
    gemini_float = _coerce_float(gemini_value)

    if doc_float is not None and gemini_float is not None:
        doc_bad = not _is_plausible_credit(doc_float)
        gemini_bad = not _is_plausible_credit(gemini_float)

        if _credits_equal(doc_float, gemini_float):
            if doc_bad:
                return doc_float, "both_bad_credit", True, (
                    f"St. Anthony {field_name} looks invalid."
                )

            return doc_float, "both", False, None

        # St. Anthony credits are usually read more reliably by Document AI from
        # the fixed SEM1/SEM2/S_SCH columns. A visible 0.0 credit can be correct
        # and must not be treated as bad. Therefore, when Document AI has a
        # plausible numeric credit, keep it and do not block completion just
        # because Gemini read a different value.
        if not doc_bad:
            return doc_float, "document_ai_credit_conflict_kept", False, None

        if doc_bad and not gemini_bad:
            return gemini_float, "gemini_doc_ai_bad_credit", False, None

        return doc_float, "document_ai_bad_credit", True, (
            f"St. Anthony {field_name} looks invalid."
        )

    if doc_float is not None:
        if not _is_plausible_credit(doc_float):
            return doc_float, "document_ai_bad_credit", True, (
                f"St. Anthony {field_name} looks invalid."
            )

        return doc_float, "document_ai", False, None

    if gemini_float is not None:
        if not _is_plausible_credit(gemini_float):
            return gemini_float, "gemini_bad_credit", True, (
                f"St. Anthony {field_name} looks invalid."
            )

        return gemini_float, "gemini", False, None

    return None, "missing", True, f"St. Anthony {field_name} is missing from both sources."


def _build_st_anthony_final_from_matched_rows(
    doc_row: NormalizedCourseRow,
    gemini_row: NormalizedCourseRow,
    *,
    inferred_grade_level: int | None,
) -> dict[str, Any]:
    review_reasons: list[str] = []
    field_decisions: dict[str, str] = {
        "course_id": "not_applicable_st_anthony",
        "month": "not_applicable_st_anthony",
    }

    def collect(field_name: str, decision: tuple[Any, str, bool, str | None]):
        value, source, needs_review, reason = decision
        field_decisions[field_name] = source

        # Non-decision fields (credit_attempted/month/school_name) and
        # format-absent columns (e.g. grade level missing from BOTH sources)
        # don't warrant manual review — keep the value, drop the blocking reason.
        if needs_review and reason and not _is_soft_review_reason(field_name, reason):
            review_reasons.append(reason)

        return value

    course_name = collect("course_name", _pick_st_anthony_name(doc_row, gemini_row))
    grade = collect("grade", _pick_st_anthony_grade(doc_row, gemini_row))

    doc_grade_level = (
        doc_row.grade_level
        if doc_row.grade_level is not None
        else inferred_grade_level
    )

    grade_level = collect(
        "grade_level",
        _pick_st_anthony_int(
            "grade_level",
            doc_grade_level,
            gemini_row.grade_level,
        ),
    )

    year = collect(
        "year",
        _pick_st_anthony_int(
            "year",
            doc_row.year,
            gemini_row.year,
        ),
    )

    school_name = collect(
        "school_name",
        _pick_text_field(
            "school_name",
            doc_row.school_name,
            gemini_row.school_name,
            require_similarity=False,
            gemini_confidence=gemini_row.confidence,
        ),
    )

    credit_attempted = collect(
        "credit_attempted",
        _pick_st_anthony_credit(
            "credit_attempted",
            doc_row.credit_attempted,
            gemini_row.credit_attempted,
        ),
    )

    credit_completed = collect(
        "credit_completed",
        _pick_st_anthony_credit(
            "credit_completed",
            doc_row.credit_completed,
            gemini_row.credit_completed,
        ),
    )

    if not course_name:
        review_reasons.append("St. Anthony final course name is missing.")

    if not grade or not _is_valid_grade(grade):
        review_reasons.append("St. Anthony final grade is missing or invalid.")

    if grade_level is None:
        review_reasons.append("St. Anthony final grade year is missing.")

    if year is None:
        review_reasons.append("St. Anthony final academic year is missing.")

    if credit_attempted is None:
        review_reasons.append("St. Anthony final attempted credits are missing.")

    if credit_completed is None:
        review_reasons.append("St. Anthony final completed credits are missing.")

    needs_review = bool(review_reasons)

    return {
        "course_id": None,
        "course_name": course_name,
        "grade": grade,
        "grade_level": grade_level,
        "month": None,
        "year": year,
        "school_name": school_name,
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "needs_review": needs_review,
        "review_status": "needs_review" if needs_review else "auto_resolved",
        "review_reason": "; ".join(dict.fromkeys(review_reasons)) or None,
        "resolution_reason": (
            "st_anthony_matched_needs_review"
            if needs_review
            else "st_anthony_matched_auto_resolved"
        ),
        "field_decisions": field_decisions,
        "final_source": "merged",
    }


def _build_st_anthony_final_from_gemini_only_row(
    row: NormalizedCourseRow,
    *,
    inferred_grade_level: int | None,
) -> dict[str, Any]:
    """
    Build a final row for a St. Anthony course found only by Gemini.

    St. Anthony has no course IDs/months. If Gemini found a complete,
    high-confidence row that Document AI missed, keep it and auto-resolve it
    instead of blocking completion. Incomplete, invalid, or low-confidence
    Gemini-only rows still go to Needs Review.
    """
    review_reasons: list[str] = []

    grade_level = row.grade_level if row.grade_level is not None else inferred_grade_level
    credit_attempted = row.credit_attempted
    credit_completed = row.credit_completed

    if not row.course_name:
        review_reasons.append("St. Anthony Gemini-only course name is missing.")

    if not row.grade or not _is_valid_grade(row.grade):
        review_reasons.append("St. Anthony Gemini-only grade is missing or invalid.")

    if grade_level is None:
        review_reasons.append("St. Anthony Gemini-only grade year is missing.")

    if row.year is None:
        review_reasons.append("St. Anthony Gemini-only academic year is missing.")

    if credit_attempted is None:
        review_reasons.append("St. Anthony Gemini-only attempted credits are missing.")
    elif not _is_plausible_credit(credit_attempted):
        review_reasons.append("St. Anthony Gemini-only attempted credits look invalid.")

    if credit_completed is None:
        review_reasons.append("St. Anthony Gemini-only completed credits are missing.")
    elif not _is_plausible_credit(credit_completed):
        review_reasons.append("St. Anthony Gemini-only completed credits look invalid.")

    if not _gemini_missing_field_confident(row.confidence):
        review_reasons.append(
            "St. Anthony Gemini-only row is below the 92% confidence threshold."
        )

    needs_review = bool(review_reasons)

    return {
        "course_id": None,
        "course_name": row.course_name,
        "grade": row.grade,
        "grade_level": grade_level,
        "month": None,
        "year": row.year,
        "school_name": row.school_name,
        "credit_attempted": credit_attempted,
        "credit_completed": credit_completed,
        "needs_review": needs_review,
        "review_status": "needs_review" if needs_review else "auto_resolved",
        "review_reason": "; ".join(dict.fromkeys(review_reasons)) or None,
        "resolution_reason": (
            "st_anthony_gemini_only_needs_review"
            if needs_review
            else "accepted_st_anthony_gemini_only_confident_extra"
        ),
        "field_decisions": {
            "course_id": "not_applicable_st_anthony",
            "course_name": "gemini" if row.course_name else "missing",
            "grade": "gemini" if row.grade else "missing",
            "grade_level": (
                "gemini"
                if row.grade_level is not None
                else "inferred_from_st_anthony_year"
                if grade_level is not None
                else "missing"
            ),
            "month": "not_applicable_st_anthony",
            "year": "gemini" if row.year is not None else "missing",
            "school_name": "gemini" if row.school_name else "missing",
            "credit_attempted": (
                "gemini" if credit_attempted is not None else "missing"
            ),
            "credit_completed": (
                "gemini" if credit_completed is not None else "missing"
            ),
        },
        "final_source": "gemini",
    }



def _st_anthony_likely_gemini_only_duplicate_of_document_ai(
    gemini_row: NormalizedCourseRow,
    document_ai_rows: list[NormalizedCourseRow],
) -> bool:
    """
    Safe St. Anthony equal-count duplicate guard.

    St. Anthony transcripts do not have course IDs/months, so occasional rows
    can remain Gemini-only after matching even when Doc AI and Gemini extracted
    the same number of courses. In that equal-count case, a Gemini-only row is
    usually a duplicate of a nearby Document AI row, not a real extra course.

    Only suppress when a likely Document AI counterpart exists. If Gemini has
    more rows than Document AI, this guard is not used and Gemini-only rows are
    still preserved for manual review.
    """
    if gemini_row is None:
        return False

    for doc_row in document_ai_rows:
        if doc_row is None:
            continue

        name_score = _names_similar(gemini_row.course_name, doc_row.course_name)
        same_name_identity = _course_names_same_identity(
            gemini_row.course_name,
            doc_row.course_name,
        )

        if name_score < 0.82 and not same_name_identity:
            continue

        year_match = _same_int(gemini_row.year, doc_row.year)
        grade_level_match = _same_int(gemini_row.grade_level, doc_row.grade_level)

        # Explicit year conflicts usually mean a different St. Anthony block.
        if year_match is False:
            continue

        # Grade-level conflicts are common in St. Anthony inference, so do not
        # hard-fail them when year/name/credits strongly agree.
        grade_match = _same_grade(gemini_row, doc_row)
        if grade_match is False:
            continue

        attempted_match = _same_credit(
            gemini_row.credit_attempted,
            doc_row.credit_attempted,
        )
        completed_match = _same_credit(
            gemini_row.credit_completed,
            doc_row.credit_completed,
        )

        if attempted_match is False or completed_match is False:
            continue

        row_distance = abs((gemini_row.row_index or 0) - (doc_row.row_index or 0))
        strong_context = sum(
            1
            for value in [year_match, grade_level_match, grade_match, attempted_match, completed_match]
            if value is True
        )

        if row_distance <= 8 and strong_context >= 2:
            return True

        if name_score >= 0.92 and strong_context >= 3:
            return True

    return False


def _calculate_expected_final_count(
    *,
    matched_count: int,
    inserted_document_ai_only_count: int,
    inserted_gemini_only_count: int,
) -> int:
    """
    Expected final count after reconciliation.

    Do not blindly use max(Document AI count, Gemini count), and do not use only
    Document AI count. The trusted final count is the rows we actually keep:

      matched rows
      + safe Document-AI-only rows
      + safe Gemini-only rows

    This supports both real cases:
      - Gemini finds a row Document AI missed.
      - Document AI finds a row Gemini missed.
    """

    return (
        max(int(matched_count or 0), 0)
        + max(int(inserted_document_ai_only_count or 0), 0)
        + max(int(inserted_gemini_only_count or 0), 0)
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CourseReconciliationService:
    def __init__(self, session: AsyncSession):
        self.session = session

        self.GeminiCourseDetails = _require_model(
            "GeminiCourseDetails",
            "GeminiCourseDetail",
            "Gemini_course_details",
            "GeminiCourse_details",
        )

        self.CourseExtractionMatches = _require_model(
            "CourseExtractionMatches",
            "CourseExtractionMatch",
            "Course_extraction_matches",
        )

        self.FinalCourseDetails = _require_model(
            "FinalCourseDetails",
            "FinalCourseDetail",
            "Final_course_details",
        )

    async def _clear_previous_outputs(self, extraction_file_id: int) -> None:
        await self.session.execute(
            delete(self.CourseExtractionMatches).where(
                _file_column(self.CourseExtractionMatches) == extraction_file_id
            )
        )

        await self.session.execute(
            delete(self.FinalCourseDetails).where(
                _file_column(self.FinalCourseDetails) == extraction_file_id
            )
        )

        await self.session.flush()

    async def _load_document_ai_rows(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int | None,
    ) -> list[NormalizedCourseRow]:
        """
        Load raw Document AI rows for this extraction file.

        Normal path keeps the student filter. If the student id on raw rows is
        missing/different after a rerun, fall back to source_file only so the
        reconciliation step never treats a successful extraction as zero rows.
        This fallback only runs when the strict query returns no rows.
        """

        base_stmt = select(models.Course_details).where(
            models.Course_details.source_file == extraction_file_id
        )

        stmt = base_stmt
        used_student_filter = student_db_id is not None

        if used_student_filter:
            stmt = stmt.where(models.Course_details.s_id == student_db_id)

        stmt = stmt.order_by(models.Course_details.id.asc())

        rows = (await self.session.execute(stmt)).scalars().all()

        if not rows and used_student_filter:
            fallback_stmt = base_stmt.order_by(models.Course_details.id.asc())
            rows = (await self.session.execute(fallback_stmt)).scalars().all()

            if rows:
                print(
                    "[COURSE RECONCILIATION] Loaded Document AI rows by source_file fallback "
                    f"file_id={extraction_file_id}, student_db_id={student_db_id}, rows={len(rows)}"
                )

        return [
            _normalize_doc_ai_row(row, index + 1)
            for index, row in enumerate(rows)
        ]

    async def _load_gemini_rows(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int | None,
    ) -> list[NormalizedCourseRow]:
        """
        Load raw Gemini rows for this extraction file.

        Keep the student filter when it works. If it hides every Gemini row
        because gemini_course_details.s_id is null/different, fall back to
        source_file only. This is intentionally small and safe: it does not
        change matching, field trust, count-owner logic, or any school-specific
        reconciliation rule.
        """

        file_col = _file_column(self.GeminiCourseDetails)
        base_stmt = select(self.GeminiCourseDetails).where(
            file_col == extraction_file_id
        )

        order_columns = []

        if _has_column(self.GeminiCourseDetails, "row_index"):
            order_columns.append(getattr(self.GeminiCourseDetails, "row_index"))

        if _has_column(self.GeminiCourseDetails, "course_index"):
            order_columns.append(getattr(self.GeminiCourseDetails, "course_index"))

        order_columns.append(getattr(self.GeminiCourseDetails, "id"))

        student_col = _student_column(self.GeminiCourseDetails)
        used_student_filter = student_db_id is not None and student_col is not None

        stmt = base_stmt

        if used_student_filter:
            stmt = stmt.where(student_col == student_db_id)

        stmt = stmt.order_by(*order_columns)

        rows = (await self.session.execute(stmt)).scalars().all()

        if not rows and used_student_filter:
            fallback_stmt = base_stmt.order_by(*order_columns)
            rows = (await self.session.execute(fallback_stmt)).scalars().all()

            if rows:
                print(
                    "[COURSE RECONCILIATION] Loaded Gemini rows by source_file fallback "
                    f"file_id={extraction_file_id}, student_db_id={student_db_id}, rows={len(rows)}"
                )

        return [
            _normalize_gemini_row(row, index + 1)
            for index, row in enumerate(rows)
        ]

    async def _resolve_transcript_pdf_path(
        self,
        *,
        extraction_file_id: int,
        explicit_pdf_path: str | None = None,
    ) -> Path | None:
        """
        Find the local PDF path for optional geometry extraction.

        Safe behavior:
        - If no path can be resolved, return None.
        - Reconciliation then falls back to the existing logic.
        - No DB schema or extractor behavior changes are required.

        Supported ways to resolve:
        1. explicit pdf_path passed by transcript_processor later.
        2. file path-like columns on extraction_file_details if available.
        3. TRANSCRIPT_GEOMETRY_PDF_ROOT / TRANSCRIPT_PDF_ROOT env folders + file_name.
        4. a few common local upload folders under the current working directory.
        """

        candidates: list[Path] = []

        def add_candidate(value: Any) -> None:
            if value in (None, ""):
                return

            raw = str(value).strip().strip('"').strip("'")

            if not raw:
                return

            # Ignore cloud-only URIs here. They need to be downloaded by the
            # caller before geometry can read them with PyMuPDF.
            if raw.startswith("gs://") or raw.startswith("http://") or raw.startswith("https://"):
                return

            candidates.append(Path(raw))

        add_candidate(explicit_pdf_path)

        file_record = await self.session.get(
            models.ExtractionFileDetails,
            extraction_file_id,
        )

        file_name = None

        if file_record is not None:
            file_name = _get_attr(file_record, "file_name", "filename", "name")

            for attr_name in [
                "local_pdf_path",
                "pdf_path",
                "local_file_path",
                "file_path",
                "source_path",
                "input_file_path",
                "uploaded_file_path",
                "storage_path",
                "path",
            ]:
                add_candidate(_get_attr(file_record, attr_name))

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except Exception:
                continue

        if not file_name:
            return None

        env_roots = [
            os.getenv("TRANSCRIPT_GEOMETRY_PDF_ROOT"),
            os.getenv("TRANSCRIPT_PDF_ROOT"),
            os.getenv("TRANSCRIPT_UPLOAD_ROOT"),
            os.getenv("UPLOAD_FOLDER"),
        ]

        common_roots = [
            Path.cwd(),
            Path.cwd() / "uploads",
            Path.cwd() / "transcripts",
            Path.cwd() / "data",
            Path.cwd() / "apps" / "backend" / "uploads",
            Path.cwd() / "apps" / "backend" / "data",
        ]

        for root_value in env_roots:
            if not root_value:
                continue

            root = Path(str(root_value).strip().strip('"').strip("'"))
            candidate = root / str(file_name)

            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except Exception:
                continue

        for root in common_roots:
            candidate = root / str(file_name)

            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except Exception:
                continue

        return None

    async def _load_transcript_geometry_rows(
        self,
        *,
        extraction_file_id: int,
        pdf_path: str | None = None,
        pdf_bytes: bytes | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Load optional deterministic row geometry.

        If ``pdf_bytes`` is supplied (the transcript already in memory during
        processing), geometry is read directly from memory and no file is
        written to or read from disk. Otherwise a local PDF path is resolved.

        This helper must never break reconciliation. Any import/path/parser
        problem becomes a diagnostic warning and the existing matching path is
        used unchanged.
        """

        diagnostics: dict[str, Any] = {
            "enabled": extract_transcript_row_geometry is not None,
            "pdf_path": None,
            "geometry_rows": 0,
            "error": None,
        }

        if extract_transcript_row_geometry is None:
            diagnostics["error"] = "transcript_row_geometry helper is not available."
            return [], diagnostics

        # Preferred path: read straight from the in-memory transcript bytes.
        # Nothing is written to or kept on disk.
        if pdf_bytes:
            diagnostics["pdf_path"] = "<in-memory bytes>"
            try:
                geometry_rows = extract_transcript_row_geometry(pdf_bytes=pdf_bytes)
            except Exception as exc:
                diagnostics["error"] = f"transcript_row_geometry failed (bytes): {exc}"
                return [], diagnostics
            diagnostics["geometry_rows"] = len(geometry_rows or [])
            return list(geometry_rows or []), diagnostics

        resolved_path = await self._resolve_transcript_pdf_path(
            extraction_file_id=extraction_file_id,
            explicit_pdf_path=pdf_path,
        )

        if resolved_path is None:
            diagnostics["error"] = (
                "No local transcript PDF path could be resolved for geometry. "
                "Set TRANSCRIPT_GEOMETRY_PDF_ROOT or pass pdf_path from transcript_processor."
            )
            return [], diagnostics

        diagnostics["pdf_path"] = str(resolved_path)

        try:
            geometry_rows = extract_transcript_row_geometry(resolved_path)
        except Exception as exc:
            diagnostics["error"] = f"transcript_row_geometry failed: {exc}"
            return [], diagnostics

        diagnostics["geometry_rows"] = len(geometry_rows or [])
        return list(geometry_rows or []), diagnostics

    async def _is_st_anthony_file(
        self,
        *,
        extraction_file_id: int,
        document_ai_rows: list[NormalizedCourseRow],
        gemini_rows: list[NormalizedCourseRow],
    ) -> bool:
        file_record = await self.session.get(
            models.ExtractionFileDetails,
            extraction_file_id,
        )

        file_text = ""

        if file_record is not None:
            file_text = " ".join(
                str(_get_attr(file_record, field) or "")
                for field in [
                    "file_name",
                    "transcript_format",
                    "school_name",
                    "school",
                    "detected_school",
                    "classifier_label",
                    "classification_label",
                    "transcript_type",
                ]
            )

        if _is_st_anthony_text(file_text):
            return True

        return any(_is_st_anthony_row(row) for row in document_ai_rows + gemini_rows)

    def _build_match_values(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int,
        doc_row: NormalizedCourseRow | None,
        gemini_row: NormalizedCourseRow | None,
        match_type: str,
        match_confidence: float | None,
        final_values: dict[str, Any],
        final_course_detail_id: int | None = None,
    ) -> dict[str, Any]:
        raw_field_decisions = final_values.get("field_decisions") or {}
        field_decisions = _compact_field_decisions(raw_field_decisions)

        name_score = (
            _names_similar(doc_row.course_name, gemini_row.course_name)
            if doc_row is not None and gemini_row is not None
            else None
        )

        same_course_id = _same_course_id(doc_row, gemini_row)

        course_id_score = (
            1.0
            if same_course_id is True
            else 0.0
            if same_course_id is False
            else None
        )

        values = {
            "extraction_file_id": extraction_file_id,
            "source_file": extraction_file_id,
            "s_id": student_db_id,
            "student_id": student_db_id,

            "document_ai_course_detail_id": doc_row.row_id if doc_row else None,
            "gemini_course_detail_id": gemini_row.row_id if gemini_row else None,

            "final_course_detail_id": final_course_detail_id,
            "applied_final_course_detail_id": final_course_detail_id,

            "match_type": str(match_type),
            "match_confidence": match_confidence,

            "course_id_match": _same_course_id(doc_row, gemini_row),
            "course_name_match": _same_name(doc_row, gemini_row),
            "letter_grade_match": _same_grade(doc_row, gemini_row),
            "grade_level_match": (
                _same_int(doc_row.grade_level, gemini_row.grade_level)
                if doc_row is not None and gemini_row is not None
                else None
            ),
            "month_match": (
                _same_int(doc_row.month, gemini_row.month)
                if doc_row is not None and gemini_row is not None
                else None
            ),
            "year_match": (
                _same_int(doc_row.year, gemini_row.year)
                if doc_row is not None and gemini_row is not None
                else None
            ),
            "credit_attempted_match": (
                _same_credit(doc_row.credit_attempted, gemini_row.credit_attempted)
                if doc_row is not None and gemini_row is not None
                else None
            ),
            "credit_completed_match": (
                _same_credit(doc_row.credit_completed, gemini_row.credit_completed)
                if doc_row is not None and gemini_row is not None
                else None
            ),

            "course_name_score": name_score,
            "course_id_score": course_id_score,
            "overall_match_score": match_confidence,

            "selected_course_id_source": _compact_source_label(field_decisions.get("course_id")),
            "selected_course_name_source": _compact_source_label(field_decisions.get("course_name")),
            "selected_letter_grade_source": _compact_source_label(field_decisions.get("grade")),
            "selected_grade_level_source": _compact_source_label(field_decisions.get("grade_level")),
            "selected_month_source": _compact_source_label(field_decisions.get("month")),
            "selected_year_source": _compact_source_label(field_decisions.get("year")),
            "selected_credit_attempted_source": _compact_source_label(field_decisions.get("credit_attempted")),
            "selected_credit_completed_source": _compact_source_label(field_decisions.get("credit_completed")),

            "needs_review": bool(final_values.get("needs_review", False)),
            "review_reason": final_values.get("review_reason"),
            "resolution_reason": final_values.get("resolution_reason"),
            "reviewed_by_user": False,
            "reviewed_at": None,

            "document_ai_snapshot": _course_payload(doc_row),
            "gemini_snapshot": _course_payload(gemini_row),
            "field_differences": _build_field_differences(doc_row, gemini_row),
            # Compact source labels only; do not store long decision reasons here.
            "field_decisions": field_decisions,

            "created_at": _now(),
            "updated_at": _now(),
        }

        cleaned = _filter_model_values(self.CourseExtractionMatches, values)

        for fk_name in ("final_course_detail_id", "applied_final_course_detail_id"):
            if fk_name in cleaned and cleaned[fk_name] not in (None, ""):
                cleaned[fk_name] = _coerce_int(cleaned[fk_name])

        return cleaned

    def _build_final_values(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int,
        doc_row: NormalizedCourseRow | None,
        gemini_row: NormalizedCourseRow | None,
        final_values: dict[str, Any],
    ) -> dict[str, Any]:
        raw_field_decisions = final_values.get("field_decisions") or {}
        field_decisions = _compact_field_decisions(raw_field_decisions)

        values = {
            "source_file": extraction_file_id,
            "s_id": student_db_id,

            "document_ai_course_detail_id": doc_row.row_id if doc_row else None,
            "gemini_course_detail_id": gemini_row.row_id if gemini_row else None,

            "crs_id": final_values.get("course_id"),
            "crs_letter_grade": final_values.get("grade"),
            "crs_description": final_values.get("course_name"),
            "crs_hs": final_values.get("school_name"),
            "crs_grade": final_values.get("grade_level"),
            "crs_month": final_values.get("month"),
            "crs_year": final_values.get("year"),
            "crs_credit_attempted": final_values.get("credit_attempted"),
            "crs_credit_completed": final_values.get("credit_completed"),
            "crs_term_gpa": None,

            "final_source": final_values.get("final_source") or "merged",

            "crs_id_source": _compact_source_label(field_decisions.get("course_id")),
            "crs_description_source": _compact_source_label(field_decisions.get("course_name")),
            "crs_letter_grade_source": _compact_source_label(field_decisions.get("grade")),
            "crs_hs_source": _compact_source_label(field_decisions.get("school_name")),
            "crs_grade_source": _compact_source_label(field_decisions.get("grade_level")),
            "crs_month_source": _compact_source_label(field_decisions.get("month")),
            "crs_year_source": _compact_source_label(field_decisions.get("year")),
            "crs_credit_attempted_source": _compact_source_label(field_decisions.get("credit_attempted")),
            "crs_credit_completed_source": _compact_source_label(field_decisions.get("credit_completed")),
            "crs_term_gpa_source": None,

            "review_status": final_values.get("review_status") or (
                "needs_review"
                if final_values.get("needs_review")
                else "auto_resolved"
            ),
            "needs_review": bool(final_values.get("needs_review", False)),
            "review_reason": final_values.get("review_reason"),
            "resolution_reason": final_values.get("resolution_reason"),

            "document_ai_snapshot": _course_payload(doc_row),
            "gemini_snapshot": _course_payload(gemini_row),
            # Compact source labels only; do not store long decision reasons here.
            "field_decisions": field_decisions,

            "created_at": _now(),
            "updated_at": _now(),
        }

        return _filter_model_values(self.FinalCourseDetails, values)

    async def _insert_match_and_final(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int,
        doc_row: NormalizedCourseRow | None,
        gemini_row: NormalizedCourseRow | None,
        match_type: str,
        match_confidence: float | None,
        final_values: dict[str, Any],
    ) -> tuple[Any, Any]:
        _apply_course_name_repair_to_final_values(final_values)

        match_values = self._build_match_values(
            extraction_file_id=extraction_file_id,
            student_db_id=student_db_id,
            doc_row=doc_row,
            gemini_row=gemini_row,
            match_type=match_type,
            match_confidence=match_confidence,
            final_values=final_values,
            final_course_detail_id=None,
        )

        match_row = self.CourseExtractionMatches(**match_values)
        self.session.add(match_row)

        final_row_values = self._build_final_values(
            extraction_file_id=extraction_file_id,
            student_db_id=student_db_id,
            doc_row=doc_row,
            gemini_row=gemini_row,
            final_values=final_values,
        )

        final_row = self.FinalCourseDetails(**final_row_values)
        self.session.add(final_row)
        # Single flush inserts both the match and the final together (the match's
        # back-link to the final id is set just below), instead of flushing the
        # match separately first. Nothing reads the match id before this point.
        await self.session.flush()

        final_id = _row_id(final_row)

        if _has_column(self.CourseExtractionMatches, "final_course_detail_id"):
            match_row.final_course_detail_id = final_id

        if _has_column(self.CourseExtractionMatches, "applied_final_course_detail_id"):
            match_row.applied_final_course_detail_id = final_id

        # Reverse link (final -> match) for data completeness. The app navigates
        # match -> final today, so this column was previously left null; populate
        # it so a final row can be traced back to its reconciliation match.
        if _has_column(self.FinalCourseDetails, "course_extraction_match_id"):
            final_row.course_extraction_match_id = _row_id(match_row)

        await self.session.flush()

        return match_row, final_row

    async def _count_final_rows(self, extraction_file_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(self.FinalCourseDetails)
            .where(_file_column(self.FinalCourseDetails) == extraction_file_id)
        )

        return int(result.scalar_one() or 0)

    async def _count_final_needs_review(self, extraction_file_id: int) -> int:
        if not _has_column(self.FinalCourseDetails, "needs_review"):
            return 0

        result = await self.session.execute(
            select(func.count())
            .select_from(self.FinalCourseDetails)
            .where(
                _file_column(self.FinalCourseDetails) == extraction_file_id,
                getattr(self.FinalCourseDetails, "needs_review").is_(True),
            )
        )

        return int(result.scalar_one() or 0)

    async def _update_file_status(
        self,
        *,
        extraction_file_id: int,
        final_status: str,
    ) -> None:
        values = {
            "process_status": final_status,
            "processed_date": _now(),
        }

        values = _filter_model_values(models.ExtractionFileDetails, values)

        await self.session.execute(
            update(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == extraction_file_id)
            .values(**values)
        )

    async def _reconcile_st_anthony_merged(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int,
        document_ai_rows: list[NormalizedCourseRow],
        gemini_rows: list[NormalizedCourseRow],
        document_ai_count: int,
        gemini_count: int,
    ) -> dict[str, Any]:
        # St. Anthony final rows use Document AI as the primary row set so
        # SEM1/SEM2 rows do not collapse or double. Gemini rows are matched
        # and linked when possible so validated rows show Document AI + Gemini.
        #
        # Important safety rule:
        # unmatched Gemini rows are NOT skipped. If Gemini found a St. Anthony
        # row that Document AI did not match, insert it as Gemini-only Needs
        # Review so a possibly real missing course is not lost.
        grade_by_year = _infer_st_anthony_grade_levels(document_ai_rows + gemini_rows)

        matched, doc_only, gemini_only = _match_st_anthony_rows(
            document_ai_rows,
            gemini_rows,
        )

        work_items: list[dict[str, Any]] = []

        for doc_row, gemini_row, match_confidence in matched:
            final_values = _build_st_anthony_final_from_matched_rows(
                doc_row,
                gemini_row,
                inferred_grade_level=grade_by_year.get(doc_row.year),
            )

            work_items.append(
                {
                    "kind": "matched",
                    "sort_order": (
                        doc_row.year or 0,
                        doc_row.grade_level or 0,
                        doc_row.row_index or 0,
                    ),
                    "doc_row": doc_row,
                    "gemini_row": gemini_row,
                    "match_confidence": match_confidence,
                    "final_values": final_values,
                }
            )

        for doc_row in doc_only:
            final_values = _build_st_anthony_final_from_doc_row(
                doc_row,
                inferred_grade_level=grade_by_year.get(doc_row.year),
            )

            work_items.append(
                {
                    "kind": "document_ai_only",
                    "sort_order": (
                        doc_row.year or 0,
                        doc_row.grade_level or 0,
                        doc_row.row_index or 0,
                    ),
                    "doc_row": doc_row,
                    "gemini_row": None,
                    "match_confidence": None,
                    "final_values": final_values,
                }
            )

        suppressed_st_anthony_gemini_duplicate_count = 0

        for gemini_row in gemini_only:
            if (
                document_ai_count == gemini_count
                and _st_anthony_likely_gemini_only_duplicate_of_document_ai(
                    gemini_row,
                    document_ai_rows,
                )
            ):
                suppressed_st_anthony_gemini_duplicate_count += 1
                continue

            final_values = _build_st_anthony_final_from_gemini_only_row(
                gemini_row,
                inferred_grade_level=grade_by_year.get(gemini_row.year),
            )

            work_items.append(
                {
                    "kind": "gemini_only",
                    "sort_order": (
                        gemini_row.year or 0,
                        gemini_row.grade_level or 0,
                        gemini_row.row_index or 0,
                    ),
                    "doc_row": None,
                    "gemini_row": gemini_row,
                    "match_confidence": gemini_row.confidence,
                    "final_values": final_values,
                }
            )

        work_items.sort(key=lambda item: item["sort_order"])

        matched_count = 0
        doc_only_count = 0
        gemini_only_count = 0

        for item in work_items:
            kind = item["kind"]

            await self._insert_match_and_final(
                extraction_file_id=extraction_file_id,
                student_db_id=student_db_id,
                doc_row=item["doc_row"],
                gemini_row=item["gemini_row"],
                match_type=kind,
                match_confidence=item["match_confidence"],
                final_values=item["final_values"],
            )

            if kind == "matched":
                matched_count += 1
            elif kind == "document_ai_only":
                doc_only_count += 1
            elif kind == "gemini_only":
                gemini_only_count += 1

        final_course_count = await self._count_final_rows(extraction_file_id)
        needs_review_count = await self._count_final_needs_review(extraction_file_id)

        target_final_count = _calculate_expected_final_count(
            matched_count=matched_count,
            inserted_document_ai_only_count=doc_only_count,
            inserted_gemini_only_count=gemini_only_count,
        )

        expected_final_count = document_ai_count + gemini_only_count

        review_reasons: list[str] = []
        warnings: list[str] = []

        if final_course_count == 0:
            review_reasons.append(
                "No final course rows were created for St. Anthony."
            )

        if needs_review_count > 0:
            review_reasons.append(
                f"{needs_review_count} St. Anthony final row(s) need manual review."
            )

        if gemini_count == 0:
            review_reasons.append(
                "Gemini returned zero St. Anthony rows, so row-level validation could not be performed."
            )

        if document_ai_count != gemini_count:
            warnings.append(
                f"St. Anthony raw row counts differ: Document AI={document_ai_count}, Gemini={gemini_count}."
            )

        if doc_only_count > 0 and gemini_count > 0:
            warnings.append(
                f"{doc_only_count} St. Anthony Document AI row(s) were not matched to Gemini and are shown as Document AI only."
            )

        if gemini_only_count > 0:
            review_reasons.append(
                f"{gemini_only_count} St. Anthony Gemini-only row(s) were inserted for manual review instead of being skipped."
            )

        if suppressed_st_anthony_gemini_duplicate_count > 0:
            warnings.append(
                f"{suppressed_st_anthony_gemini_duplicate_count} likely duplicate St. Anthony Gemini-only row(s) were suppressed because Document AI and Gemini raw counts were equal."
            )

        if final_course_count < expected_final_count:
            review_reasons.append(
                f"Final rows are short by {expected_final_count - final_course_count} row(s)."
            )

        if final_course_count > expected_final_count:
            review_reasons.append(
                f"Final rows exceed expected St. Anthony count by {final_course_count - expected_final_count} row(s)."
            )

        final_status = (
            "completed"
            if final_course_count > 0
            and needs_review_count == 0
            and final_course_count == expected_final_count
            and gemini_count > 0
            else "needs_review"
        )

        await self._update_file_status(
            extraction_file_id=extraction_file_id,
            final_status=final_status,
        )

        await self.session.commit()

        result = {
            "status": final_status,
            "file_status": final_status,
            "process_status": final_status,
            "validation_type": "st_anthony_reconciliation",
            "extraction_file_id": extraction_file_id,
            "student_db_id": student_db_id,

            "document_ai_course_count": document_ai_count,
            "raw_document_ai_course_count": document_ai_count,
            "course_details_count": document_ai_count,

            "gemini_course_count": gemini_count,
            "raw_gemini_course_count": gemini_count,
            "gemini_course_details_count": gemini_count,

            "primary_source": "document_ai",
            "target_final_count": expected_final_count,

            "initial_matched_count": matched_count,
            "match_coverage": round(
                matched_count / min(document_ai_count, gemini_count),
                3,
            ) if min(document_ai_count, gemini_count) > 0 else 0,
            "low_match_coverage": False,

            "matched_count": matched_count,
            "matched_course_count": matched_count,
            "document_ai_only_count": doc_only_count,
            "gemini_only_count": gemini_only_count,

            "skipped_document_ai_only_count": 0,
            "skipped_gemini_only_count": suppressed_st_anthony_gemini_duplicate_count,

            "suppressed_document_ai_duplicate_count": 0,
            "suppressed_gemini_duplicate_count": suppressed_st_anthony_gemini_duplicate_count,

            "final_course_count": final_course_count,
            "actual_final_course_count": final_course_count,
            "final_course_details_count": final_course_count,
            "expected_final_course_count": expected_final_count,

            "needs_review_count": needs_review_count,
            "open_review_count": needs_review_count,

            # St. Anthony Gemini linking is validation, not auto-fixing.
            "auto_fixed_count": 0,
            "review_reason": "; ".join(review_reasons) or None,
            "review_reasons": review_reasons,
            "warnings": warnings,
            "counts_match": document_ai_count == gemini_count,
            "school_rule": "st_anthony_document_ai_primary_gemini_validation_with_gemini_only_review",
        }

        print(
            "[ST ANTHONY RECONCILIATION SAVED] "
            f"file_id={extraction_file_id}, "
            f"status={final_status}, "
            f"doc_ai={document_ai_count}, "
            f"gemini={gemini_count}, "
            f"matched={matched_count}, "
            f"doc_only={doc_only_count}, "
            f"gemini_only={gemini_only_count}, "
            f"final={final_course_count}, "
            f"expected_final={expected_final_count}, "
            f"needs_review={needs_review_count}"
        )

        return result


    async def reconcile_file(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int,
        document_ai_course_count: int | None = None,
        gemini_course_count: int | None = None,
        pdf_path: str | None = None,
        pdf_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        await self._clear_previous_outputs(extraction_file_id)

        document_ai_rows = await self._load_document_ai_rows(
            extraction_file_id=extraction_file_id,
            student_db_id=student_db_id,
        )

        gemini_rows = await self._load_gemini_rows(
            extraction_file_id=extraction_file_id,
            student_db_id=student_db_id,
        )

        document_ai_count = (
            document_ai_course_count
            if document_ai_course_count is not None
            else len(document_ai_rows)
        )

        gemini_count = (
            gemini_course_count
            if gemini_course_count is not None
            else len(gemini_rows)
        )

        st_anthony_file = await self._is_st_anthony_file(
            extraction_file_id=extraction_file_id,
            document_ai_rows=document_ai_rows,
            gemini_rows=gemini_rows,
        )

        geometry_diagnostics: dict[str, Any] = {
            "enabled": extract_transcript_row_geometry is not None,
            "pdf_path": None,
            "geometry_rows": 0,
            "error": None,
            "attached": {},
        }

        # St. Anthony has a different layout and already has dedicated rules.
        # Use geometry only for Mayfair/LBUSD-style dense column transcripts.
        if not st_anthony_file and (document_ai_rows or gemini_rows):
            geometry_rows, geometry_diagnostics = await self._load_transcript_geometry_rows(
                extraction_file_id=extraction_file_id,
                pdf_path=pdf_path,
                pdf_bytes=pdf_bytes,
            )

            if geometry_rows:
                geometry_attach_stats = _attach_transcript_geometry_to_rows(
                    document_ai_rows=document_ai_rows,
                    gemini_rows=gemini_rows,
                    geometry_rows=geometry_rows,
                )
                geometry_diagnostics["attached"] = geometry_attach_stats

        if st_anthony_file:
            return await self._reconcile_st_anthony_merged(
                extraction_file_id=extraction_file_id,
                student_db_id=student_db_id,
                document_ai_rows=document_ai_rows,
                gemini_rows=gemini_rows,
                document_ai_count=document_ai_count,
                gemini_count=gemini_count,
            )

        matched, doc_only, gemini_only = _match_rows(
            document_ai_rows,
            gemini_rows,
        )

        rescued_matches, doc_only, gemini_only = _rescue_doc_ai_only_rows_with_gemini(
            doc_only,
            gemini_only,
        )

        if rescued_matches:
            matched.extend(rescued_matches)
            matched.sort(
                key=lambda item: (
                    item[1].row_index or 0,
                    item[0].year or 0,
                    item[0].grade_level or 0,
                    item[0].month or 0,
                    item[0].row_index or 0,
                )
            )

        both_sources_present = bool(document_ai_count > 0 and gemini_count > 0)
        gemini_unavailable = bool(document_ai_count > 0 and gemini_count == 0)
        document_ai_unavailable = bool(gemini_count > 0 and document_ai_count == 0)

        primary_source = _select_primary_source(
            document_ai_count=document_ai_count,
            gemini_count=gemini_count,
        )

        max_source_count = max(document_ai_count, gemini_count)
        min_source_count = min(
            count
            for count in [document_ai_count, gemini_count]
            if count > 0
        ) if max_source_count > 0 else 0

        initial_matched_count = len(matched)
        match_coverage = (
            initial_matched_count / min_source_count
            if min_source_count > 0
            else 0.0
        )

        low_match_coverage = bool(
            both_sources_present
            and min_source_count >= 5
            and match_coverage < LOW_MATCH_COVERAGE_THRESHOLD
        )

        matched_count = 0
        doc_only_count = 0
        gemini_only_count = 0
        skipped_document_ai_only_count = 0
        skipped_gemini_only_count = 0
        auto_fixed_count = 0

        work_items: list[dict[str, Any]] = []
        seen_source_only_signatures: set[tuple[Any, ...]] = set()

        count_owner_source = _select_course_count_owner(
            document_ai_count=document_ai_count,
            gemini_count=gemini_count,
        )
        target_final_count: int | None = None

        def add_matched_rows() -> None:
            # Step 1: match whatever can be safely matched.
            for doc_row, gemini_row, match_confidence in matched:
                final_values = _build_final_from_matched_rows(
                    doc_row,
                    gemini_row,
                    match_confidence=match_confidence,
                    count_owner_source=count_owner_source,
                    all_document_ai_rows=document_ai_rows,
                    all_gemini_rows=gemini_rows,
                )

                # Step 2: _build_final_from_matched_rows() compares all fields
                # and keeps trusted values field-by-field.
                work_items.append(
                    {
                        "kind": "matched",
                        "priority": 0,
                        "sort_order": (
                            gemini_row.row_index or 0,
                            doc_row.year or 0,
                            doc_row.grade_level or 0,
                            doc_row.month or 0,
                            doc_row.row_index or 0,
                        ),
                        "doc_row": doc_row,
                        "gemini_row": gemini_row,
                        "match_confidence": match_confidence,
                        "final_values": final_values,
                        "force_review_reason": None,
                    }
                )

        def add_gemini_only_rows(*, priority: int) -> None:
            nonlocal skipped_gemini_only_count

            for gemini_row in gemini_only:
                conflict_reason = _gemini_only_conflict_review_reason(
                    gemini_row,
                    document_ai_rows,
                )

                if _gemini_only_suppression_reason(conflict_reason):
                    skipped_gemini_only_count += 1
                    continue

                work_items.append(
                    {
                        "kind": "gemini_only",
                        "priority": priority,
                        "sort_order": (
                            gemini_row.row_index or 0,
                            gemini_row.year or 0,
                            gemini_row.grade_level or 0,
                            gemini_row.month or 0,
                        ),
                        "doc_row": None,
                        "gemini_row": gemini_row,
                        "match_confidence": gemini_row.confidence,
                        "force_review_reason": _combine_review_reasons(
                            _source_only_duplicate_review_reason(
                                gemini_row,
                                seen_source_only_signatures,
                            ),
                            _strip_gemini_only_suppression_prefix(conflict_reason),
                        ),
                    }
                )

        def add_document_ai_only_rows(*, priority: int) -> None:
            for doc_row in doc_only:
                work_items.append(
                    {
                        "kind": "document_ai_only",
                        "priority": priority,
                        "sort_order": (
                            doc_row.year or 0,
                            doc_row.grade_level or 0,
                            doc_row.month or 0,
                            doc_row.row_index or 0,
                        ),
                        "doc_row": doc_row,
                        "gemini_row": None,
                        "match_confidence": None,
                        "force_review_reason": _source_only_duplicate_review_reason(
                            doc_row,
                            seen_source_only_signatures,
                        ),
                    }
                )

        add_matched_rows()

        # Step 3: preserve source-only rows from the course-count owner only.
        #
        # This prevents inflated finals like:
        #   matched rows + Document-AI-only rows + Gemini-only rows
        # when matching coverage is low and both extractors actually describe
        # many of the same transcript rows.
        #
        # Example:
        #   Document AI = 55, Gemini = 62, matched = 31
        #   Correct target follows Gemini: 31 matched + 31 Gemini-only = 62
        #   Do NOT also add the 24 unmatched Document-AI-only rows, because those
        #   are likely rows Gemini already represented but the matcher failed to link.
        if both_sources_present:
            if count_owner_source == "gemini":
                add_gemini_only_rows(priority=1)
                skipped_document_ai_only_count += len(doc_only)
            else:
                add_document_ai_only_rows(priority=1)
                skipped_gemini_only_count += len(gemini_only)
        elif document_ai_unavailable:
            add_gemini_only_rows(priority=1)
        elif gemini_unavailable:
            add_document_ai_only_rows(priority=1)
        else:
            # Defensive fallback for empty/odd inputs.
            add_document_ai_only_rows(priority=1)
            add_gemini_only_rows(priority=2)

        # Safety fallback: never leave a transcript with raw extracted rows but
        # zero final rows. If matching/source-only suppression produced no work
        # items, preserve the course-count owner source as Needs Review rows.
        # This keeps the count-owner rule intact and prevents a blank review
        # screen such as raw max source rows=71 but final_course_details=0.
        if not work_items and (document_ai_rows or gemini_rows):
            emergency_reason = (
                "Emergency reconciliation fallback: raw extractor rows existed, "
                "but no final work items were produced. Preserved the course-count "
                "owner rows for manual review instead of creating an empty final transcript."
            )

            if count_owner_source == "gemini" and gemini_rows:
                for gemini_row in gemini_rows:
                    work_items.append(
                        {
                            "kind": "gemini_only",
                            "priority": 99,
                            "sort_order": (
                                gemini_row.year or 0,
                                gemini_row.grade_level or 0,
                                gemini_row.month or 0,
                                gemini_row.row_index or 0,
                            ),
                            "doc_row": None,
                            "gemini_row": gemini_row,
                            "match_confidence": gemini_row.confidence,
                            "force_review_reason": _combine_review_reasons(
                                emergency_reason,
                                _source_only_duplicate_review_reason(
                                    gemini_row,
                                    seen_source_only_signatures,
                                ),
                            ),
                        }
                    )
            elif document_ai_rows:
                for doc_row in document_ai_rows:
                    work_items.append(
                        {
                            "kind": "document_ai_only",
                            "priority": 99,
                            "sort_order": (
                                doc_row.year or 0,
                                doc_row.grade_level or 0,
                                doc_row.month or 0,
                                doc_row.row_index or 0,
                            ),
                            "doc_row": doc_row,
                            "gemini_row": None,
                            "match_confidence": None,
                            "force_review_reason": _combine_review_reasons(
                                emergency_reason,
                                _source_only_duplicate_review_reason(
                                    doc_row,
                                    seen_source_only_signatures,
                                ),
                            ),
                        }
                    )
            else:
                for gemini_row in gemini_rows:
                    work_items.append(
                        {
                            "kind": "gemini_only",
                            "priority": 99,
                            "sort_order": (
                                gemini_row.year or 0,
                                gemini_row.grade_level or 0,
                                gemini_row.month or 0,
                                gemini_row.row_index or 0,
                            ),
                            "doc_row": None,
                            "gemini_row": gemini_row,
                            "match_confidence": gemini_row.confidence,
                            "force_review_reason": _combine_review_reasons(
                                emergency_reason,
                                _source_only_duplicate_review_reason(
                                    gemini_row,
                                    seen_source_only_signatures,
                                ),
                            ),
                        }
                    )

        work_items.sort(key=lambda item: (item["priority"], item["sort_order"]))

        inserted_final_count = 0

        for item in work_items:
            kind = item["kind"]

            if kind == "matched":
                doc_row = item["doc_row"]
                gemini_row = item["gemini_row"]
                match_confidence = item["match_confidence"]
                final_values = item["final_values"]

                if _field_decisions_include_user_visible_gemini_fix(
                    final_values.get("field_decisions") or {}
                ):
                    auto_fixed_count += 1

                await self._insert_match_and_final(
                    extraction_file_id=extraction_file_id,
                    student_db_id=student_db_id,
                    doc_row=doc_row,
                    gemini_row=gemini_row,
                    match_type="matched",
                    match_confidence=match_confidence,
                    final_values=final_values,
                )

                matched_count += 1
                inserted_final_count += 1
                continue

            if kind == "gemini_only":
                gemini_row = item["gemini_row"]

                final_values = _build_final_from_single_source(
                    gemini_row,
                    source="gemini",
                    force_review_reason=item.get("force_review_reason"),
                )

                if not final_values.get("needs_review"):
                    auto_fixed_count += 1

                await self._insert_match_and_final(
                    extraction_file_id=extraction_file_id,
                    student_db_id=student_db_id,
                    doc_row=None,
                    gemini_row=gemini_row,
                    match_type="gemini_only",
                    match_confidence=gemini_row.confidence,
                    final_values=final_values,
                )

                gemini_only_count += 1
                inserted_final_count += 1
                continue

            if kind == "document_ai_only":
                doc_row = item["doc_row"]

                final_values = _build_final_from_single_source(
                    doc_row,
                    source="document_ai",
                    force_review_reason=item.get("force_review_reason"),
                )

                await self._insert_match_and_final(
                    extraction_file_id=extraction_file_id,
                    student_db_id=student_db_id,
                    doc_row=doc_row,
                    gemini_row=None,
                    match_type="document_ai_only",
                    match_confidence=None,
                    final_values=final_values,
                )

                doc_only_count += 1
                inserted_final_count += 1
                continue

        final_course_count = await self._count_final_rows(extraction_file_id)
        needs_review_count = await self._count_final_needs_review(extraction_file_id)

        review_reasons: list[str] = []
        warnings: list[str] = []

        if final_course_count == 0:
            review_reasons.append("No final course rows were created.")

        if needs_review_count > 0:
            review_reasons.append(
                f"{needs_review_count} final course row(s) need manual review."
            )

        if low_match_coverage:
            warnings.append(
                "Document AI and Gemini matched poorly. Reconciliation kept only safe matches, then preserved source-only rows that were complete/believable or sent unsafe rows to review."
            )

        if gemini_unavailable:
            review_reasons.append(
                "Gemini returned zero saved rows while Document AI had courses. "
                "The second extractor must participate before this file can be marked Completed."
            )
            warnings.append(
                "Gemini raw extraction returned zero rows while Document AI had courses. "
                "No Gemini fill/proof was available for missing course IDs or bad course names. "
                "Check gemini_course_extractor response parsing/logs for the raw failure reason."
            )

        if document_ai_unavailable:
            review_reasons.append(
                "Document AI returned zero saved rows while Gemini had courses. "
                "Both extractors must participate before this file can be marked Completed."
            )
            warnings.append(
                "Document AI raw extraction returned zero rows while Gemini had courses."
            )

        if document_ai_count != gemini_count:
            warnings.append(
                f"Raw extractor row counts differ: Document AI={document_ai_count}, Gemini={gemini_count}."
            )

        if skipped_gemini_only_count > 0:
            warnings.append(
                f"{skipped_gemini_only_count} Gemini-only row(s) were suppressed because they were duplicate/conflict rows "
                "or because Document AI controlled the final course count for this file."
            )

        if skipped_document_ai_only_count > 0:
            warnings.append(
                f"{skipped_document_ai_only_count} Document-AI-only row(s) were suppressed because Gemini controlled "
                "the final course count for this file."
            )

        expected_final_count = _calculate_expected_final_count(
            matched_count=matched_count,
            inserted_document_ai_only_count=doc_only_count,
            inserted_gemini_only_count=gemini_only_count,
        )
        target_final_count = expected_final_count

        if final_course_count < expected_final_count:
            review_reasons.append(
                f"Final rows are short by {expected_final_count - final_course_count} row(s)."
            )

        if final_course_count > expected_final_count:
            review_reasons.append(
                f"Final rows exceed expected inserted row count by {final_course_count - expected_final_count} row(s)."
            )

        if both_sources_present and final_course_count > max_source_count:
            review_reasons.append(
                "Final course count exceeds both raw extractor counts "
                f"(final={final_course_count}, Document AI={document_ai_count}, Gemini={gemini_count}). "
                "This usually means unmatched rows from both extractors were double-counted."
            )

        final_status = (
            "completed"
            if final_course_count > 0
            and needs_review_count == 0
            and final_course_count == expected_final_count
            and (not both_sources_present or final_course_count <= max_source_count)
            and not gemini_unavailable
            and not document_ai_unavailable
            else "needs_review"
        )

        await self._update_file_status(
            extraction_file_id=extraction_file_id,
            final_status=final_status,
        )

        await self.session.commit()

        result = {
            "status": final_status,
            "file_status": final_status,
            "process_status": final_status,
            "validation_type": "course_reconciliation",
            "extraction_file_id": extraction_file_id,
            "student_db_id": student_db_id,

            "document_ai_course_count": document_ai_count,
            "raw_document_ai_course_count": document_ai_count,
            "course_details_count": document_ai_count,

            "gemini_course_count": gemini_count,
            "raw_gemini_course_count": gemini_count,
            "gemini_course_details_count": gemini_count,

            "primary_source": primary_source,
            "course_count_owner_source": count_owner_source,
            "max_source_course_count": max_source_count,
            "target_final_count": target_final_count,

            "initial_matched_count": initial_matched_count,
            "match_coverage": round(match_coverage, 3),
            "low_match_coverage": low_match_coverage,

            "matched_count": matched_count,
            "matched_course_count": matched_count,
            "document_ai_only_count": doc_only_count,
            "gemini_only_count": gemini_only_count,

            "skipped_document_ai_only_count": skipped_document_ai_only_count,
            "skipped_gemini_only_count": skipped_gemini_only_count,

            "suppressed_document_ai_duplicate_count": skipped_document_ai_only_count,
            "suppressed_gemini_duplicate_count": skipped_gemini_only_count,

            "final_course_count": final_course_count,
            "actual_final_course_count": final_course_count,
            "final_course_details_count": final_course_count,
            "expected_final_course_count": expected_final_count,

            "needs_review_count": needs_review_count,
            "open_review_count": needs_review_count,

            "auto_fixed_count": auto_fixed_count,
            "review_reason": "; ".join(review_reasons) or None,
            "review_reasons": review_reasons,
            "warnings": warnings,
            "counts_match": document_ai_count == gemini_count,
            "extractor_participation_valid": not gemini_unavailable and not document_ai_unavailable,
            "geometry_diagnostics": geometry_diagnostics,
            "course_count_rule": "matched_rows_plus_count_owner_source_only_rows",
            "course_count_rule_detail": (
                "When both extractors have rows, final count follows the extractor with the larger raw course count. "
                "Final rows are matched rows plus source-only rows from that count-owner extractor only. "
                "This prevents double-counting the same real transcript rows as both Document-AI-only and Gemini-only when matching coverage is low. "
                "If one extractor has zero rows, final rows may be created for visibility, but the file stays Needs Review because both extractors must participate."
            ),
            "gemini_zero_diagnostics": (
                {
                    "message": (
                        "Gemini returned zero saved rows. Reconciliation could not use Gemini to fill missing course IDs, "
                        "course names, grades, or credits. Inspect gemini_course_extractor logs/raw response parsing."
                    ),
                    "doc_ai_rows": document_ai_count,
                    "gemini_rows": gemini_count,
                }
                if gemini_unavailable
                else None
            ),
        }

        print(
            "[COURSE RECONCILIATION SAVED] "
            f"file_id={extraction_file_id}, "
            f"status={final_status}, "
            f"primary_source={primary_source}, "
            f"doc_ai={document_ai_count}, "
            f"gemini={gemini_count}, "
            f"target_final={target_final_count}, "
            f"geometry_rows={geometry_diagnostics.get('geometry_rows')}, "
            f"geometry_attached={geometry_diagnostics.get('attached')}, "
            f"initial_matched={initial_matched_count}, "
            f"match_coverage={round(match_coverage, 3)}, "
            f"low_match_coverage={low_match_coverage}, "
            f"matched={matched_count}, "
            f"doc_only_inserted={doc_only_count}, "
            f"gemini_only_inserted={gemini_only_count}, "
            f"skipped_doc_only={skipped_document_ai_only_count}, "
            f"skipped_gemini_only={skipped_gemini_only_count}, "
            f"final={final_course_count}, "
            f"expected_final={expected_final_count}, "
            f"needs_review={needs_review_count}, "
            f"auto_fixed={auto_fixed_count}"
        )

        return result

    async def reconcile(
        self,
        *,
        extraction_file_id: int,
        student_db_id: int,
        document_ai_course_count: int | None = None,
        gemini_course_count: int | None = None,
        pdf_path: str | None = None,
        pdf_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        return await self.reconcile_file(
            extraction_file_id=extraction_file_id,
            student_db_id=student_db_id,
            document_ai_course_count=document_ai_course_count,
            gemini_course_count=gemini_course_count,
            pdf_path=pdf_path,
            pdf_bytes=pdf_bytes,
        )
