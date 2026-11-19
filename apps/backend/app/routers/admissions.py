from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import AsyncSessionLocal, get_session
from app.routers.auth import get_current_user
from app.services.admission_calculation_service import (
    AdmissionCalculationConfig,
    ManualAgMapping,
    build_admission_review_payload,
)


router = APIRouter(prefix="/admission", tags=["admission-calculation"])


AgTarget = Literal["a", "b", "c", "d", "d1", "d2", "e", "f", "g", "removed"]


class ManualAgMappingRequest(BaseModel):
    course_id: str

    # Backend preferred field
    target_ag: Optional[AgTarget] = None

    # Frontend may send this name
    target_ag_type: Optional[AgTarget] = None


class AdmissionCalculationConfigRequest(BaseModel):
    ag_required: Optional[Dict[str, int]] = None

    # Needed for editable GPA table points
    grade_points: Optional[Dict[str, float]] = None

    # Backend preferred field
    honors_bonus_points: Optional[float] = None

    # Frontend may send this shorter name
    honors_bonus: Optional[float] = None

    honors_max_semesters: Optional[int] = None
    honors_max_10th_grade_semesters: Optional[int] = None
    csulb_score_multiplier: Optional[int] = None
    california_resident_min_gpa: Optional[float] = None
    non_resident_min_gpa: Optional[float] = None
    csulb_threshold: Optional[int] = None
    non_resident_csulb_threshold: Optional[int] = None
    stem_threshold: Optional[int] = None
    ag_hs_grades: Optional[List[int]] = None
    gpa_hs_grades: Optional[List[int]] = None
    gpa_cumulative_hs_grades: Optional[List[int]] = None


class AdmissionCalculationRequest(BaseModel):
    student: Dict[str, Any]
    config: Optional[AdmissionCalculationConfigRequest] = None
    manual_mappings: List[ManualAgMappingRequest] = Field(default_factory=list)
    # Term whose institution criteria seed the base thresholds (overridable below).
    year_intake: Optional[str] = None


class AdmissionSaveRequest(AdmissionCalculationRequest):
    year_intake: Optional[str] = None


def build_config(
    config_payload: Optional[AdmissionCalculationConfigRequest],
    base: Optional[AdmissionCalculationConfig] = None,
) -> AdmissionCalculationConfig:
    # `base` (typically derived from the institution criteria) supplies the
    # starting thresholds; the payload then applies per-student overrides on top.
    config = base if base is not None else AdmissionCalculationConfig()

    if not config_payload:
        return config

    if config_payload.ag_required is not None:
        config.ag_required.update(config_payload.ag_required)

    if config_payload.grade_points is not None:
        config.grade_points.update(config_payload.grade_points)

    if config_payload.honors_bonus_points is not None:
        config.honors_bonus_points = config_payload.honors_bonus_points

    if config_payload.honors_bonus is not None:
        config.honors_bonus_points = config_payload.honors_bonus

    if config_payload.honors_max_semesters is not None:
        config.honors_max_semesters = config_payload.honors_max_semesters

    if config_payload.honors_max_10th_grade_semesters is not None:
        config.honors_max_10th_grade_semesters = config_payload.honors_max_10th_grade_semesters

    if config_payload.csulb_score_multiplier is not None:
        config.csulb_score_multiplier = config_payload.csulb_score_multiplier

    if config_payload.california_resident_min_gpa is not None:
        config.california_resident_min_gpa = config_payload.california_resident_min_gpa

    if config_payload.non_resident_min_gpa is not None:
        config.non_resident_min_gpa = config_payload.non_resident_min_gpa

    if config_payload.csulb_threshold is not None:
        config.csulb_threshold = config_payload.csulb_threshold

    if config_payload.non_resident_csulb_threshold is not None:
        config.non_resident_csulb_threshold = config_payload.non_resident_csulb_threshold

    if config_payload.stem_threshold is not None:
        # The frontend's STEM threshold is a STEM Index (GPA × 800), which is
        # what the Final Audit gate compares against. Drive stem_index_threshold
        # (legacy stem_threshold kept in sync for any callers reading it).
        config.stem_index_threshold = config_payload.stem_threshold
        config.stem_threshold = config_payload.stem_threshold

    if config_payload.ag_hs_grades is not None:
        config.ag_hs_grades = config_payload.ag_hs_grades

    if config_payload.gpa_hs_grades is not None:
        config.gpa_hs_grades = config_payload.gpa_hs_grades

    if config_payload.gpa_cumulative_hs_grades is not None:
        config.gpa_cumulative_hs_grades = config_payload.gpa_cumulative_hs_grades

    return config


def build_manual_mappings(items: List[ManualAgMappingRequest]) -> List[ManualAgMapping]:
    manual_mappings: List[ManualAgMapping] = []

    for item in items:
        target = item.target_ag or item.target_ag_type

        if not target:
            continue

        manual_mappings.append(
            ManualAgMapping(
                course_id=item.course_id,
                target_ag=target.lower(),
            )
        )

    return manual_mappings


def get_student_pk_from_payload(student: Dict[str, Any]) -> int:
    """
    student_ag_summary.student_id points to student_details.id.

    Frontend should ideally send the DB id in student.id or student.db_id.
    """
    possible_keys = [
        "db_id",
        "student_db_id",
        "student_detail_id",
        "studentDetailsId",
        "id",
    ]

    for key in possible_keys:
        raw_value = student.get(key)

        if raw_value is None or raw_value == "":
            continue

        try:
            return int(raw_value)
        except (TypeError, ValueError):
            continue

    raise HTTPException(
        status_code=400,
        detail=(
            "Missing student DB id. Expected student.id, student.db_id, "
            "or student_detail_id to match student_details.id."
        ),
    )


def manual_mappings_to_course_overrides(
    manual_mappings: List[ManualAgMapping],
) -> Dict[str, Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()

    overrides: Dict[str, Dict[str, Any]] = {}

    for mapping in manual_mappings:
        target = str(mapping.target_ag).lower()
        removed = target == "removed"

        overrides[mapping.course_id] = {
            "courseKey": mapping.course_id,
            "agKey": "" if removed else target,
            "target_ag": target,
            "removed": removed,
            "updated_at": now,
        }

    return overrides


def course_overrides_to_manual_mappings(
    course_overrides: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    if not course_overrides:
        return []

    mappings: List[Dict[str, str]] = []

    for course_key, value in course_overrides.items():
        if not isinstance(value, dict):
            continue

        removed = bool(value.get("removed"))
        target = (
            value.get("target_ag")
            or value.get("agKey")
            or value.get("to_ag")
            or value.get("targetAg")
        )

        if removed:
            target = "removed"

        if not target:
            continue

        mappings.append(
            {
                "course_id": str(value.get("courseKey") or course_key),
                "target_ag": str(target).lower(),
            }
        )

    return mappings


def get_ag_row_value(review: Dict[str, Any], key: str, field_name: str, default: float = 0.0) -> float:
    rows = review.get("ag_review", {}).get("rows", [])

    for row in rows:
        if row.get("key") == key:
            try:
                return float(row.get(field_name, default) or default)
            except (TypeError, ValueError):
                return default

    return default


def save_review_to_summary(
    summary: models.StudentAgSummary,
    review: Dict[str, Any],
    course_overrides: Dict[str, Dict[str, Any]],
    year_intake: Optional[str] = None,
) -> None:
    score_summary = review.get("gpa_calculation", {}).get("score_summary", {})
    admission_decision = review.get("admission_decision", {})

    summary.a_calc = get_ag_row_value(review, "a", "actual")
    summary.b_calc = get_ag_row_value(review, "b", "actual")
    summary.c_calc = get_ag_row_value(review, "c", "actual")
    summary.d1_calc = get_ag_row_value(review, "d1", "actual")
    summary.d2_calc = get_ag_row_value(review, "d2", "actual")
    summary.d_calc = get_ag_row_value(review, "d", "actual")
    summary.e_calc = get_ag_row_value(review, "e", "actual")
    summary.f_calc = get_ag_row_value(review, "f", "actual")
    summary.g_calc = get_ag_row_value(review, "g", "actual")

    summary.gpa_cumulative = score_summary.get("cumulative_gpa")
    summary.gpa_english = score_summary.get("english_gpa")
    summary.gpa_math = score_summary.get("math_gpa")
    summary.gpa_science = score_summary.get("science_gpa")
    summary.stem_score = score_summary.get("stem_score")
    summary.csulb_score = score_summary.get("csulb_score")

    summary.course_overrides = course_overrides
    summary.admission_decision = admission_decision.get("recommended_decision")

    if year_intake:
        summary.year_intake = year_intake


async def _load_institution_codes(db: AsyncSession, inst_id) -> List[Dict[str, Any]]:
    if not inst_id:
        return []
    try:
        rows = (await db.execute(
            select(models.TranscriptCourseCode).where(
                models.TranscriptCourseCode.institution_id == inst_id
            )
        )).scalars().all()
        return [
            {"code": r.code, "position": r.position, "meaning": r.meaning,
             "school_name": r.school_name, "affects_ag": r.affects_ag,
             "strip_for_matching": r.strip_for_matching}
            for r in rows
        ]
    except Exception:
        return []


async def _load_term_criteria(db: AsyncSession, inst_id, term: Optional[str]):
    """Institution A-G criteria for a term, or None — used to seed the base
    admission config so the review uses the same thresholds as batch-calculate."""
    if not inst_id or not term:
        return None
    return (await db.execute(
        select(models.InstitutionAgCriteria).where(
            models.InstitutionAgCriteria.institution_id == inst_id,
            models.InstitutionAgCriteria.year_intake == term,
        )
    )).scalars().first()


@router.post("/calculate")
async def calculate_admission_review(
    payload: AdmissionCalculationRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    criteria = await _load_term_criteria(db, inst_id, payload.year_intake)
    config = build_config(payload.config, base=_config_from_criteria(criteria))
    manual_mappings = build_manual_mappings(payload.manual_mappings)
    institution_codes = await _load_institution_codes(db, inst_id)
    course_overrides = await _load_course_overrides(db, inst_id)

    return build_admission_review_payload(
        student=payload.student,
        config=config,
        manual_mappings=manual_mappings,
        institution_codes=institution_codes,
        institution_course_overrides=course_overrides,
    )


def _config_from_criteria(criteria) -> AdmissionCalculationConfig:
    """Build the calculation config from the institution's saved A-G criteria."""
    config = AdmissionCalculationConfig()
    if not criteria:
        return config
    for ag in ("a", "b", "c", "d", "e", "f", "g"):
        val = getattr(criteria, f"{ag}_required", None)
        if val is not None and ag in config.ag_required:
            config.ag_required[ag] = val
    if getattr(criteria, "california_resident_min_gpa", None):
        config.california_resident_min_gpa = criteria.california_resident_min_gpa
    # Non-resident minimums (higher CSU bar); None keeps the engine defaults.
    if getattr(criteria, "non_resident_min_gpa", None):
        config.non_resident_min_gpa = criteria.non_resident_min_gpa
    if getattr(criteria, "non_resident_csulb_score", None):
        config.non_resident_csulb_threshold = int(criteria.non_resident_csulb_score)
    # CSULB Index minimum (cumulative GPA x 800) from the institution criteria.
    if getattr(criteria, "min_csulb_score", None):
        config.csulb_threshold = int(criteria.min_csulb_score)
    # STEM Index minimum (STEM GPA x 800) from the institution criteria. This is the
    # configurable "STEM score" requirement; enforcement still requires a STEM-major
    # signal per student (deferred), so it is reported but does not auto-rescind yet.
    if getattr(criteria, "min_stem_score", None):
        config.stem_index_threshold = int(criteria.min_stem_score)
    # HS grade levels to consider for A-G counting and GPA (subject vs cumulative).
    if getattr(criteria, "ag_hs_grades", None):
        config.ag_hs_grades = list(criteria.ag_hs_grades)
    if getattr(criteria, "gpa_hs_grades", None):
        config.gpa_hs_grades = list(criteria.gpa_hs_grades)
    if getattr(criteria, "gpa_cumulative_hs_grades", None):
        config.gpa_cumulative_hs_grades = list(criteria.gpa_cumulative_hs_grades)
    # Strict handbook rule toggles (absent/None => off, i.e. current behavior).
    rule_config = getattr(criteria, "rule_config", None) or {}
    if isinstance(rule_config, dict):
        for flag in ("strict_c_math_slots", "strict_a_history_anchor", "strict_f_same_discipline"):
            if flag in rule_config:
                setattr(config, flag, bool(rule_config[flag]))
    return config


async def _load_course_overrides(db: AsyncSession, inst_id) -> list[dict]:
    """Institution course->A-G reassignments, as plain dicts for the calc service."""
    if not inst_id:
        return []
    rows = (await db.execute(
        select(models.InstitutionCourseAgOverride).where(
            models.InstitutionCourseAgOverride.institution_id == inst_id,
            models.InstitutionCourseAgOverride.enabled.is_(True),
        )
    )).scalars().all()
    return [
        {"course_name": r.course_name, "discipline": r.discipline, "target_ag": r.target_ag}
        for r in rows
    ]


def _course_dict_for_admission(fcd, uc) -> Dict[str, Any]:
    """Shape a final_course_details row (+ its UC mapping) into the dict the
    admission calculation service expects. A-G comes from the UC doorway map."""
    mapped = None
    if uc is not None:
        mapped = {
            "id": getattr(uc, "id", None),
            "crs_ag_category_letter": getattr(uc, "crs_ag_category_letter", None),
            "crs_ag_category_description": getattr(uc, "crs_ag_category_description", None),
            "crs_discipline": getattr(uc, "crs_discipline", None),
            "crs_honors": getattr(uc, "crs_honors", None),
            "standardizedCode": getattr(uc, "crs_ag_category_letter", None),
            "standardizedDescription": getattr(uc, "crs_ag_category_description", None),
        }
    return {
        "crs_id": fcd.crs_id,
        "crs_description": fcd.crs_description,
        "crs_letter_grade": fcd.crs_letter_grade,
        "crs_grade": fcd.crs_grade,
        "crs_year": fcd.crs_year,
        "crs_month": fcd.crs_month,
        "crs_credit_attempted": fcd.crs_credit_attempted,
        "crs_credit_completed": fcd.crs_credit_completed,
        "crs_hs": fcd.crs_hs,
        "mapped_uc_course": mapped,
    }


# Column order for the lean batch-calculate query (scalar columns only — no heavy
# JSONB like field_decisions/snapshots/geometry, which dominated decode time).
_BATCH_COURSE_COLS = lambda FCD, UC: (  # noqa: E731
    FCD.id, FCD.s_id, FCD.crs_id, FCD.crs_description, FCD.crs_letter_grade,
    FCD.crs_grade, FCD.crs_year, FCD.crs_month, FCD.crs_credit_attempted,
    FCD.crs_credit_completed, FCD.crs_hs,
    UC.id, UC.crs_ag_category_letter, UC.crs_ag_category_description,
    UC.crs_discipline, UC.crs_honors,
)


def _course_dict_from_row(row) -> Dict[str, Any]:
    """Same shape as _course_dict_for_admission, but from a lean column tuple."""
    (_fid, _sid, crs_id, crs_description, crs_letter_grade, crs_grade, crs_year,
     crs_month, crs_credit_attempted, crs_credit_completed, crs_hs,
     uc_id, uc_letter, uc_desc, uc_discipline, uc_honors) = row
    mapped = None
    if uc_id is not None:
        mapped = {
            "id": uc_id,
            "crs_ag_category_letter": uc_letter,
            "crs_ag_category_description": uc_desc,
            "crs_discipline": uc_discipline,
            "crs_honors": uc_honors,
            "standardizedCode": uc_letter,
            "standardizedDescription": uc_desc,
        }
    return {
        "crs_id": crs_id,
        "crs_description": crs_description,
        "crs_letter_grade": crs_letter_grade,
        "crs_grade": crs_grade,
        "crs_year": crs_year,
        "crs_month": crs_month,
        "crs_credit_attempted": crs_credit_attempted,
        "crs_credit_completed": crs_credit_completed,
        "crs_hs": crs_hs,
        "mapped_uc_course": mapped,
    }


@router.post("/batch-calculate")
async def batch_calculate(
    term: str = Query(...),
    force: bool = Query(False),
    background: bool = Query(False),
    background_tasks: BackgroundTasks = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Compute and auto-save an admission recommendation for every completed,
    unreviewed student in a term — so students appear on the Admitted/Denied
    pages right after extraction, and stay in Pending Review (reviewed=False)
    until a counselor confirms them.

    With background=true, the recalc is scheduled server-side and the request
    returns immediately — so the Save Criteria button doesn't hang on the
    (CPU-bound, per-student) recompute. Decisions update as it finishes.

    A-G counts come from final_course_details joined to the UC Doorway mapping;
    GPA comes from the final-course grades.
    """
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        return {"processed": 0}

    if background and background_tasks is not None:
        background_tasks.add_task(_batch_calculate_in_background, inst_id, term, force)
        return {"processed": 0, "scheduled": True}

    return {"processed": await _run_batch_calculate(db, inst_id, term, force)}


async def _batch_calculate_in_background(inst_id: int, term: str, force: bool) -> None:
    # Runs after the response is sent, so it needs its own session.
    async with AsyncSessionLocal() as db:
        await _run_batch_calculate(db, inst_id, term, force)


async def _run_batch_calculate(db: AsyncSession, inst_id: int, term: str, force: bool) -> int:
    # Institution A-G criteria for this term -> config (the "conditions").
    criteria = (await db.execute(
        select(models.InstitutionAgCriteria).where(
            models.InstitutionAgCriteria.institution_id == inst_id,
            models.InstitutionAgCriteria.year_intake == term,
        )
    )).scalars().first()
    config = _config_from_criteria(criteria)

    # Institution transcript codes (e.g. '*' = non-academic, '+' = honors) so the
    # calculation applies the markers the user configured on the Codes page.
    institution_codes = await _load_institution_codes(db, inst_id)
    course_overrides = await _load_course_overrides(db, inst_id)

    # Approved term ruleset (if any) drives the grounded Gemini audit layer. When
    # present, each student gets a cached LLM verdict keyed on the ruleset version;
    # Gemini only runs on a cache miss (new student or a newer approved ruleset).
    # Rules are served from the in-memory (RAG-style) cache.
    from app.routers.term_rules import get_active_rules
    ruleset, active_rules = await get_active_rules(db, inst_id, term)

    # Completed students in this term. Select only the scalar columns the calc
    # needs — loading full Students/ExtractionFileDetails ORM objects pulled in
    # huge JSONB blobs and made this query take ~20s for 100 students.
    S = models.Students
    students = (await db.execute(
        select(S.id, S.s_id, S.s_name, S.hs_name, S.s_address, S.hs_graduation_date)
        .join(models.ExtractionFileDetails, S.source_file == models.ExtractionFileDetails.id)
        .where(
            models.ExtractionFileDetails.institution_id == inst_id,
            models.ExtractionFileDetails.year_intake == term,
            models.ExtractionFileDetails.process_status == "completed",
        )
    )).all()
    if not students:
        return 0

    student_ids = [s.id for s in students]

    # Existing summaries first, so the cheap auto-route path (no force) can decide
    # who still needs computing BEFORE loading any course data.
    existing = (await db.execute(
        select(models.StudentAgSummary).where(models.StudentAgSummary.student_id.in_(student_ids))
    )).scalars().all()
    summary_by_student = {r.student_id: r for r in existing}

    # Students whose audit already landed for the ACTIVE ruleset version. Anyone
    # missing (e.g. their Gemini call failed and was deliberately not cached)
    # gets picked up by EVERY recalc — including the passive page-mount ones —
    # until a real audit exists.
    verdict_have: set[int] = set()
    if ruleset is not None and student_ids:
        verdict_have = set((await db.execute(
            select(models.StudentLlmVerdict.student_id).where(
                models.StudentLlmVerdict.student_id.in_(student_ids),
                models.StudentLlmVerdict.ruleset_version == ruleset.version,
            )
        )).scalars().all())

    def _needs_compute(s) -> bool:
        if not s.s_name:
            return False
        summary = summary_by_student.get(s.id)
        if summary is None:
            return True
        if force:
            return True
        if getattr(summary, "reviewed", False):
            return False  # human-confirmed — passive runs never touch it
        if ruleset is not None and s.id not in verdict_have:
            return True  # audit missing/failed — retry until Gemini answers once
        # Already auto-routed with a current audit — fast no-op.
        return not summary.admission_decision

    todo = [s for s in students if _needs_compute(s)]
    if not todo:
        return 0
    todo_ids = [s.id for s in todo]

    # Batch-load courses + UC mappings for ONLY the students that need computing,
    # selecting just the scalar columns the calc reads (no heavy JSONB decode).
    FCD = models.FinalCourseDetails
    UC = models.UCDoorwayCourses
    rows = (await db.execute(
        select(*_BATCH_COURSE_COLS(FCD, UC))
        .outerjoin(
            models.CourseDetailMappingUcDoorwayCourses,
            or_(
                models.CourseDetailMappingUcDoorwayCourses.final_course_details_id == FCD.id,
                models.CourseDetailMappingUcDoorwayCourses.course_details_id == FCD.document_ai_course_detail_id,
            ),
        )
        .outerjoin(
            UC,
            models.CourseDetailMappingUcDoorwayCourses.uc_doorway_courses_id == UC.id,
        )
        .where(FCD.s_id.in_(todo_ids))
        .order_by(FCD.s_id, FCD.id)
    )).all()

    courses_by_student: Dict[int, List[Dict[str, Any]]] = {}
    seen_final_ids: Dict[int, set] = {}
    for row in rows:
        fid, sid = row[0], row[1]
        seen = seen_final_ids.setdefault(sid, set())
        if fid in seen:
            continue  # dedupe the OR-join double rows
        seen.add(fid)
        courses_by_student.setdefault(sid, []).append(_course_dict_from_row(row))

    # Cached Gemini verdicts for the active ruleset version (cache hits => no LLM).
    verdicts_by_student: dict[int, models.StudentLlmVerdict] = {}
    if ruleset is not None:
        vrows = (await db.execute(
            select(models.StudentLlmVerdict).where(
                models.StudentLlmVerdict.student_id.in_(todo_ids),
                models.StudentLlmVerdict.ruleset_version == ruleset.version,
            )
        )).scalars().all()
        verdicts_by_student = {v.student_id: v for v in vrows}

    processed = 0
    audit_jobs: list = []  # (student_id, review, courses, summary) needing a Gemini audit
    for s in todo:
        summary = summary_by_student.get(s.id)

        courses = courses_by_student.get(s.id, [])
        if not courses:
            continue

        student_dict = {
            "id": s.id,
            "db_id": s.id,
            "student_id": s.s_id,
            "name": s.s_name,
            "school_name": s.hs_name,
            "address": s.s_address,  # used to read CA vs non-resident residency
            "graduation_date": s.hs_graduation_date,
            "courses": courses,
        }

        try:
            review = build_admission_review_payload(
                student=student_dict, config=config, institution_codes=institution_codes,
                institution_course_overrides=course_overrides,
            )
        except Exception:
            continue

        if summary is None:
            summary = models.StudentAgSummary(student_id=s.id, reviewed=False)
            db.add(summary)
            summary_by_student[s.id] = summary

        save_review_to_summary(summary, review, summary.course_overrides or {}, year_intake=term)

        # Grounded Gemini audit layer (only when a term ruleset is approved).
        # Cached verdicts apply instantly; missing ones are queued and audited
        # CONCURRENTLY below (fanned out like any high-throughput pipeline),
        # instead of one blocking call per student.
        if ruleset is not None:
            verdict = verdicts_by_student.get(s.id)
            if verdict is None:
                audit_jobs.append((s.id, review, courses, summary))
            else:
                final_decision = verdict.override_decision if verdict.overridden else verdict.decision
                if final_decision:
                    summary.admission_decision = final_decision

        # Auto-routed but not yet confirmed by a human.
        if not getattr(summary, "reviewed", False):
            summary.reviewed = False
        processed += 1

    # Deterministic pass is done — persist it immediately so decisions update
    # fast, then fan out the missing audits.
    await db.commit()

    if ruleset is not None and audit_jobs:
        import asyncio as _aio
        import os as _os
        from concurrent.futures import ThreadPoolExecutor
        from app.services.llm_evaluation import evaluate_student

        conc = int(_os.environ.get("AUDIT_CONCURRENCY", "25"))
        sem = _aio.Semaphore(conc)
        # Dedicated pool: asyncio.to_thread uses the DEFAULT executor, which caps
        # at ~(cpu+4) threads — on a 4-CPU instance that silently throttled the
        # "80-way" fan-out to ~8 concurrent Gemini calls. I/O-bound work needs a
        # pool sized to the concurrency target, not the CPU count.
        pool = ThreadPoolExecutor(max_workers=conc)
        loop = _aio.get_running_loop()

        async def _audit(job):
            sid, review_, courses_, summary_ = job
            async with sem:
                # Worker thread: never block the event loop on a Gemini call.
                result = await loop.run_in_executor(
                    pool, evaluate_student, review_, courses_, active_rules or []
                )
            return sid, summary_, result

        for coro in _aio.as_completed([_audit(j) for j in audit_jobs]):
            try:
                sid, summary_, result = await coro
            except Exception:  # noqa: BLE001 — one failed audit never sinks the batch
                continue
            if result.get("failed"):
                # Gemini never answered (rate limit/transient): keep the baseline
                # for now but DON'T cache a verdict — the next recalc retries.
                continue
            verdict = models.StudentLlmVerdict(
                student_id=sid,
                institution_id=inst_id,
                ruleset_id=ruleset.id,
                ruleset_version=ruleset.version,
                decision=result["decision"],
                baseline_decision=result["baseline_decision"],
                reason=result["reason"],
                per_area=result["per_area"],
                learned_rules=result["learned_rules"],
            )
            db.add(verdict)
            verdicts_by_student[sid] = verdict
            if result["decision"]:
                summary_.admission_decision = result["decision"]
            # Durable per-verdict: a killed request loses at most one student.
            try:
                await db.commit()
            except Exception:  # noqa: BLE001 — e.g. concurrent run inserted same verdict
                await db.rollback()

        pool.shutdown(wait=False)

    await db.commit()
    return processed


@router.get("/course-overrides")
async def get_course_overrides(student_id: int = Query(...)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.StudentAgSummary).where(
                models.StudentAgSummary.student_id == student_id
            )
        )
        summary = result.scalar_one_or_none()

        if not summary:
            return {
                "student_id": student_id,
                "course_overrides": {},
                "manual_mappings": [],
            }

        course_overrides = summary.course_overrides or {}

        return {
            "student_id": student_id,
            "course_overrides": course_overrides,
            "manual_mappings": course_overrides_to_manual_mappings(course_overrides),
            "admission_decision": summary.admission_decision,
            "year_intake": summary.year_intake,
        }


@router.post("/course-overrides")
async def save_course_overrides(
    payload: AdmissionSaveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    student_pk = get_student_pk_from_payload(payload.student)

    criteria = await _load_term_criteria(
        db, getattr(current_user, "institution_id", None), payload.year_intake
    )
    config = build_config(payload.config, base=_config_from_criteria(criteria))
    manual_mappings = build_manual_mappings(payload.manual_mappings)
    inst_course_overrides = await _load_course_overrides(
        db, getattr(current_user, "institution_id", None)
    )

    review = build_admission_review_payload(
        student=payload.student,
        config=config,
        manual_mappings=manual_mappings,
        institution_course_overrides=inst_course_overrides,
    )

    course_overrides = manual_mappings_to_course_overrides(manual_mappings)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.StudentAgSummary).where(
                models.StudentAgSummary.student_id == student_pk
            )
        )
        summary = result.scalar_one_or_none()

        if not summary:
            summary = models.StudentAgSummary(student_id=student_pk)
            session.add(summary)

        save_review_to_summary(
            summary=summary,
            review=review,
            course_overrides=course_overrides,
            year_intake=payload.year_intake,
        )

        await session.commit()
        await session.refresh(summary)

    return {
        "status": "success",
        "student_id": student_pk,
        "course_overrides": course_overrides,
        "review": review,
        "message": "Course A/G edits saved and recalculated successfully.",
    }