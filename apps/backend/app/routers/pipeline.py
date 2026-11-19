from fastapi import APIRouter, Depends
router = APIRouter(prefix="/pipeline", tags=["pipeline"])
from threading import Thread, Lock
from collections import deque
from datetime import datetime
import uuid
import traceback
import asyncio
from app.db import get_session
from app.models import PipelineJob
from app.schemas import JobResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.semester_classification_clustering import run_pipeline_for_all_semesters

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

queue_lock = Lock()

job_queue = deque()
is_running = False
current_job_id = None
last_finished_job_id = None
last_error = None
last_run_status = "idle"   # idle | running | success | failed
started_at = None
finished_at = None
progress_stage = None
progress_percent = 0
cancel_requested = False

async def _update_job_status(job_id: str, status: str, error: str | None = None):
    async for session in get_session():
        job = (
            await session.execute(
                select(PipelineJob).where(PipelineJob.id == uuid.UUID(job_id))
            )
        ).scalar_one_or_none()

        if job:
            job.status = status
            job.error = error
            await session.commit()

        break

def _worker_loop():
    global is_running, current_job_id, last_finished_job_id
    global last_error, last_run_status, started_at, finished_at, progress_stage, progress_percent, cancel_requested

    while True:
        with queue_lock:
            if not job_queue:
                is_running = False
                current_job_id = None
                progress_stage = None
                progress_percent = 0
                return
            if cancel_requested:
                job_queue.clear()
                is_running = False
                current_job_id = None
                progress_stage = "cancelled"
                progress_percent = 0
                cancel_requested = False
                return

            current_job_id = job_queue.popleft()
            last_run_status = "running"
            last_error = None
            started_at = datetime.utcnow().isoformat()
            finished_at = None
            progress_stage = "queued"
            progress_percent = 0

        # DB: mark running
        asyncio.run(_update_job_status(current_job_id, "running"))

        # DB: mark running
        asyncio.run(_update_job_status(current_job_id, "running"))

        try:
            def _set_progress(stage, pct):
                with queue_lock:
                    globals()['progress_stage'] = stage
                    globals()['progress_percent'] = int(pct)
                    if cancel_requested:
                        raise KeyboardInterrupt("Pipeline cancellation requested")
            run_pipeline_for_all_semesters(progress_cb=_set_progress, should_cancel=lambda: cancel_requested)

            with queue_lock:
                last_run_status = "success"
                last_finished_job_id = current_job_id
                finished_at = datetime.utcnow().isoformat()
                progress_stage = "done"
                progress_percent = 100

            # DB: mark completed
            asyncio.run(_update_job_status(current_job_id, "completed"))

            # DB: mark completed
            asyncio.run(_update_job_status(current_job_id, "completed"))

        except KeyboardInterrupt:
            with queue_lock:
                last_run_status = "cancelled"
                last_finished_job_id = current_job_id
                finished_at = datetime.utcnow().isoformat()
                progress_stage = "cancelled"
                progress_percent = 0
                cancel_requested = False
            asyncio.run(_update_job_status(current_job_id, "cancelled", "Cancelled by user"))
        except Exception:
            error_text = traceback.format_exc()
            # DB: mark failed
            asyncio.run(_update_job_status(current_job_id, "failed", error_text))

            with queue_lock:
                last_run_status = "failed"
                last_error = error_text
                last_finished_job_id = current_job_id
                finished_at = datetime.utcnow().isoformat()
                progress_stage = "error"


@router.post("/run-semester")
async def run_semester_pipeline(session: AsyncSession = Depends(get_session)):
    global is_running

    new_job_uuid = uuid.uuid4()
    new_job_id = str(new_job_uuid)

    job = PipelineJob(
        id=new_job_uuid,
        job_type="semester_pipeline",
        status="queued",
        created_at=datetime.utcnow(),
        error=None,
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    with queue_lock:
        job_queue.append(new_job_id)

        should_start = not is_running
        if should_start:
            is_running = True
            Thread(target=_worker_loop, daemon=True).start()

        waiting_count = len(job_queue)
        queue_position = 0 if should_start else waiting_count

    return {
        "status": "queued",
        "job_id": new_job_id,
        "message": "Pipeline request queued. It will run in order.",
        "queue_position": queue_position,
    }


@router.post("/run-all")
async def run_all_semesters_pipeline(session: AsyncSession = Depends(get_session)):
    """
    Placeholder endpoint to trigger the pipeline for all semesters.
    Currently queues a job identical to /run-semester; worker already runs all semesters.
    """
    global is_running

    new_job_uuid = uuid.uuid4()
    new_job_id = str(new_job_uuid)

    job = PipelineJob(
        id=new_job_uuid,
        job_type="all_semesters_pipeline",
        status="queued",
        created_at=datetime.utcnow(),
        error=None,
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    with queue_lock:
        job_queue.append(new_job_id)

        should_start = not is_running
        if should_start:
            is_running = True
            Thread(target=_worker_loop, daemon=True).start()

        waiting_count = len(job_queue)
        queue_position = 0 if should_start else waiting_count

    return {
        "status": "queued",
        "job_id": new_job_id,
        "message": "All-semesters pipeline queued. It will run in order.",
        "queue_position": queue_position,
    }


@router.get("/status")
def pipeline_status():
    with queue_lock:
        return {
            "last_run_status": last_run_status,
            "is_running": is_running,
            "current_job_id": current_job_id,
            "queued_jobs": list(job_queue),
            "queue_length": len(job_queue),
            "started_at": started_at,
            "finished_at": finished_at,
            "last_error": last_error,
            "last_finished_job_id": last_finished_job_id,
            "progress_stage": progress_stage,
            "progress_percent": progress_percent,
        }


@router.post("/cancel")
def cancel_pipeline():
    global cancel_requested, is_running, progress_stage, progress_percent
    with queue_lock:
        job_queue.clear()
        cancel_requested = True
        if not is_running:
            cancel_requested = False
            progress_stage = "cancelled"
            progress_percent = 0
            return {"ok": True, "message": "No pipeline running; queue cleared"}
    return {"ok": True, "message": "Cancellation requested"}
