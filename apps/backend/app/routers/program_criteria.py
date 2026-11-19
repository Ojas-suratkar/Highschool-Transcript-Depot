from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Profile, ProgramCriteria
from app.routers.auth import get_current_user

from ..db import get_session

router = APIRouter(prefix="/program-criteria", tags=["Program Criteria"])

PLACEHOLDER_PREREQ = "__placeholder__"


class PrereqIn(BaseModel):
    course_name: str
    min_gpa: str | None = None


class ProgramWithPrereqs(BaseModel):
    program_name: str
    year_intake: str
    prerequisites: List[PrereqIn] | None = None


class ProgramSummaryOut(BaseModel):
    id: int
    program_name: str
    year_intake: str
    prereq_count: int


async def _get_program_group_anchor(
    db: AsyncSession,
    institution_id: int,
    program_name: str,
    year_intake: str,
) -> ProgramCriteria | None:
    stmt = (
        select(ProgramCriteria)
        .where(
            ProgramCriteria.institution_id == institution_id,
            ProgramCriteria.program_name == program_name,
            ProgramCriteria.year_intake == year_intake,
        )
        .order_by(ProgramCriteria.id.asc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _get_scoped_program(
    db: AsyncSession,
    institution_id: int,
    program_id: int,
) -> ProgramCriteria:
    stmt = select(ProgramCriteria).where(
        ProgramCriteria.id == program_id,
        ProgramCriteria.institution_id == institution_id,
    )
    program = (await db.execute(stmt)).scalars().first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


def _normalize_program_payload(payload: ProgramWithPrereqs) -> tuple[str, str, list[PrereqIn]]:
    program_name = payload.program_name.strip()
    year_intake = payload.year_intake.strip()
    if not program_name or not year_intake:
        raise HTTPException(status_code=400, detail="program_name and year_intake required")

    normalized_prereqs: list[PrereqIn] = []
    for prereq in payload.prerequisites or []:
        course_name = prereq.course_name.strip()
        if not course_name:
            continue
        min_gpa = prereq.min_gpa.strip() if prereq.min_gpa else None
        normalized_prereqs.append(PrereqIn(course_name=course_name, min_gpa=min_gpa))

    return program_name, year_intake, normalized_prereqs


async def _replace_program_rows(
    db: AsyncSession,
    *,
    anchor: ProgramCriteria,
    old_program_name: str,
    old_year_intake: str,
    new_program_name: str,
    new_year_intake: str,
    prerequisites: list[PrereqIn],
    current_user_id,
) -> None:
    await db.execute(
        delete(ProgramCriteria).where(
            ProgramCriteria.institution_id == anchor.institution_id,
            ProgramCriteria.program_name == old_program_name,
            ProgramCriteria.year_intake == old_year_intake,
            ProgramCriteria.id != anchor.id,
        )
    )

    anchor.program_name = new_program_name
    anchor.year_intake = new_year_intake
    anchor.prerequisite_course_name = PLACEHOLDER_PREREQ
    anchor.prerequisite_course_gpa = "0"
    anchor.updated_by_user_id = current_user_id

    for prereq in prerequisites:
        db.add(
            ProgramCriteria(
                institution_id=anchor.institution_id,
                program_name=new_program_name,
                prerequisite_course_name=prereq.course_name,
                prerequisite_course_gpa=prereq.min_gpa or "0",
                year_intake=new_year_intake,
                updated_by_user_id=current_user_id,
            )
        )


@router.get("/program-names", response_model=list[str])
async def list_program_names(
    institution_id: int = Query(...),
    year_intake: str = Query(...),
    db: AsyncSession = Depends(get_session),
):
    stmt = (
        select(distinct(ProgramCriteria.program_name))
        .where(
            ProgramCriteria.institution_id == institution_id,
            ProgramCriteria.year_intake == year_intake,
        )
        .order_by(ProgramCriteria.program_name.asc())
    )
    names = (await db.execute(stmt)).scalars().all()
    return [name for name in names if name and name.strip()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_program(
    payload: ProgramWithPrereqs,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    program_name, year_intake, prerequisites = _normalize_program_payload(payload)

    existing = await _get_program_group_anchor(db, inst_id, program_name, year_intake)
    if existing:
        return {"ok": True, "created": False, "id": existing.id}

    anchor = ProgramCriteria(
        institution_id=inst_id,
        program_name=program_name,
        prerequisite_course_name=PLACEHOLDER_PREREQ,
        prerequisite_course_gpa="0",
        year_intake=year_intake,
        updated_by_user_id=current_user.id,
    )
    db.add(anchor)
    await db.flush()

    await _replace_program_rows(
        db,
        anchor=anchor,
        old_program_name=program_name,
        old_year_intake=year_intake,
        new_program_name=program_name,
        new_year_intake=year_intake,
        prerequisites=prerequisites,
        current_user_id=current_user.id,
    )

    await db.commit()
    await db.refresh(anchor)
    return {"ok": True, "created": True, "id": anchor.id}


@router.get("/{program_id}/prereqs", response_model=List[PrereqIn])
async def list_prereqs(
    program_id: int,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    base = await _get_scoped_program(db, inst_id, program_id)
    stmt = (
        select(ProgramCriteria)
        .where(
            ProgramCriteria.institution_id == base.institution_id,
            ProgramCriteria.program_name == base.program_name,
            ProgramCriteria.year_intake == base.year_intake,
        )
        .order_by(ProgramCriteria.id.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        PrereqIn(course_name=row.prerequisite_course_name, min_gpa=row.prerequisite_course_gpa)
        for row in rows
        if row.prerequisite_course_name and row.prerequisite_course_name != PLACEHOLDER_PREREQ
    ]


@router.put("/{program_id}")
async def update_program(
    program_id: int,
    payload: ProgramWithPrereqs,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    anchor = await _get_scoped_program(db, inst_id, program_id)
    old_program_name = anchor.program_name
    old_year_intake = anchor.year_intake
    new_program_name, new_year_intake, prerequisites = _normalize_program_payload(payload)

    if new_program_name != old_program_name or new_year_intake != old_year_intake:
        existing = await _get_program_group_anchor(db, inst_id, new_program_name, new_year_intake)
        if existing and existing.id != anchor.id:
            raise HTTPException(status_code=409, detail="Program already exists for this term")

    await _replace_program_rows(
        db,
        anchor=anchor,
        old_program_name=old_program_name,
        old_year_intake=old_year_intake,
        new_program_name=new_program_name,
        new_year_intake=new_year_intake,
        prerequisites=prerequisites,
        current_user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(anchor)
    return {"ok": True, "id": anchor.id}


@router.delete("/{program_id}")
async def delete_program(
    program_id: int,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    anchor = await _get_scoped_program(db, inst_id, program_id)
    await db.execute(
        delete(ProgramCriteria).where(
            ProgramCriteria.institution_id == inst_id,
            ProgramCriteria.program_name == anchor.program_name,
            ProgramCriteria.year_intake == anchor.year_intake,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("", response_model=List[ProgramSummaryOut])
async def list_programs(
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    stmt = (
        select(
            ProgramCriteria.program_name,
            ProgramCriteria.year_intake,
            func.min(ProgramCriteria.id).label("id"),
            func.count(ProgramCriteria.id)
            .filter(ProgramCriteria.prerequisite_course_name != PLACEHOLDER_PREREQ)
            .label("prereq_count"),
        )
        .where(ProgramCriteria.institution_id == inst_id)
        .group_by(ProgramCriteria.program_name, ProgramCriteria.year_intake)
        .order_by(ProgramCriteria.program_name.asc(), ProgramCriteria.year_intake.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        ProgramSummaryOut(
            id=int(row[2]),
            program_name=row[0],
            year_intake=row[1],
            prereq_count=int(row[3] or 0),
        )
        for row in rows
    ]
