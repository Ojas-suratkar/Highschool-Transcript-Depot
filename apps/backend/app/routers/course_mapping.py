from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app import models
from app.routers.auth import get_current_user

router = APIRouter(prefix="/course-mapping", tags=["course-mapping"])

# A-G targets a course can be reassigned to (plus 'exclude' = drop from A-G).
VALID_TARGETS = {"a", "b", "c", "d1", "d2", "d", "e", "f", "g", "exclude"}


class CourseHit(BaseModel):
    course_name: str
    ag_letter: Optional[str] = None
    ag_description: Optional[str] = None
    discipline: Optional[str] = None
    occurrences: int


class OverrideIn(BaseModel):
    course_name: str
    discipline: Optional[str] = None
    original_ag: Optional[str] = None
    target_ag: str
    is_new: bool = False


class OverrideOut(BaseModel):
    id: int
    course_name: str
    discipline: Optional[str]
    original_ag: Optional[str]
    target_ag: str
    is_new: bool
    enabled: bool
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/search", response_model=list[CourseHit])
async def search_uc_courses(
    q: str = Query(..., min_length=2),
    limit: int = Query(30, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Fast trigram search over the distinct UC Doorways course catalog (already
    classified). One row per distinct (name, A-G, discipline) so the UI can show a
    card per course."""
    rows = (await db.execute(
        text(
            """
            SELECT course_name, ag_letter, ag_description, discipline, occurrences
            FROM uc_doorway_course_catalog
            WHERE lower(course_name) LIKE :pat
            ORDER BY occurrences DESC
            LIMIT :lim
            """
        ),
        {"pat": f"%{q.strip().lower()}%", "lim": limit},
    )).all()
    return [
        CourseHit(
            course_name=r[0], ag_letter=r[1], ag_description=r[2],
            discipline=r[3], occurrences=r[4],
        )
        for r in rows
    ]


@router.get("/overrides", response_model=list[OverrideOut])
async def list_overrides(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        return []
    rows = (await db.execute(
        select(models.InstitutionCourseAgOverride)
        .where(models.InstitutionCourseAgOverride.institution_id == inst_id)
        .order_by(models.InstitutionCourseAgOverride.updated_at.desc())
    )).scalars().all()
    return rows


@router.post("/overrides", response_model=OverrideOut)
async def upsert_override(
    payload: OverrideIn,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    target = (payload.target_ag or "").strip().lower()
    if target not in VALID_TARGETS:
        raise HTTPException(status_code=400, detail=f"Invalid target_ag '{payload.target_ag}'")

    name = (payload.course_name or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="course_name is required")
    disc = (payload.discipline or "").strip().lower() or None

    existing = (await db.execute(
        select(models.InstitutionCourseAgOverride).where(
            models.InstitutionCourseAgOverride.institution_id == inst_id,
            models.InstitutionCourseAgOverride.course_name == name,
            models.InstitutionCourseAgOverride.discipline.is_(None) if disc is None
            else models.InstitutionCourseAgOverride.discipline == disc,
        )
    )).scalars().first()

    if existing:
        existing.target_ag = target
        existing.original_ag = payload.original_ag
        existing.is_new = payload.is_new
        existing.enabled = True
        existing.updated_at = datetime.now(timezone.utc)
        row = existing
    else:
        row = models.InstitutionCourseAgOverride(
            institution_id=inst_id,
            course_name=name,
            discipline=disc,
            original_ag=payload.original_ag,
            target_ag=target,
            is_new=payload.is_new,
            enabled=True,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/overrides/{override_id}")
async def delete_override(
    override_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    row = (await db.execute(
        select(models.InstitutionCourseAgOverride).where(
            models.InstitutionCourseAgOverride.id == override_id,
            models.InstitutionCourseAgOverride.institution_id == inst_id,
        )
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True, "deleted": override_id}
