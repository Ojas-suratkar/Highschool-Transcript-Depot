from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import StudentAgSummary, Profile
from app.routers.auth import get_current_user

router = APIRouter(prefix="/student-ag-summary", tags=["student-ag-summary"])


class StudentAgSummaryOut(BaseModel):
    id: int
    student_id: int
    a_calc: float
    b_calc: float
    c_calc: float
    d1_calc: float
    d2_calc: float
    d_calc: float
    e_calc: float
    f_calc: float
    g_calc: float
    a_override: Optional[float]
    b_override: Optional[float]
    c_override: Optional[float]
    d1_override: Optional[float]
    d2_override: Optional[float]
    d_override: Optional[float]
    e_override: Optional[float]
    f_override: Optional[float]
    g_override: Optional[float]
    gpa_extracted: Optional[float]
    gpa_cumulative: Optional[float]
    gpa_english: Optional[float]
    gpa_math: Optional[float]
    gpa_science: Optional[float]
    stem_score: Optional[float]
    csulb_score: Optional[float]
    gpa_cumulative_override: Optional[float]
    gpa_english_override: Optional[float]
    gpa_math_override: Optional[float]
    gpa_science_override: Optional[float]
    stem_score_override: Optional[float]
    csulb_score_override: Optional[float]
    course_overrides: Optional[Dict[str, Any]]
    admission_decision: Optional[str]
    reviewed: Optional[bool] = None
    year_intake: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Lightweight payload sent from the frontend after Confirm Edit ─────────────

class AgUnitsPayload(BaseModel):
    a: Optional[float] = None
    b: Optional[float] = None
    c: Optional[float] = None
    d1: Optional[float] = None
    d2: Optional[float] = None
    d: Optional[float] = None
    e: Optional[float] = None
    f: Optional[float] = None
    g: Optional[float] = None


class AdmissionResultPayload(BaseModel):
    """
    Sent by the frontend when the counselor clicks Confirm Edit or changes the
    admission decision.  All fields are optional so the caller can send just
    what changed.
    """
    student_id: int
    year_intake: Optional[str] = None
    admission_decision: Optional[str] = None

    # Counselor confirmation flag. True once a human has reviewed the student
    # on the Admitted/Denied/Pending page (removes them from Pending Review).
    reviewed: Optional[bool] = None

    # A-G actuals (override columns – filled when counselor edits manually)
    ag_overrides: Optional[AgUnitsPayload] = None

    # GPA values (override columns – from the live calculation)
    gpa_cumulative: Optional[float] = None
    gpa_english: Optional[float] = None
    gpa_math: Optional[float] = None
    gpa_science: Optional[float] = None
    stem_score: Optional[float] = None
    csulb_score: Optional[float] = None
    gpa_extracted: Optional[float] = None

    # Manual course reassignments log
    course_overrides: Optional[Dict[str, Any]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_overrides(row: StudentAgSummary, payload: AdmissionResultPayload) -> None:
    # Only update AG overrides when explicitly provided (Confirm Edit path).
    # Admission-decision-only saves (handleDecisionChange) don't send ag_overrides
    # and must not wipe existing override values.
    if payload.ag_overrides is not None:
        ag = payload.ag_overrides
        row.a_override  = ag.a
        row.b_override  = ag.b
        row.c_override  = ag.c
        row.d1_override = ag.d1
        row.d2_override = ag.d2
        row.d_override  = ag.d
        row.e_override  = ag.e
        row.f_override  = ag.f
        row.g_override  = ag.g

    # Write to override columns so recompute (which only updates _calc) doesn't clobber edits
    if payload.gpa_cumulative is not None: row.gpa_cumulative_override = payload.gpa_cumulative
    if payload.gpa_english is not None:   row.gpa_english_override = payload.gpa_english
    if payload.gpa_math is not None:      row.gpa_math_override = payload.gpa_math
    if payload.gpa_science is not None:   row.gpa_science_override = payload.gpa_science
    if payload.stem_score is not None:    row.stem_score_override = payload.stem_score
    if payload.csulb_score is not None:   row.csulb_score_override = payload.csulb_score
    if payload.gpa_extracted is not None: row.gpa_extracted = payload.gpa_extracted

    if payload.admission_decision is not None:
        row.admission_decision = payload.admission_decision

    if payload.reviewed is not None:
        row.reviewed = payload.reviewed

    if payload.year_intake:
        row.year_intake = payload.year_intake

    if payload.course_overrides:
        existing = row.course_overrides or {}
        existing.update(payload.course_overrides)
        row.course_overrides = existing

    row.updated_at = datetime.now(timezone.utc)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{student_id}", response_model=StudentAgSummaryOut)
async def get_summary(
    student_id: int,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    stmt = select(StudentAgSummary).where(StudentAgSummary.student_id == student_id)
    row = (await db.execute(stmt)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="No summary found for this student")
    return row


@router.post("/save-admission-result", response_model=StudentAgSummaryOut)
async def save_admission_result(
    payload: AdmissionResultPayload,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Called by the frontend on Confirm Edit or when Admitted/Denied is toggled.
    Writes override columns and admission_decision; never overwrites calc columns.
    If no row exists yet, creates one (calc columns start at 0 until auto-compute runs).
    """
    stmt = select(StudentAgSummary).where(StudentAgSummary.student_id == payload.student_id)
    row = (await db.execute(stmt)).scalars().first()

    if row:
        _apply_overrides(row, payload)
    else:
        ag = payload.ag_overrides or AgUnitsPayload()
        row = StudentAgSummary(
            student_id=payload.student_id,
            a_override=ag.a,
            b_override=ag.b,
            c_override=ag.c,
            d1_override=ag.d1,
            d2_override=ag.d2,
            d_override=ag.d,
            e_override=ag.e,
            f_override=ag.f,
            g_override=ag.g,
            gpa_extracted=payload.gpa_extracted,
            gpa_cumulative_override=payload.gpa_cumulative,
            gpa_english_override=payload.gpa_english,
            gpa_math_override=payload.gpa_math,
            gpa_science_override=payload.gpa_science,
            stem_score_override=payload.stem_score,
            csulb_score_override=payload.csulb_score,
            course_overrides=payload.course_overrides,
            admission_decision=payload.admission_decision,
            reviewed=bool(payload.reviewed),
            year_intake=payload.year_intake,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return row


@router.post("/recompute/{student_id}", response_model=StudentAgSummaryOut)
async def recompute_summary(
    student_id: int,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Re-run the admission calculation for a student and refresh calc columns."""
    from app.services.student_ag_computation_service import compute_and_store_ag_summary
    row = await compute_and_store_ag_summary(db, student_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    await db.commit()
    await db.refresh(row)
    return row
