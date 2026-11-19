from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import StudentAgSummary

logger = logging.getLogger(__name__)


async def compute_and_store_ag_summary(
    db: AsyncSession,
    student_id: int,
) -> Optional[StudentAgSummary]:
    """Call the SQL function that computes and upserts calc columns for one student."""
    await db.execute(
        text("SELECT compute_student_ag_summary(:sid)"),
        {"sid": student_id},
    )
    stmt = select(StudentAgSummary).where(StudentAgSummary.student_id == student_id)
    return (await db.execute(stmt)).scalars().first()


async def compute_ag_summaries_for_file(
    session_factory: async_sessionmaker,
    extraction_file_id: int,
) -> None:
    """Compute AG summaries for every student in a file after UC mapping completes."""
    logger.info(f"[AG_SUMMARY] Computing summaries for file_id={extraction_file_id}")
    try:
        async with session_factory() as db:
            result = await db.execute(
                text("SELECT id FROM student_details WHERE source_file = :fid"),
                {"fid": extraction_file_id},
            )
            student_ids = [r[0] for r in result.fetchall()]

        for sid in student_ids:
            try:
                async with session_factory() as db:
                    await db.execute(
                        text("SELECT compute_student_ag_summary(:sid)"),
                        {"sid": sid},
                    )
                    await db.commit()
            except Exception:
                logger.exception(f"[AG_SUMMARY] Failed for student_id={sid}")

        logger.info(f"[AG_SUMMARY] Done for file_id={extraction_file_id}, students={len(student_ids)}")
    except Exception:
        logger.exception(f"[AG_SUMMARY] Outer error for file_id={extraction_file_id}")
