from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
import asyncio

from app.db import get_session
from app.models import (
    AcademicTerm, CloudFileLocation, ExtractionFileDetails,
    Students, Course_details, FinalCourseDetails, GeminiCourseDetails,
    CourseExtractionMatches, StudentAgSummary, CourseDetailMappingUcDoorwayCourses,
)
from app.services.cloud_storage_service import CloudStorageService
# from app.schemas.terms import TermCreate, TermOut


from typing import Literal
from pydantic import BaseModel

class TermCreate(BaseModel):
    term: Literal["spring", "summer", "fall", "winter"]
    year: int
    term_name: str
    institution_id: int
    created_by_user_id: str

class TermOut(BaseModel):
    id: int
    term_name: str
    term: str
    year: int
    institution_id: int
    is_current: bool

    class Config:
        from_attributes = True


router = APIRouter(prefix="/academic-terms", tags=["Academic Term"])

@router.post("", response_model=TermOut)
async def create_term(payload: TermCreate, session: AsyncSession = Depends(get_session)):
    # Normalize term string (capitalize first letter)
    term_clean = payload.term_name.strip()
    term_clean = term_clean[0].upper() + term_clean[1:] if term_clean else payload.term
    payload.term_name = term_clean

    # Avoid duplicate term rows for same institution/term_name (case-insensitive)
    existing_term = (
        await session.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution_id == payload.institution_id,
                func.lower(AcademicTerm.term_name) == func.lower(term_clean),
            )
        )
    ).scalar_one_or_none()
    if existing_term:
        return existing_term

    term = AcademicTerm(
        term_name=term_clean,
        term=payload.term,
        year=payload.year,
        institution_id=payload.institution_id,
        created_by=str(payload.created_by_user_id) if payload.created_by_user_id else None,
        is_current=False,
    )
    session.add(term)
    await session.commit()
    await session.refresh(term)

    # Automatically create a term-level cloud folder (no program dimension)
    term_label_str = payload.term_name.strip()
    term_word = term_label_str.split()[0].capitalize() if term_label_str else payload.term.capitalize()
    folder_label = term_label_str if term_label_str else f"{term_word} {payload.year}"
    existing_folder = (
        await session.execute(
            select(CloudFileLocation).where(
                CloudFileLocation.institution_id == payload.institution_id,
                func.lower(CloudFileLocation.year_intake) == func.lower(payload.term_name),
                CloudFileLocation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not existing_folder:
        folder = CloudFileLocation(
            label=folder_label,
            year_intake=payload.term_name,
            sync_status="unsynced",
            program_name=None,
            institution_id=payload.institution_id,
            updated_by_user_id=payload.created_by_user_id,
            is_active=True,
        )
        session.add(folder)
        await session.commit()

        # Create the term folder + its handbook/ subfolder in storage (background).
        storage = CloudStorageService()
        asyncio.create_task(
            asyncio.to_thread(
                storage.ensure_term_and_course_prefixes,
                payload.institution_id,
                payload.term_name,
                None,
                [],
            )
        )
        asyncio.create_task(
            asyncio.to_thread(storage.ensure_handbook_folder, payload.term_name)
        )

    return term

@router.get("", response_model=list[TermOut])
async def list_terms(institution_id: int, session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(AcademicTerm)
        .where(AcademicTerm.institution_id == institution_id)
        .order_by(AcademicTerm.year.desc())
    )
    return res.scalars().all()


@router.delete("/{term_id}")
async def delete_term(term_id: int, session: AsyncSession = Depends(get_session)):
    term = (await session.execute(
        select(AcademicTerm).where(AcademicTerm.id == term_id)
    )).scalar_one_or_none()

    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    term_name = term.term_name

    # Get all extraction files for this term
    file_ids_result = await session.execute(
        select(ExtractionFileDetails.id)
        .where(ExtractionFileDetails.year_intake == term_name)
    )
    file_ids = [row[0] for row in file_ids_result.fetchall()]

    if file_ids:
        # Delete in dependency order
        student_ids_result = await session.execute(
            select(Students.id).where(Students.source_file.in_(file_ids))
        )
        student_ids = [row[0] for row in student_ids_result.fetchall()]

        if student_ids:
            await session.execute(delete(StudentAgSummary).where(StudentAgSummary.student_id.in_(student_ids)))

        await session.execute(delete(CourseDetailMappingUcDoorwayCourses).where(
            CourseDetailMappingUcDoorwayCourses.course_details_id.in_(
                select(Course_details.id).where(Course_details.source_file.in_(file_ids))
            )
        ))
        await session.execute(delete(CourseExtractionMatches).where(
            CourseExtractionMatches.extraction_file_id.in_(file_ids)
        ))
        await session.execute(delete(FinalCourseDetails).where(FinalCourseDetails.source_file.in_(file_ids)))
        await session.execute(delete(GeminiCourseDetails).where(GeminiCourseDetails.source_file.in_(file_ids)))
        await session.execute(delete(Course_details).where(Course_details.source_file.in_(file_ids)))
        await session.execute(delete(Students).where(Students.source_file.in_(file_ids)))
        await session.execute(delete(ExtractionFileDetails).where(ExtractionFileDetails.id.in_(file_ids)))

    # Delete cloud file location for this term
    await session.execute(delete(CloudFileLocation).where(
        CloudFileLocation.year_intake == term_name
    ))

    # Tear down the term's LLM rules: DB rows + verdicts + the GCS handbook folder.
    from app import models as _m
    from app.routers.term_rules import invalidate_rules_cache
    rs_rows = (await session.execute(
        select(_m.TermRuleSet.institution_id).where(_m.TermRuleSet.year_intake == term_name)
    )).scalars().all()
    inst_ids = set(rs_rows)
    await session.execute(delete(_m.TermRuleSet).where(_m.TermRuleSet.year_intake == term_name))
    for iid in inst_ids:
        invalidate_rules_cache(iid, term_name)
    try:
        storage = CloudStorageService()
        bucket = storage.ensure_bucket()
        asyncio.create_task(
            asyncio.to_thread(storage.delete_prefix, bucket, storage.handbook_prefix(term_name))
        )
    except Exception:
        pass

    await session.delete(term)
    await session.commit()

    return {"deleted": True, "term_name": term_name}
