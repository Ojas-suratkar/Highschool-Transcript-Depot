from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.student_details import get_student_full_details

router = APIRouter(
    prefix="/students",
    tags=["Student Details"],
)


@router.get("/{student_id}/full-details")
async def fetch_student_full_details(
    student_id: int,
    db: AsyncSession = Depends(get_session),
):
    result = await get_student_full_details(db=db, student_id=student_id)
    print("invokedd")

    if not result:
        raise HTTPException(status_code=404, detail="Student not found")

    return result