import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import PipelineJob
from app.services.uc_doorway_course_mapping_service import (
    schedule_uc_mapping_bg_task,
    get_uc_doorway_mapping_runtime_status,
)

router = APIRouter(
    prefix="/uc-doorway-course-mapping",
    tags=["uc-doorway-course-mapping"],
)


@router.post("/run")
async def run_uc_doorway_course_mapping_job(
    session: AsyncSession = Depends(get_session),
):
    new_job_uuid = uuid.uuid4()
    new_job_id = str(new_job_uuid)

    job = PipelineJob(
        id=new_job_uuid,
        job_type="uc_doorway_course_mapping",
        status="queued",
        error=None,
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    schedule_uc_mapping_bg_task(new_job_id)

    return {
        "status": "queued",
        "job_id": new_job_id,
        "message": "UC doorway course mapping job queued.",
    }


@router.get("/status")
def get_uc_doorway_course_mapping_status():
    return get_uc_doorway_mapping_runtime_status()