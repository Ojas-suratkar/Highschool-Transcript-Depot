from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import InstitutionAgCriteria, AcademicTerm, Profile
from app.routers.auth import get_current_user

router = APIRouter(prefix="/institution-ag-criteria", tags=["institution-ag-criteria"])


class AgCriteriaOut(BaseModel):
    id: int
    institution_id: int
    year_intake: str
    a_required: int
    b_required: int
    c_required: int
    d1_required: int
    d2_required: int
    d_required: int
    e_required: int
    f_required: int
    g_required: int
    min_gpa_cumulative: Optional[float]
    min_gpa_english: Optional[float]
    min_gpa_math: Optional[float]
    min_gpa_science: Optional[float]
    min_csulb_score: Optional[float]
    min_stem_score: Optional[float]
    california_resident_min_gpa: Optional[float]
    non_resident_min_gpa: Optional[float]
    non_resident_csulb_score: Optional[float]
    ag_hs_grades: Optional[list[int]]
    gpa_hs_grades: Optional[list[int]]
    gpa_cumulative_hs_grades: Optional[list[int]]
    rule_config: Optional[dict] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class AgCriteriaIn(BaseModel):
    year_intake: str
    a_required: int = 4
    b_required: int = 8
    c_required: int = 6
    d1_required: int = 2
    d2_required: int = 2
    d_required: int = 4
    e_required: int = 4
    f_required: int = 2
    g_required: int = 2
    min_gpa_cumulative: Optional[float] = None
    min_gpa_english: Optional[float] = None
    min_gpa_math: Optional[float] = None
    min_gpa_science: Optional[float] = None
    min_csulb_score: Optional[float] = None
    min_stem_score: Optional[float] = None
    california_resident_min_gpa: Optional[float] = None
    non_resident_min_gpa: Optional[float] = None
    non_resident_csulb_score: Optional[float] = None
    ag_hs_grades: Optional[list[int]] = None
    gpa_hs_grades: Optional[list[int]] = None
    gpa_cumulative_hs_grades: Optional[list[int]] = None
    rule_config: Optional[dict] = None


@router.get("", response_model=list[AgCriteriaOut])
async def list_criteria(
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")
    stmt = (
        select(InstitutionAgCriteria)
        .where(InstitutionAgCriteria.institution_id == inst_id)
        .order_by(InstitutionAgCriteria.year_intake.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{year_intake}", response_model=AgCriteriaOut)
async def get_criteria(
    year_intake: str,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")
    stmt = select(InstitutionAgCriteria).where(
        InstitutionAgCriteria.institution_id == inst_id,
        InstitutionAgCriteria.year_intake == year_intake,
    )
    row = (await db.execute(stmt)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="No criteria found for this term")
    return row


@router.put("", response_model=AgCriteriaOut)
async def upsert_criteria(
    payload: AgCriteriaIn,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    # Resolve academic_term_id from term_name
    term_row = (await db.execute(
        select(AcademicTerm).where(
            AcademicTerm.institution_id == inst_id,
            AcademicTerm.term_name == payload.year_intake,
        )
    )).scalars().first()
    academic_term_id = term_row.id if term_row else None

    stmt = select(InstitutionAgCriteria).where(
        InstitutionAgCriteria.institution_id == inst_id,
        InstitutionAgCriteria.year_intake == payload.year_intake,
    )
    row = (await db.execute(stmt)).scalars().first()

    if row:
        row.a_required = payload.a_required
        row.b_required = payload.b_required
        row.c_required = payload.c_required
        row.d1_required = payload.d1_required
        row.d2_required = payload.d2_required
        row.d_required = payload.d_required
        row.e_required = payload.e_required
        row.f_required = payload.f_required
        row.g_required = payload.g_required
        row.min_gpa_cumulative = payload.min_gpa_cumulative
        row.min_gpa_english = payload.min_gpa_english
        row.min_gpa_math = payload.min_gpa_math
        row.min_gpa_science = payload.min_gpa_science
        row.min_csulb_score = payload.min_csulb_score
        row.min_stem_score = payload.min_stem_score
        row.california_resident_min_gpa = payload.california_resident_min_gpa
        row.non_resident_min_gpa = payload.non_resident_min_gpa
        row.non_resident_csulb_score = payload.non_resident_csulb_score
        row.ag_hs_grades = payload.ag_hs_grades
        row.gpa_hs_grades = payload.gpa_hs_grades
        row.gpa_cumulative_hs_grades = payload.gpa_cumulative_hs_grades
        row.rule_config = payload.rule_config
        if academic_term_id is not None:
            row.academic_term_id = academic_term_id
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = InstitutionAgCriteria(
            institution_id=inst_id,
            year_intake=payload.year_intake,
            academic_term_id=academic_term_id,
            a_required=payload.a_required,
            b_required=payload.b_required,
            c_required=payload.c_required,
            d1_required=payload.d1_required,
            d2_required=payload.d2_required,
            d_required=payload.d_required,
            e_required=payload.e_required,
            f_required=payload.f_required,
            g_required=payload.g_required,
            min_gpa_cumulative=payload.min_gpa_cumulative,
            min_gpa_english=payload.min_gpa_english,
            min_gpa_math=payload.min_gpa_math,
            min_gpa_science=payload.min_gpa_science,
            min_csulb_score=payload.min_csulb_score,
            min_stem_score=payload.min_stem_score,
            california_resident_min_gpa=payload.california_resident_min_gpa,
            non_resident_min_gpa=payload.non_resident_min_gpa,
            non_resident_csulb_score=payload.non_resident_csulb_score,
            ag_hs_grades=payload.ag_hs_grades,
            gpa_hs_grades=payload.gpa_hs_grades,
            gpa_cumulative_hs_grades=payload.gpa_cumulative_hs_grades,
            rule_config=payload.rule_config,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return row
