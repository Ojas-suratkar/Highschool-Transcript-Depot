from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from sqlalchemy import cast, Integer
from app.models import (
    ClassifiersType,
    Course_details,
    ExtractionFileDetails,
    Students,
    TranscriptCourseCode,
    Profile,
)
from app.routers.auth import get_current_user

router = APIRouter(prefix="/transcript-course-codes", tags=["transcript-course-codes"])

VALID_POSITIONS = {"prefix", "suffix", "either"}
VALID_MEANINGS = {
    "honors",
    "non_academic",
    "repeated",
    "college_prep",
    "ap",
    "dual_enrollment",
    "other",
}


def _normalize_school(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    return v if v else None


def _dup_filter(inst_id: int, code: str, position: str, school_name: str | None, exclude_id: int | None = None):
    conditions = [
        TranscriptCourseCode.institution_id == inst_id,
        TranscriptCourseCode.code == code,
        TranscriptCourseCode.position == position,
    ]
    if school_name is None:
        conditions.append(TranscriptCourseCode.school_name.is_(None))
    else:
        conditions.append(TranscriptCourseCode.school_name == school_name)
    if exclude_id is not None:
        conditions.append(TranscriptCourseCode.id != exclude_id)
    return conditions


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TranscriptCodeIn(BaseModel):
    code: str
    position: str = "prefix"
    meaning: str = "other"
    label: str = ""
    school_name: Optional[str] = None
    affects_ag: bool = True
    strip_for_matching: bool = True

    @field_validator("code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("code cannot be empty")
        if len(v) > 20:
            raise ValueError("code must be 20 characters or fewer")
        return v

    @field_validator("position")
    @classmethod
    def position_valid(cls, v: str) -> str:
        if v not in VALID_POSITIONS:
            raise ValueError(f"position must be one of {sorted(VALID_POSITIONS)}")
        return v

    @field_validator("meaning")
    @classmethod
    def meaning_valid(cls, v: str) -> str:
        if v not in VALID_MEANINGS:
            raise ValueError(f"meaning must be one of {sorted(VALID_MEANINGS)}")
        return v

    @field_validator("school_name")
    @classmethod
    def normalize_school(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_school(v)


class TranscriptCodeOut(BaseModel):
    id: int
    institution_id: int
    code: str
    position: str
    meaning: str
    label: str
    school_name: Optional[str]
    affects_ag: bool
    strip_for_matching: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Transcript types discovery endpoint
# ---------------------------------------------------------------------------

@router.get("/transcript-types", response_model=list[str])
async def list_transcript_types(
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[str]:
    """
    Return distinct classifier_name values for all transcript types that have
    been processed for this institution. Used to populate type cards in the UI.
    """
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    try:
        result = await db.execute(
            select(distinct(ClassifiersType.classifier_name))
            .join(
                ExtractionFileDetails,
                cast(ExtractionFileDetails.classifier_type, Integer) == ClassifiersType.id,
            )
            .where(ExtractionFileDetails.institution_id == inst_id)
            .where(ClassifiersType.classifier_name.isnot(None))
            .where(ClassifiersType.classifier_name != "")
            .order_by(ClassifiersType.classifier_name)
        )
        return [row[0] for row in result.all()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TranscriptCodeOut])
async def list_codes(
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[TranscriptCourseCode]:
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")
    rows = (
        await db.execute(
            select(TranscriptCourseCode)
            .where(TranscriptCourseCode.institution_id == inst_id)
            .order_by(
                TranscriptCourseCode.school_name.nulls_first(),
                TranscriptCourseCode.meaning,
                TranscriptCourseCode.code,
            )
        )
    ).scalars().all()
    return list(rows)


@router.post("", response_model=TranscriptCodeOut, status_code=201)
async def create_code(
    payload: TranscriptCodeIn,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> TranscriptCourseCode:
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    school = _normalize_school(payload.school_name)

    existing = (
        await db.execute(
            select(TranscriptCourseCode).where(*_dup_filter(inst_id, payload.code, payload.position, school))
        )
    ).scalar_one_or_none()
    if existing:
        scope = f"'{school}'" if school else "institution-wide"
        raise HTTPException(
            status_code=409,
            detail=f"Code '{payload.code}' ({payload.position}) already exists for {scope}",
        )

    row = TranscriptCourseCode(
        institution_id=inst_id,
        code=payload.code,
        position=payload.position,
        meaning=payload.meaning,
        label=payload.label,
        school_name=school,
        affects_ag=payload.affects_ag,
        strip_for_matching=payload.strip_for_matching,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.put("/{code_id}", response_model=TranscriptCodeOut)
async def update_code(
    code_id: int,
    payload: TranscriptCodeIn,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> TranscriptCourseCode:
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    row = (
        await db.execute(
            select(TranscriptCourseCode).where(
                TranscriptCourseCode.id == code_id,
                TranscriptCourseCode.institution_id == inst_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Code not found")

    school = _normalize_school(payload.school_name)

    conflict = (
        await db.execute(
            select(TranscriptCourseCode).where(
                *_dup_filter(inst_id, payload.code, payload.position, school, exclude_id=code_id)
            )
        )
    ).scalar_one_or_none()
    if conflict:
        scope = f"'{school}'" if school else "institution-wide"
        raise HTTPException(
            status_code=409,
            detail=f"Code '{payload.code}' ({payload.position}) already exists for {scope}",
        )

    row.code = payload.code
    row.position = payload.position
    row.meaning = payload.meaning
    row.label = payload.label
    row.school_name = school
    row.affects_ag = payload.affects_ag
    row.strip_for_matching = payload.strip_for_matching
    row.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{code_id}")
async def delete_code(
    code_id: int,
    current_user: Profile = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    row = (
        await db.execute(
            select(TranscriptCourseCode).where(
                TranscriptCourseCode.id == code_id,
                TranscriptCourseCode.institution_id == inst_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Code not found")

    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
