from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from sqlalchemy import select
from app.models import ProgramCriteria
from .auth import get_current_user
from app.models_program_version import ProgramVersion

router = APIRouter(prefix='/program-criteria', tags=['Program Criteria Versions'])


class CreateVersionRequest(BaseModel):
    notes: str | None = None


@router.post('/{program_id}/versions')
async def create_version(program_id: int, payload: CreateVersionRequest, current_user=Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    # ensure program exists and belongs to user's institution
    p = (
        await session.execute(
            select(ProgramCriteria).where(
                ProgramCriteria.id == program_id,
                ProgramCriteria.institution_id == current_user.institution_id,
            )
        )
    ).scalars().first()
    if not p:
        raise HTTPException(status_code=404, detail='Program not found')

    pv = ProgramVersion(program_criteria_id=program_id, created_by_user_id=current_user.id, notes=payload.notes)
    session.add(pv)
    await session.commit()
    await session.refresh(pv)
    return { 'ok': True, 'id': pv.id }
