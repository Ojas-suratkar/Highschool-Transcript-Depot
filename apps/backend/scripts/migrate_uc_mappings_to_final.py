#!/usr/bin/env python3
"""
Migrate UC course mappings from course_details to final_course_details.

This script copies existing UC mappings so that:
- Old files with course_details mappings work with batch-calculate
- A-G and GPA tabs can find UC course data for final_course_details rows
"""

import asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models import (
    CourseDetailMappingUcDoorwayCourses,
    FinalCourseDetail,
    Course_details,
)


async def migrate_mappings(db_url: str):
    """Migrate UC mappings from course_details to final_course_details."""

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        print("[MIGRATION] Starting UC mapping migration...")

        # Find all mappings linked to course_details
        result = await session.execute(
            select(CourseDetailMappingUcDoorwayCourses)
            .where(CourseDetailMappingUcDoorwayCourses.course_details_id.isnot(None))
            .where(CourseDetailMappingUcDoorwayCourses.final_course_details_id.is_(None))
        )
        old_mappings = result.scalars().all()

        print(f"[MIGRATION] Found {len(old_mappings)} mappings on course_details without final_course_details link")

        migrated = 0
        skipped = 0

        for mapping in old_mappings:
            try:
                # Find the corresponding final_course_details row
                # Match by: same student, same course ID
                doc_result = await session.execute(
                    select(Course_details)
                    .where(Course_details.id == mapping.course_details_id)
                )
                doc_row = doc_result.scalar_one_or_none()

                if not doc_row:
                    skipped += 1
                    continue

                # Find final_course_details with same s_id and crs_id and document_ai_course_detail_id
                final_result = await session.execute(
                    select(FinalCourseDetail)
                    .where(
                        FinalCourseDetail.s_id == doc_row.s_id,
                        FinalCourseDetail.crs_id == doc_row.crs_id,
                        FinalCourseDetail.document_ai_course_detail_id == mapping.course_details_id,
                    )
                )
                final_row = final_result.scalar_one_or_none()

                if final_row:
                    # Link the mapping to final_course_details
                    mapping.final_course_details_id = final_row.id
                    migrated += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"[MIGRATION ERROR] Failed to migrate mapping {mapping.id}: {e}")
                skipped += 1

        # Commit all changes
        await session.commit()

        print(f"[MIGRATION] Migrated: {migrated}, Skipped: {skipped}")
        print("[MIGRATION] Done!")


if __name__ == "__main__":
    import os

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/transcripts"
    )

    asyncio.run(migrate_mappings(db_url))
