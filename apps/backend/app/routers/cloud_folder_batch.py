import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import CloudFileLocation, ExtractionFileDetails, ClassifiersType
from app.routers.auth import get_current_user
from app.routers.cloud_folder_locations import (
    _detect_classifier_name,
    _select_processor_id,
)
from app.services.cloud_storage_service import CloudStorageService
from app.services.transcript_processor import (
    ExtractionContext,
    ProcessorConfig,
    TranscriptProcessor,
)


router = APIRouter(
    prefix="/cloud-folder-locations",
    tags=["Cloud Folder Batch"],
)


TERMINAL_SKIP_STATUSES = {
    "processing",
    "completed",
    "completed_with_errors",
    "needs_review",
}


@router.post("/extract-all")
async def extract_all_folders(
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """
    Extract all active cloud folders for the current user's institution.

    Flow:
    - Finds all active cloud folders for the user's institution.
    - Lists classified PDF files from GCS.
    - Skips files already completed, processing, completed_with_errors, or needs_review.
    - Runs Document AI extraction.
    - Runs Gemini course-count validation through TranscriptProcessor.
    - Marks file as completed or needs_review based on validation result.
    """

    institution_id = getattr(current_user, "institution_id", None)

    if institution_id is None:
        raise HTTPException(
            status_code=403,
            detail="User not linked to an institution",
        )

    folders: List[CloudFileLocation] = (
        (
            await session.execute(
                select(CloudFileLocation)
                .where(
                    CloudFileLocation.institution_id == institution_id,
                    CloudFileLocation.is_active.is_(True),
                    CloudFileLocation.deleted_at.is_(None),
                )
                .order_by(CloudFileLocation.id.asc())
            )
        )
        .scalars()
        .all()
    )

    if not folders:
        return {
            "ok": True,
            "folders": [],
            "message": "No active cloud folders found",
        }

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)

    project_id = os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript")
    location = os.environ.get("DOC_AI_LOCATION", "us")
    default_processor_id = os.environ.get(
        "DOC_AI_PROCESSOR",
        "4bf06de9ecadb866",
    )

    processor = TranscriptProcessor(
        ProcessorConfig(
            project_id=project_id,
            location=location,
            processor_id=default_processor_id,
        )
    )

    summary: List[Dict[str, Any]] = []

    for folder in folders:
        folder_stats: Dict[str, Any] = {
            "folder_id": int(folder.id),
            "label": folder.label,
            "year_intake": folder.year_intake,
            "processed_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "details": [],
        }

        prefix = storage.build_classified_upload_prefix(
            folder.year_intake,
            None,
        )

        files = await asyncio.to_thread(
            storage.list_files,
            bucket_name,
            prefix,
        )

        pdf_files = [
            item
            for item in files
            if str(item.get("name") or "").lower().endswith(".pdf")
        ]

        for item in pdf_files:
            file_name = str(item["name"]).split("/")[-1]
            file_path = item.get("path") or item["name"]
            gcs_uri = f"gs://{bucket_name}/{file_path}"

            existing = (
                await session.execute(
                    select(ExtractionFileDetails)
                    .where(
                        ExtractionFileDetails.institution_id == institution_id,
                        ExtractionFileDetails.file_name == file_name,
                        ExtractionFileDetails.year_intake == folder.year_intake,
                    )
                    .order_by(ExtractionFileDetails.id.desc())
                )
            ).scalars().first()

            if existing and existing.process_status in TERMINAL_SKIP_STATUSES:
                folder_stats["skipped_files"] += 1
                folder_stats["details"].append(
                    {
                        "file_name": file_name,
                        "status": "skipped",
                        "process_status": existing.process_status,
                        "reason": f"already_{existing.process_status}",
                    }
                )
                continue

            if existing is None:
                existing = ExtractionFileDetails(
                    file_name=file_name,
                    process_status="uploaded",
                    institution_id=institution_id,
                    year_intake=folder.year_intake,
                    program_id=None,
                    upload_date=datetime.now(timezone.utc),
                )

                session.add(existing)
                await session.commit()
                await session.refresh(existing)

            # Gate: only extract transcripts whose school type has a trained
            # extractor. An unrecognized school (classifier -> "others") has no
            # extractor yet; extracting it would run the wrong/fallback processor
            # and dump garbage into Needs Review. Those must go to New Transcript
            # Type for setup instead, and stay out of extraction until a real
            # extractor is integrated for that school.
            # A school has a real extractor only when it resolves to a known
            # classifier (not the "others" catch-all). Do NOT trust
            # existing.classifier_type here — a prior run links unknown schools to
            # the generic "others" classifier, which is exactly what must be
            # blocked. Unknown schools go to New Transcript Type, never extracted.
            # Detect from the FILE NAME only — the folder path can be a
            # mis-classification that hides the real (unknown) school.
            detected_classifier = _detect_classifier_name(file_name)
            has_extractor = detected_classifier != "others"
            if not has_extractor:
                existing.process_status = "new_type"
                await session.commit()
                folder_stats["skipped_files"] += 1
                folder_stats["details"].append(
                    {
                        "file_name": file_name,
                        "status": "skipped",
                        "process_status": "new_type",
                        "reason": "no_extractor_awaiting_new_type_setup",
                    }
                )
                continue

            try:
                content = await asyncio.to_thread(
                    storage.download_file,
                    bucket_name,
                    file_path,
                )

                stored_processor_id = None

                if existing.classifier_type:
                    stored_processor_id = (
                        await session.execute(
                            select(ClassifiersType.processor_id).where(
                                ClassifiersType.id == existing.classifier_type
                            )
                        )
                    ).scalar_one_or_none()

                processor_id = stored_processor_id or _select_processor_id(
                    file_name,
                    file_path,
                )

                classifier_name = _detect_classifier_name(
                    file_name,
                    file_path,
                )

                ctx = ExtractionContext(
                    extraction_file_id=int(existing.id),
                    institution_id=institution_id,
                    classifier_type_id=(
                        int(existing.classifier_type)
                        if existing.classifier_type
                        else 0
                    ),
                    used_processor_id=processor_id,
                    classifier_name=classifier_name,
                    file_name=file_name,
                )

                result = await processor.process_bytes_and_persist(
                    session,
                    ctx,
                    content,
                    gcs_uri=gcs_uri,
                )

                process_status = result.get("process_status", "completed")
                course_validation = result.get("course_validation")

                folder_stats["processed_files"] += 1
                folder_stats["details"].append(
                    {
                        "file_name": file_name,
                        "status": "processed",
                        "process_status": process_status,
                        "students": result.get("students", 0),
                        "courses": result.get("courses", 0),
                        "course_validation": course_validation,
                    }
                )

            except Exception as exc:
                folder_stats["failed_files"] += 1

                existing.process_status = "failed"
                await session.commit()

                folder_stats["details"].append(
                    {
                        "file_name": file_name,
                        "status": "failed",
                        "reason": str(exc),
                    }
                )

        summary.append(folder_stats)

    return {
        "ok": True,
        "folders": summary,
    }