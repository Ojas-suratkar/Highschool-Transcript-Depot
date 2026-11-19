# app/routers/cloud_folder_locations.py
import os
import uuid as uuid_lib
import logging
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from ..db import AsyncSessionLocal, get_session
from app.models import CloudFileLocation, ExtractionFileDetails, ClassifiersType, PipelineJob
from .auth import get_current_user
from ..services.cloud_storage_service import CloudStorageService
from ..services.extraction_job_service import extraction_job_service
from ..services.transcript_processor import ExtractionContext, ProcessorConfig, TranscriptProcessor
from ..services.new_transcript_type_extraction_service import NewTranscriptTypeExtractionService
from app.services.semester_classification_clustering import (
    run_pipeline_for_semester,
    classify_blob_pipeline,
    gcs_list_pdfs,
    GCS_BUCKET,
    GCS_INPUT_PREFIX,
    get_semester_from_input_blob,
    cluster_and_group_others_gcs,
)
from app.services.uc_doorway_course_mapping_service import schedule_uc_mapping_bg_task, run_uc_mapping_for_file
import asyncio

router = APIRouter(prefix="/cloud-folder-locations", tags=["Cloud Folder Locations"])
logger = logging.getLogger(__name__)

# Only GCS uploads supported; polling/drive disabled.
SUPPORTED_SOURCES = {"gcs"}

# A file in any of these statuses has already been extracted (or is mid-flight)
# and must NOT be re-extracted on a subsequent run. needs_review in particular
# is a finished extraction awaiting a human ΓÇö re-running it wipes/duplicates the
# review work, which is the repeated-extraction bug users hit.
FINALIZED_EXTRACTION_STATUSES = {
    "completed",
    "completed_with_errors",
    "needs_review",
    "needs_review_audit",
}

ALREADY_EXTRACTED_STATUSES = {
    "processing",
    *FINALIZED_EXTRACTION_STATUSES,
}


def _normalized_gcs_path(path: str | None) -> str:
    """Return a slash-normalized, lowercase GCS object path for routing checks."""
    return "/" + str(path or "").replace("\\", "/").strip("/").lower()


def _is_grouped_new_transcript_path(path: str | None) -> bool:
    """True only for clustered new transcript types handled by Gemini alone."""
    normalized = _normalized_gcs_path(path)
    return "/transcript/others/grouped_by_school/" in normalized


def _is_extractable_classified_pdf(item: dict) -> bool:
    """Keep known/integrated transcript PDFs and clustered new transcript PDFs.

    Ungrouped Others files are intentionally excluded until clustering places
    them under Others/Grouped_by_school/<school>/.
    """
    name = str(item.get("name") or item.get("path") or "")
    normalized = _normalized_gcs_path(name)
    if not normalized.endswith(".pdf"):
        return False
    if "/not_a_transcript/" in normalized:
        return False
    if "/transcript/others/" in normalized and not _is_grouped_new_transcript_path(normalized):
        return False
    return True


def _is_gcs_not_found_error(exc_or_message) -> bool:
    """Recognize the stale raw-GCS-path race raised by Google storage helpers."""
    message = str(exc_or_message or "").lower()
    return (
        "404" in message
        or "no such object" in message
        or "failed to read gcs object metadata" in message
        or "not found" in message
        or "was not found" in message
    )


async def _resolve_current_gcs_object_path(
    *,
    storage: "CloudStorageService",
    bucket_name: str,
    transcript_prefix: str,
    candidate_path: str,
) -> str:
    """
    Return the object's current classified path.

    The fresh phase-2 path is checked first. If another legitimate mover changed
    it after the listing, resolve by exact basename inside this term's classified
    transcript tree. Ambiguous duplicates are rejected instead of guessing.
    """
    normalized_candidate = (
        str(candidate_path or "").replace("\\", "/").strip("/")
    )
    if not normalized_candidate:
        raise FileNotFoundError("The extraction candidate has no GCS path.")

    bucket = storage.client.bucket(bucket_name)
    blob = bucket.blob(normalized_candidate)
    if await asyncio.to_thread(blob.exists, storage.client):
        return normalized_candidate

    file_name = PurePosixPath(normalized_candidate).name
    current_files = await asyncio.to_thread(
        storage.list_files,
        bucket_name,
        transcript_prefix,
    )
    matches = sorted(
        {
            str(item.get("path") or item.get("name") or "")
            .replace("\\", "/")
            .strip("/")
            for item in current_files
            if _is_extractable_classified_pdf(item)
            and PurePosixPath(
                str(item.get("path") or item.get("name") or "")
            ).name
            == file_name
        }
    )

    if not matches:
        raise FileNotFoundError(
            "No current classified GCS object exists for "
            f"{file_name!r}. Last known path: "
            f"gs://{bucket_name}/{normalized_candidate}"
        )
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple current classified GCS objects share the same filename "
            f"{file_name!r}; refusing to choose the wrong transcript: "
            + ", ".join(matches)
        )

    logger.warning(
        "Resolved moved GCS object for %s: %s -> %s",
        file_name,
        normalized_candidate,
        matches[0],
    )
    return matches[0]


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    """
    Parse gs://bucket/prefix URIs into (bucket, prefix).
    prefix may be ''.
    """
    if not uri or not uri.startswith("gs://"):
        raise ValueError("Expected a gs://bucket/path URI")
    without = uri[len("gs://") :]
    parts = without.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    prefix = prefix.strip("/")
    return bucket, prefix


def _guess_source_type(uri: str | None) -> str | None:
    if not uri:
        return None
    if uri.startswith("gs://"):
        return "gcs"
    return None


# Runtime-integrated transcript types live in the classifier_type table; the
# shared registry mirrors them into a cached lookup so the sync processor-picker
# can route their transcript/<type>/ folders with no redeploy. (invalidate alias
# kept for the integrate endpoint that already imports this name.)
from app.services.classifier_registry import (
    get_integrated_classifiers as _get_dynamic_classifiers,
    invalidate_classifier_cache as invalidate_dynamic_classifier_cache,
    HARDCODED_CLASSIFIERS as _HARDCODED_CLASSIFIERS,
)


# Processor picker: prefer folder path under 02 library, then filename keywords
def _detect_classifier_name(file_name: str, path: str | None = None) -> str:
    text = f"{path or ''} {file_name or ''}".lower()

    # Path-based (02 library layout)
    if "transcript/lbusd" in text:
        return "lbusd"
    if "transcript/mayfair_high_school" in text or "mayfair" in text:
        return "mayfair_high_school"
    if "transcript/st_anthony_high_school" in text or "st anthony" in text or "st_anthony" in text:
        return "st_anthony_high_school"

    # Filename fallbacks
    if "mayfair" in text:
        return "mayfair_high_school"
    if "anthony" in text or "st_anthony" in text or "st-anthony" in text or "st anthony" in text:
        return "st_anthony_high_school"
    if "lbusd" in text or "lb usd" in text or "/lb" in text or "lb_" in text:
        return "lbusd"

    # Positive filename rescue for known LBUSD member schools.
    _lbusd_schools = (
        "cabrillo high",
        "millikan high",
        "sato academy",
        "jordan high",
        "wilson high",
        "mcbride high",
        "avalon high",
        "lakewood high",
        "browning high",
        "california academy",
        "_cams",
    )
    if any(school in text for school in _lbusd_schools):
        return "lbusd"

    # Runtime-integrated transcript types are routed by classified folder.
    for name in _get_dynamic_classifiers():
        if name in _HARDCODED_CLASSIFIERS:
            continue
        if f"transcript/{name}" in text:
            return name

    return "others"


def _rescue_known_transcript_destination(
    *,
    pipeline_result: dict,
    file_name: str,
) -> str:
    """
    Positive filename rescue for the three built-in known transcript formats.

    This only moves a PDF when the filename itself clearly names a known format
    but the classifier placed it elsewhere. Unknown-school filenames are never
    forced into a known extractor by this helper.
    """
    destination_path = str(pipeline_result.get("dest_blob") or "")
    if not destination_path or "/transcript/" not in destination_path:
        return destination_path

    hardcoded_folder = {
        "lbusd": "LBUSD",
        "mayfair_high_school": "Mayfair_High_School",
        "st_anthony_high_school": "St_Anthony_High_School",
    }
    name_based = _detect_classifier_name(file_name)
    model_based = str(pipeline_result.get("classifier_name") or "others")
    if name_based not in hardcoded_folder or model_based == name_based:
        return destination_path

    head, separator, tail = destination_path.partition("/transcript/")
    if not separator:
        return destination_path
    _current_folder, slash, remainder = tail.partition("/")
    if not slash or not remainder:
        return destination_path

    target_path = (
        f"{head}/transcript/{hardcoded_folder[name_based]}/{remainder}"
    )
    if target_path == destination_path:
        return destination_path

    storage = CloudStorageService()
    bucket = storage.client.bucket(storage.get_bucket_name())
    source_blob = bucket.blob(destination_path)
    if not source_blob.exists(storage.client):
        # Another task may already have moved it. Phase 2 will fresh-list anyway.
        return destination_path

    bucket.copy_blob(source_blob, bucket, target_path)
    source_blob.delete()
    pipeline_result["dest_blob"] = target_path
    pipeline_result["classifier_name"] = name_based
    pipeline_result["is_other"] = False
    logger.info(
        "Classification rescue: %s moved from %s to %s (model said %s).",
        file_name,
        destination_path,
        target_path,
        model_based,
    )
    return target_path


def _select_processor_id(file_name: str, path: str | None = None) -> str:
    classifier_name = _detect_classifier_name(file_name, path)
    if classifier_name == "mayfair_high_school":
        return "4bf06de9ecadb866"  # Mayfair_transcript_type2
    if classifier_name == "st_anthony_high_school":
        return "7ec1dfc2705ce10d"  # ST_Anthony_High_School
    if classifier_name == "lbusd":
        return "eec9a0bd33bef934"  # LBUSD_CustomExtractor_V1

    # Runtime-integrated types: look up the processor wired during integration.
    dynamic = _get_dynamic_classifiers()
    if classifier_name in dynamic:
        return dynamic[classifier_name]

    # fallback to env default
    return os.environ.get("DOC_AI_PROCESSOR", "4bf06de9ecadb866")


async def _resolve_processor_id(
    session: AsyncSession,
    extraction_row: ExtractionFileDetails | None,
    file_name: str,
    path: str | None = None,
) -> str:
    """
    Prefer a processor already linked to this extraction (classifier_type.processor_id),
    otherwise fall back to filename-based selection, then env default.
    """
    if extraction_row and extraction_row.classifier_type:
        res = await session.execute(
            select(ClassifiersType.processor_id).where(ClassifiersType.id == extraction_row.classifier_type)
        )
        proc = res.scalar_one_or_none()
        if proc:
            return proc
    return _select_processor_id(file_name, path)


class CloudFolderCreate(BaseModel):
    label: str
    year_intake: str  # e.g. "2026-2027"
    # optional list of initial course names to create under the term
    courses: list[str] | None = None
    # Accept optional fields coming from frontend (ignored server-side)
    user_id: str | None = None
    institution_id: int | None = None



class CloudFolderUpdate(BaseModel):
    label: str
    # url: HttpUrl
    year_intake: str


class CloudFolderOut(BaseModel):
    id: int
    label: str
    # url: str
    year_intake: str
    last_polled: datetime|None
    updated_at: datetime


class CloudFolderNodeOut(BaseModel):
    name: str
    path: str
    kind: str  # 'folder' or 'file'
    size_bytes: int | None = None
    updated_at: datetime | None = None


class FolderExtractionOut(BaseModel):
    ok: bool
    processed_files: int
    skipped_files: int
    failed_files: int
    details: list[dict]


class FolderExtractionJobOut(BaseModel):
    id: str
    folder_id: int
    folder_label: str
    program_name: str | None = None
    year_intake: str
    status: str
    percent_complete: int
    total_files: int
    processed_files: int
    skipped_files: int
    failed_files: int
    current_file: str | None = None
    details: list[dict]
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    eta_seconds: int | None = None


class FolderExtractionJobStart(BaseModel):
    """Optional controls used only by explicit transcript re-extraction."""

    force_reextract: bool = False
    selected_file_ids: list[int] | None = None


def _job_response(job: dict) -> FolderExtractionJobOut:
    return FolderExtractionJobOut(**job)


async def _extract_one_file(
    item: dict,
    institution_id: int,
    folder_year_intake: str,
    bucket_name: str,
    processor: "TranscriptProcessor",
    resolved_program_id,
    semaphore: asyncio.Semaphore,
    storage: "CloudStorageService",
    job_id: str | None = None,
    force_reextract: bool = False,
) -> dict:
    """
    Extract one transcript using its CURRENT classified GCS object path.

    Forced reruns bypass only the finalized-status guard. Existing transcript
    data is never pre-deleted here. If a forced replacement fails, the previous
    finalized file status is restored.
    """
    async with semaphore:
        candidate_path = str(item.get("path") or item.get("name") or "")
        file_name = PurePosixPath(candidate_path).name
        if not file_name:
            return {
                "status": "failed",
                "file_name": "unknown",
                "reason": "Extraction candidate is missing a file name.",
            }

        if job_id:
            state = extraction_job_service.get_job(job_id, institution_id)
            if state and state.get("status") == "cancelled":
                return {
                    "status": "skipped",
                    "file_name": file_name,
                    "reason": "cancelled",
                }

        transcript_prefix = (
            f"{storage.get_classified_root_prefix()}/"
            f"{folder_year_intake}/transcript/"
        )
        mapping_file_id: int | None = None
        out: dict | None = None
        previous_status: str | None = None

        async with AsyncSessionLocal() as session:
            extraction_row = (
                await session.execute(
                    select(ExtractionFileDetails)
                    .where(
                        ExtractionFileDetails.institution_id == institution_id,
                        ExtractionFileDetails.file_name == file_name,
                        ExtractionFileDetails.year_intake == folder_year_intake,
                        ExtractionFileDetails.program_id == resolved_program_id,
                    )
                    .order_by(ExtractionFileDetails.id.desc())
                )
            ).scalars().first()

            if extraction_row is not None:
                previous_status = extraction_row.process_status

            if (
                extraction_row is not None
                and extraction_row.process_status in ALREADY_EXTRACTED_STATUSES
                and not force_reextract
            ):
                return {
                    "status": "skipped",
                    "file_name": file_name,
                    "reason": f"already_{extraction_row.process_status}",
                    "process_status": extraction_row.process_status,
                }

            if extraction_row is None:
                extraction_row = ExtractionFileDetails(
                    file_name=file_name,
                    process_status="uploaded",
                    institution_id=institution_id,
                    year_intake=folder_year_intake,
                    program_id=resolved_program_id,
                )
                session.add(extraction_row)
                await session.commit()
                await session.refresh(extraction_row)
                previous_status = "uploaded"

            extraction_row.process_status = "processing"
            await session.commit()
            await session.refresh(extraction_row)

            last_exception: Exception | None = None
            for attempt in range(2):
                try:
                    current_path = await _resolve_current_gcs_object_path(
                        storage=storage,
                        bucket_name=bucket_name,
                        transcript_prefix=transcript_prefix,
                        candidate_path=candidate_path,
                    )
                    gcs_uri = f"gs://{bucket_name}/{current_path}"

                    if _is_grouped_new_transcript_path(current_path):
                        transcript_group = PurePosixPath(current_path).parent.name
                        result = (
                            await NewTranscriptTypeExtractionService()
                            .process_gemini_only_transcript(
                                session=session,
                                extraction_file=extraction_row,
                                gcs_uri=gcs_uri,
                                institution_id=institution_id,
                                classifier_name=transcript_group,
                            )
                        )
                        is_new_transcript_type = True
                        if result.get("process_status") == "completed":
                            mapping_file_id = int(extraction_row.id)
                    else:
                        processor_id = await _resolve_processor_id(
                            session,
                            extraction_row,
                            file_name,
                            current_path,
                        )
                        classifier_name = _detect_classifier_name(
                            file_name,
                            current_path,
                        )
                        ctx = ExtractionContext(
                            extraction_file_id=int(extraction_row.id),
                            institution_id=institution_id,
                            classifier_type_id=(
                                int(extraction_row.classifier_type)
                                if extraction_row.classifier_type
                                else 0
                            ),
                            used_processor_id=processor_id,
                            classifier_name=classifier_name,
                            file_name=file_name,
                        )
                        result = await processor.process_bytes_and_persist(
                            session,
                            ctx,
                            gcs_uri=gcs_uri,
                        )
                        mapping_file_id = int(extraction_row.id)
                        is_new_transcript_type = False

                    await session.refresh(extraction_row)
                    out = {
                        "status": "processed",
                        "file_name": file_name,
                        "students": result.get("students", 0),
                        "courses": result.get("courses", 0),
                        "mode": result.get(
                            "mode",
                            (
                                "gemini_only_new_transcript"
                                if is_new_transcript_type
                                else "document_ai_and_gemini"
                            ),
                        ),
                        "is_new_transcript_type": is_new_transcript_type,
                        "review_bucket": result.get("review_bucket"),
                        "process_status": result.get(
                            "process_status",
                            extraction_row.process_status,
                        ),
                        "unresolved_courses": result.get("unresolved_courses", 0),
                        "student_needs_review": result.get(
                            "student_needs_review",
                            False,
                        ),
                        "student_audit_required": result.get(
                            "student_audit_required",
                            False,
                        ),
                    }
                    break

                except Exception as exc:  # noqa: BLE001
                    last_exception = exc
                    await session.rollback()

                    if attempt == 0 and _is_gcs_not_found_error(exc):
                        logger.warning(
                            "GCS object moved while extracting %s; resolving "
                            "its current classified path and retrying once.",
                            file_name,
                        )
                        refreshed = await session.get(
                            ExtractionFileDetails,
                            int(extraction_row.id),
                        )
                        if refreshed is not None:
                            refreshed.process_status = "processing"
                            await session.commit()
                            extraction_row = refreshed
                        await asyncio.sleep(0.25)
                        continue

                    refreshed = await session.get(
                        ExtractionFileDetails,
                        int(extraction_row.id),
                    )
                    if refreshed is not None:
                        if (
                            force_reextract
                            and previous_status in FINALIZED_EXTRACTION_STATUSES
                        ):
                            refreshed.process_status = previous_status
                        elif refreshed.process_status not in FINALIZED_EXTRACTION_STATUSES:
                            refreshed.process_status = "failed"
                        if hasattr(refreshed, "processed_date"):
                            refreshed.processed_date = datetime.now(timezone.utc)
                        await session.commit()

                    logger.exception("Extraction failed for file %s", file_name)
                    return {
                        "status": "failed",
                        "file_name": file_name,
                        "reason": str(exc),
                    }

            if out is None:
                return {
                    "status": "failed",
                    "file_name": file_name,
                    "reason": str(
                        last_exception or "Extraction failed without a result."
                    ),
                }

        if mapping_file_id is not None:
            try:
                await run_uc_mapping_for_file(
                    AsyncSessionLocal,
                    mapping_file_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "UC mapping failed for extraction file %s",
                    mapping_file_id,
                )
                out["mapping_warning"] = str(exc)
        return out


async def _classify_one(
    blob_name: str,
    institution_id: int,
    folder_year_intake: str,
    binary_client,
    layout_client,
    ocr_client,
    resolved_program_id,
    semaphore: asyncio.Semaphore,
    job_id: str | None = None,
) -> dict:
    """
    Phase 1: classify one raw inbox PDF only.

    The Doc AI/layout classifier is authoritative for transcript format.
    Filename matching is only a positive rescue for explicitly known district
    schools. Phase 2 always fresh-lists the classified tree before extraction.
    """
    async with semaphore:
        file_name = PurePosixPath(blob_name).name

        if job_id:
            state = extraction_job_service.get_job(job_id, institution_id)
            if state and state.get("status") == "cancelled":
                return {
                    "status": "skipped",
                    "file_name": file_name,
                    "reason": "cancelled",
                }
            extraction_job_service.set_current_file(job_id, file_name)

        try:
            pipeline_result = await asyncio.to_thread(
                classify_blob_pipeline,
                blob_name,
                binary_client,
                layout_client,
                ocr_client,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_gcs_not_found_error(exc):
                return {
                    "status": "classification_race_resolved",
                    "file_name": file_name,
                }

            pipeline_result = {
                "ok": False,
                "error": str(exc),
                "stage": "classify",
            }

        if not pipeline_result.get("ok"):
            error_message = str(
                pipeline_result.get("error") or "classify failed"
            )

            if _is_gcs_not_found_error(error_message):
                return {
                    "status": "classification_race_resolved",
                    "file_name": file_name,
                }

            async with AsyncSessionLocal() as session:
                existing = (
                    await session.execute(
                        select(ExtractionFileDetails)
                        .where(
                            ExtractionFileDetails.institution_id
                            == institution_id,
                            ExtractionFileDetails.file_name == file_name,
                            ExtractionFileDetails.year_intake
                            == folder_year_intake,
                            ExtractionFileDetails.program_id
                            == resolved_program_id,
                        )
                        .order_by(ExtractionFileDetails.id.desc())
                    )
                ).scalars().first()

                if existing is None:
                    session.add(
                        ExtractionFileDetails(
                            file_name=file_name,
                            process_status="failed",
                            institution_id=institution_id,
                            year_intake=folder_year_intake,
                            program_id=resolved_program_id,
                        )
                    )
                    await session.commit()
                elif existing.process_status not in ALREADY_EXTRACTED_STATUSES:
                    existing.process_status = "failed"
                    await session.commit()

            return {
                "status": "failed",
                "file_name": file_name,
                "reason": error_message,
                "stage": pipeline_result.get("stage"),
            }

        destination_path = str(pipeline_result.get("dest_blob") or "")

        try:
            destination_path = await asyncio.to_thread(
                _rescue_known_transcript_destination,
                pipeline_result=pipeline_result,
                file_name=file_name,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Known-transcript destination rescue failed for %s; "
                "continuing with the freshly classified tree.",
                file_name,
            )
            destination_path = str(
                pipeline_result.get("dest_blob") or destination_path
            )

        if "/not_a_transcript/" in _normalized_gcs_path(destination_path):
            return {
                "status": "skipped",
                "file_name": file_name,
                "reason": "not_a_transcript",
            }

        ml_classifier = str(
            pipeline_result.get("classifier_name") or "others"
        )
        name_based = _detect_classifier_name(file_name)

        built_in_classifiers = {
            "lbusd",
            "mayfair_high_school",
            "st_anthony_high_school",
        }
        extractor_ready_classifiers = (
            built_in_classifiers | set(_get_dynamic_classifiers())
        )

        # Main/teammate behavior: explicit known-school filenames can rescue,
        # otherwise trust the Doc AI/layout classifier result.
        if name_based in built_in_classifiers:
            classifier_name = name_based
        else:
            classifier_name = ml_classifier

        # True Others/new formats continue to Gemini-only Needs AI Extractor.
        if classifier_name not in extractor_ready_classifiers:
            return {
                "status": "needs_ai_extractor",
                "file_name": file_name,
                "reason": f"classifier={classifier_name}",
            }

        return {
            "status": "classified",
            "file_name": file_name,
            "classifier_name": classifier_name,
        }


async def _classify_and_extract_one(
    blob_name: str,
    institution_id: int,
    folder_year_intake: str,
    binary_client,
    layout_client,
    ocr_client,
    processor: "TranscriptProcessor",
    resolved_program_id,
    semaphore: asyncio.Semaphore,
    job_id: str | None = None,
) -> dict:
    """Classify a single inbox PDF then immediately extract it (pipeline approach)."""
    async with semaphore:
        file_name = PurePosixPath(blob_name).name

        if job_id:
            state = extraction_job_service.get_job(job_id, institution_id)
            if state and state.get("status") == "cancelled":
                return {"status": "skipped", "file_name": file_name, "reason": "cancelled"}

        # Run full classify pipeline in a thread (binary ΓåÆ layout ΓåÆ OCR if Others)
        pipeline_result = await asyncio.to_thread(
            classify_blob_pipeline, blob_name, binary_client, layout_client, ocr_client
        )

        if not pipeline_result.get("ok"):
            # Persist a failed record so the file appears in "not processed"
            async with AsyncSessionLocal() as session:
                existing = (await session.execute(
                    select(ExtractionFileDetails).where(
                        ExtractionFileDetails.institution_id == institution_id,
                        ExtractionFileDetails.file_name == file_name,
                        ExtractionFileDetails.year_intake == folder_year_intake,
                        ExtractionFileDetails.program_id == resolved_program_id,
                    )
                )).scalars().first()
                if existing is None:
                    session.add(ExtractionFileDetails(
                        file_name=file_name,
                        process_status="failed",
                        institution_id=institution_id,
                        year_intake=folder_year_intake,
                        program_id=resolved_program_id,
                    ))
                    await session.commit()
                elif existing.process_status not in ("completed", "processing"):
                    existing.process_status = "failed"
                    await session.commit()
            return {"status": "failed", "file_name": file_name, "reason": pipeline_result.get("error", "classify failed"), "stage": pipeline_result.get("stage")}

        classifier_name = pipeline_result.get("classifier_name", "others")

        # Only extract known classifier types ΓÇö Others and non-transcripts are skipped
        if classifier_name not in ("lbusd", "mayfair_high_school", "st_anthony_high_school"):
            return {"status": "skipped", "file_name": file_name, "reason": f"classifier={classifier_name}"}

        dest_blob = pipeline_result["dest_blob"]
        gcs_uri = f"gs://{GCS_BUCKET}/{dest_blob}"

        mapping_file_id = None
        async with AsyncSessionLocal() as session:
            extraction_row = (
                await session.execute(
                    select(ExtractionFileDetails)
                    .where(
                        ExtractionFileDetails.institution_id == institution_id,
                        ExtractionFileDetails.file_name == file_name,
                        ExtractionFileDetails.year_intake == folder_year_intake,
                        ExtractionFileDetails.program_id == resolved_program_id,
                    )
                    .order_by(ExtractionFileDetails.id.desc())
                )
            ).scalars().first()

            if extraction_row and extraction_row.process_status in ALREADY_EXTRACTED_STATUSES:
                return {"status": "skipped", "file_name": file_name, "reason": f"already_{extraction_row.process_status}"}

            if extraction_row is None:
                extraction_row = ExtractionFileDetails(
                    file_name=file_name,
                    process_status="uploaded",
                    institution_id=institution_id,
                    year_intake=folder_year_intake,
                    program_id=resolved_program_id,
                )
                session.add(extraction_row)
                await session.commit()
                await session.refresh(extraction_row)

            # Gate: don't extract a school that has no trained extractor
            # (classifier -> "others"). It must go to New Transcript Type for
            # setup, not be extracted with the fallback processor into review.
            # classifier_type is intentionally NOT trusted: a prior run links
            # unknown schools to the generic "others" classifier. Detect from the
            # FILE NAME only ΓÇö the classified folder path (dest_blob) can be a
            # mis-classification that hides the real school.
            if _detect_classifier_name(file_name) == "others":
                extraction_row.process_status = "new_type"
                await session.commit()
                return {
                    "status": "skipped",
                    "file_name": file_name,
                    "reason": "no_extractor_awaiting_new_type_setup",
                    "process_status": "new_type",
                }

            try:
                processor_id = _select_processor_id(file_name, dest_blob)
                ctx = ExtractionContext(
                    extraction_file_id=int(extraction_row.id),
                    institution_id=institution_id,
                    classifier_type_id=int(extraction_row.classifier_type) if extraction_row.classifier_type else 0,
                    used_processor_id=processor_id,
                    classifier_name=classifier_name,
                    file_name=file_name,
                )
                result = await processor.process_bytes_and_persist(session, ctx, gcs_uri=gcs_uri)
                mapping_file_id = int(extraction_row.id)
                out = {"status": "processed", "file_name": file_name, "students": result.get("students", 0), "courses": result.get("courses", 0)}
            except Exception as exc:
                extraction_row.process_status = "failed"
                await session.commit()
                logger.exception("Extraction failed for file %s", file_name)
                return {"status": "failed", "file_name": file_name, "reason": str(exc)}

        if mapping_file_id is not None:
            await run_uc_mapping_for_file(AsyncSessionLocal, mapping_file_id)
        return out


async def _execute_extraction_job(
    job_id: str,
    folder_id: int,
    institution_id: int,
    *,
    force_reextract: bool = False,
    selected_file_ids: list[int] | None = None,
) -> None:
    """
    Race-safe background extraction job.

    Normal upload flow:
      1. classify the settled raw inbox batch;
      2. group Others;
      3. re-list the CURRENT classified transcript tree;
      4. extract each pending PDF exactly once.

    Selected re-extraction:
      - never classifies/moves raw inbox objects;
      - never runs term-wide Others grouping;
      - extracts only the selected ExtractionFileDetails IDs;
      - never pre-deletes existing transcript rows.
    """
    try:
        resolved_program_id = None

        async with AsyncSessionLocal() as session:
            folder = (
                await session.execute(
                    select(CloudFileLocation).where(
                        CloudFileLocation.id == folder_id,
                        CloudFileLocation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()

            if not folder:
                extraction_job_service.finish_job(
                    job_id,
                    status="failed",
                    error="Folder not found",
                )
                return

            if folder.institution_id != institution_id:
                extraction_job_service.finish_job(
                    job_id,
                    status="failed",
                    error="Not allowed to extract this folder",
                )
                return

            folder_year_intake = str(folder.year_intake or "")

            selected_rows: list[ExtractionFileDetails] = []
            if selected_file_ids is not None:
                normalized_ids = sorted(
                    {
                        int(file_id)
                        for file_id in selected_file_ids
                        if int(file_id) > 0
                    }
                )
                if not normalized_ids:
                    extraction_job_service.finish_job(
                        job_id,
                        status="failed",
                        error="No transcript files were selected.",
                    )
                    return

                selected_rows = (
                    await session.execute(
                        select(ExtractionFileDetails)
                        .where(
                            ExtractionFileDetails.id.in_(normalized_ids),
                            ExtractionFileDetails.institution_id
                            == institution_id,
                            ExtractionFileDetails.year_intake
                            == folder_year_intake,
                        )
                        .order_by(ExtractionFileDetails.id.asc())
                    )
                ).scalars().all()

                found_ids = {int(row.id) for row in selected_rows}
                missing_ids = [
                    file_id
                    for file_id in normalized_ids
                    if file_id not in found_ids
                ]
                if missing_ids:
                    extraction_job_service.finish_job(
                        job_id,
                        status="failed",
                        error=(
                            "Some selected transcript IDs do not belong to "
                            f"{folder_year_intake}: {missing_ids}"
                        ),
                    )
                    return

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

        storage = CloudStorageService()
        bucket_name = await asyncio.to_thread(storage.ensure_bucket)
        classified_root = storage.get_classified_root_prefix()
        transcript_prefix = (
            f"{classified_root}/{folder_year_intake}/transcript/"
        )

        extract_sem = asyncio.Semaphore(
            int(os.environ.get("EXTRACTION_CONCURRENCY", "6"))
        )

        # --------------------------------------------------------------
        # Selected transcript rerun: no classification, no grouping.
        # --------------------------------------------------------------
        if selected_file_ids is not None:
            selected_names = {str(row.file_name) for row in selected_rows}
            extraction_job_service.mark_started(job_id, len(selected_names))

            current_files = await asyncio.to_thread(
                storage.list_files,
                bucket_name,
                transcript_prefix,
            )
            current_candidates = [
                item
                for item in current_files
                if _is_extractable_classified_pdf(item)
                and PurePosixPath(
                    str(item.get("path") or item.get("name") or "")
                ).name
                in selected_names
            ]

            by_name: dict[str, list[dict]] = {}
            for item in current_candidates:
                name = PurePosixPath(
                    str(item.get("path") or item.get("name") or "")
                ).name
                by_name.setdefault(name, []).append(item)

            candidates: list[dict] = []
            already_counted: set[str] = set()

            for file_name in sorted(selected_names):
                matches = by_name.get(file_name, [])
                if len(matches) == 1:
                    candidates.append(matches[0])
                    continue

                if len(matches) == 0:
                    extraction_job_service.record_result(
                        job_id,
                        "failed",
                        {
                            "file_name": file_name,
                            "status": "failed",
                            "reason": (
                                "Selected transcript is not present in the "
                                "current classified GCS tree."
                            ),
                        },
                    )
                    already_counted.add(file_name)
                    continue

                extraction_job_service.record_result(
                    job_id,
                    "failed",
                    {
                        "file_name": file_name,
                        "status": "failed",
                        "reason": (
                            "Multiple classified GCS objects have this file "
                            "name; refusing to choose the wrong transcript."
                        ),
                    },
                )
                already_counted.add(file_name)

            tasks = [
                _extract_one_file(
                    item,
                    institution_id,
                    folder_year_intake,
                    bucket_name,
                    processor,
                    resolved_program_id,
                    extract_sem,
                    storage,
                    job_id,
                    force_reextract=force_reextract,
                )
                for item in candidates
            ]

            for coro in asyncio.as_completed(tasks):
                result = await coro
                file_name = result.get("file_name", "unknown")
                if file_name in already_counted:
                    continue
                already_counted.add(file_name)
                extraction_job_service.set_current_file(job_id, file_name)
                status = result.get("status")
                if status == "processed":
                    extraction_job_service.record_result(
                        job_id,
                        "processed",
                        {
                            "file_name": file_name,
                            "status": "processed",
                            "students": result.get("students", 0),
                            "courses": result.get("courses", 0),
                            "mode": result.get("mode"),
                            "process_status": result.get("process_status"),
                            "review_bucket": result.get("review_bucket"),
                        },
                    )
                elif status == "skipped":
                    extraction_job_service.record_result(
                        job_id,
                        "skipped",
                        {
                            "file_name": file_name,
                            "status": "skipped",
                            "reason": result.get("reason", ""),
                        },
                    )
                else:
                    extraction_job_service.record_result(
                        job_id,
                        "failed",
                        {
                            "file_name": file_name,
                            "status": "failed",
                            "reason": result.get("reason", ""),
                        },
                    )

            final_job = extraction_job_service.get_job(
                job_id,
                institution_id,
            )
            if final_job is None or final_job.get("status") == "cancelled":
                return

            extraction_job_service.finish_job(
                job_id,
                status=(
                    "completed_with_errors"
                    if final_job.get("failed_files", 0) > 0
                    else "completed"
                ),
            )
            return

        # --------------------------------------------------------------
        # Normal upload/automatic extraction.
        # --------------------------------------------------------------
        from google.cloud import documentai_v1 as documentai

        binary_client = documentai.DocumentProcessorServiceClient()
        layout_client = documentai.DocumentProcessorServiceClient()
        ocr_client = documentai.DocumentProcessorServiceClient()

        inbox_prefix = f"{GCS_INPUT_PREFIX}{folder_year_intake}/"
        inbox_blobs = await asyncio.to_thread(
            gcs_list_pdfs,
            GCS_BUCKET,
            inbox_prefix,
        )

        current_files_before = await asyncio.to_thread(
            storage.list_files,
            bucket_name,
            transcript_prefix,
        )
        current_classified_before = [
            item
            for item in current_files_before
            if _is_extractable_classified_pdf(item)
        ]

        # Keep only classified PDFs that are not already protected.
        classified_names = {
            PurePosixPath(
                str(item.get("path") or item.get("name") or "")
            ).name
            for item in current_classified_before
        }
        protected_names: set[str] = set()
        if classified_names:
            async with AsyncSessionLocal() as status_session:
                status_rows = (
                    await status_session.execute(
                        select(
                            ExtractionFileDetails.file_name,
                            ExtractionFileDetails.process_status,
                            ExtractionFileDetails.id,
                        )
                        .where(
                            ExtractionFileDetails.institution_id
                            == institution_id,
                            ExtractionFileDetails.year_intake
                            == folder_year_intake,
                            ExtractionFileDetails.file_name.in_(
                                classified_names
                            ),
                            ExtractionFileDetails.program_id
                            == resolved_program_id,
                        )
                        .order_by(ExtractionFileDetails.id.desc())
                    )
                ).all()

            latest_status: dict[str, str | None] = {}
            for file_name, status, _row_id in status_rows:
                latest_status.setdefault(str(file_name), status)

            protected_names = {
                file_name
                for file_name, status in latest_status.items()
                if status in ALREADY_EXTRACTED_STATUSES
            }

        pending_names = {
            PurePosixPath(blob_name).name for blob_name in inbox_blobs
        }
        pending_names.update(
            name for name in classified_names if name not in protected_names
        )

        extraction_job_service.mark_started(job_id, len(pending_names))
        if not pending_names:
            extraction_job_service.finish_job(job_id, status="completed")
            return

        classify_sem = asyncio.Semaphore(
            int(os.environ.get("CLASSIFY_CONCURRENCY", "10"))
        )
        finalized_names: set[str] = set()
        needs_grouping_names: set[str] = set()

        async def _classify_named(blob_name: str) -> dict:
            try:
                return await _classify_one(
                    blob_name,
                    institution_id,
                    folder_year_intake,
                    binary_client,
                    layout_client,
                    ocr_client,
                    resolved_program_id,
                    classify_sem,
                    job_id,
                )
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "failed",
                    "file_name": PurePosixPath(blob_name).name,
                    "reason": str(exc),
                    "stage": "classify",
                }

        classify_tasks = [
            _classify_named(blob_name) for blob_name in inbox_blobs
        ]

        for coro in asyncio.as_completed(classify_tasks):
            result = await coro
            file_name = result.get("file_name", "unknown")
            extraction_job_service.set_current_file(job_id, file_name)
            status = result.get("status")

            if status in {"classified", "classification_race_resolved"}:
                # No counter yet. Phase 2 finds the current path and records the
                # transcript once, after extraction actually finishes.
                continue

            if status == "needs_ai_extractor":
                needs_grouping_names.add(file_name)
                continue

            finalized_names.add(file_name)
            if status == "skipped":
                extraction_job_service.record_result(
                    job_id,
                    "skipped",
                    {
                        "file_name": file_name,
                        "status": "skipped",
                        "reason": result.get("reason", ""),
                    },
                )
            else:
                extraction_job_service.record_result(
                    job_id,
                    "failed",
                    {
                        "file_name": file_name,
                        "status": "failed",
                        "reason": result.get("reason", ""),
                        "stage": result.get("stage"),
                    },
                )

        # One grouping pass only, after ALL raw classification has settled.
        try:
            await asyncio.to_thread(
                cluster_and_group_others_gcs,
                folder_year_intake,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clustering failed (non-fatal): %s", exc)

        # Critical stale-path fix: NEVER use classification destination paths.
        # Re-list the current tree after every mover (classification/grouping)
        # has finished, and extract only these fresh paths.
        current_files_after: list[dict] = []
        for attempt in range(3):
            current_files_after = await asyncio.to_thread(
                storage.list_files,
                bucket_name,
                transcript_prefix,
            )
            current_names_after = {
                PurePosixPath(
                    str(item.get("path") or item.get("name") or "")
                ).name
                for item in current_files_after
                if _is_extractable_classified_pdf(item)
            }
            unresolved = (
                pending_names - finalized_names - current_names_after
            )
            if not unresolved:
                break
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))

        by_name: dict[str, list[dict]] = {}
        for item in current_files_after:
            if not _is_extractable_classified_pdf(item):
                continue
            file_name = PurePosixPath(
                str(item.get("path") or item.get("name") or "")
            ).name
            if file_name not in pending_names or file_name in finalized_names:
                continue
            by_name.setdefault(file_name, []).append(item)

        extraction_candidates: list[dict] = []
        for file_name in sorted(pending_names - finalized_names):
            matches = by_name.get(file_name, [])
            if len(matches) == 1:
                extraction_candidates.append(matches[0])
                continue

            finalized_names.add(file_name)
            if len(matches) == 0:
                extraction_job_service.record_result(
                    job_id,
                    "failed",
                    {
                        "file_name": file_name,
                        "status": "failed",
                        "reason": (
                            "Classification finished, but the PDF was not found "
                            "in the refreshed classified transcript tree."
                        ),
                    },
                )
            else:
                extraction_job_service.record_result(
                    job_id,
                    "failed",
                    {
                        "file_name": file_name,
                        "status": "failed",
                        "reason": (
                            "Multiple current classified objects share this "
                            "file name; extraction was stopped for safety."
                        ),
                    },
                )

        known_transcript_processed = False
        extract_tasks = [
            _extract_one_file(
                item,
                institution_id,
                folder_year_intake,
                bucket_name,
                processor,
                resolved_program_id,
                extract_sem,
                storage,
                job_id,
            )
            for item in extraction_candidates
        ]

        for coro in asyncio.as_completed(extract_tasks):
            try:
                result = await coro
            except Exception as exc:  # noqa: BLE001
                extraction_job_service.record_result(
                    job_id,
                    "failed",
                    {
                        "file_name": "unknown",
                        "status": "failed",
                        "reason": str(exc),
                    },
                )
                continue

            file_name = result.get("file_name", "unknown")
            if file_name in finalized_names:
                continue
            finalized_names.add(file_name)
            extraction_job_service.set_current_file(job_id, file_name)
            status = result.get("status")

            if status == "processed":
                if not result.get("is_new_transcript_type", False):
                    known_transcript_processed = True
                extraction_job_service.record_result(
                    job_id,
                    "processed",
                    {
                        "file_name": file_name,
                        "status": "processed",
                        "students": result.get("students", 0),
                        "courses": result.get("courses", 0),
                        "mode": result.get("mode"),
                        "process_status": result.get("process_status"),
                        "review_bucket": result.get("review_bucket"),
                    },
                )
            elif status == "skipped":
                extraction_job_service.record_result(
                    job_id,
                    "skipped",
                    {
                        "file_name": file_name,
                        "status": "skipped",
                        "reason": result.get("reason", ""),
                    },
                )
            else:
                extraction_job_service.record_result(
                    job_id,
                    "failed",
                    {
                        "file_name": file_name,
                        "status": "failed",
                        "reason": result.get("reason", ""),
                    },
                )

        final_job = extraction_job_service.get_job(
            job_id,
            institution_id,
        )
        if final_job is None or final_job.get("status") == "cancelled":
            return

        extraction_job_service.finish_job(
            job_id,
            status=(
                "completed_with_errors"
                if final_job.get("failed_files", 0) > 0
                else "completed"
            ),
        )

        if known_transcript_processed:
            try:
                schedule_uc_mapping_bg_task(str(uuid_lib.uuid4()))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to schedule UC mapping retry sweep for job %s",
                    job_id,
                )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Cloud folder extraction job %s crashed", job_id)
        state = extraction_job_service.get_job(job_id, institution_id)
        if state and state.get("status") == "cancelled":
            return
        extraction_job_service.finish_job(
            job_id,
            status="failed",
            error=str(exc),
        )


@router.get("", response_model=list[CloudFolderOut])
async def list_folders(
    year_intake: str | None = None,
    current_user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(CloudFileLocation)
    # scope to the current user's institution only
    inst_id = getattr(current_user, 'institution_id', None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail='No institution linked to user')
    q = q.where(CloudFileLocation.institution_id == inst_id, CloudFileLocation.deleted_at.is_(None))
    if year_intake:
        q = q.where(CloudFileLocation.year_intake == year_intake)

    rows = (await session.execute(q)).scalars().all()
    out = []
    for r in rows:
        out.append(
            CloudFolderOut(
                id=int(r.id),
                label=r.label,
                year_intake=str(r.year_intake) if r.year_intake is not None else '',
                last_polled=r.last_polled,
                updated_at=r.updated_at,
            )
        )
    return out


@router.get("/{folder_id}/files", response_model=list[CloudFolderNodeOut])
async def list_folder_files(
    folder_id: int,
    path: str | None = None,
    library: str = "auto",  # raw -> 01 (uploads), classified -> 02 (school-wise), auto -> raw then fallback to classified
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail="Not allowed to view this folder")

    # DB-driven explorer: derive folders/files from stored paths for this term/institution
    db_files = (
        await session.execute(
            select(ExtractionFileDetails.file_name, ExtractionFileDetails.upload_date)
            .where(
                ExtractionFileDetails.institution_id == folder.institution_id,
                ExtractionFileDetails.year_intake == folder.year_intake,
            )
            .order_by(ExtractionFileDetails.upload_date.asc())
        )
    ).all()

    normalized_path = (path or "").strip().strip("/")
    # collect basenames that exist in nested paths to suppress root duplicates
    nested_basenames = {
        fn.split("/")[-1]
        for fn, _ in db_files
        if "/" in str(fn)
    }
    folders: set[str] = set()
    files: list[dict] = []

    for file_name, ts in db_files:
        name_str = str(file_name)
        if not name_str.lower().endswith(".pdf"):
            continue
        parts = name_str.split("/")
        if normalized_path:
            prefix_parts = normalized_path.split("/")
            if parts[: len(prefix_parts)] != prefix_parts:
                continue
            parts = parts[len(prefix_parts) :]
        if not parts:
            continue
        if len(parts) == 1:
            # skip root duplicate if a nested version exists
            if not normalized_path and parts[0] in nested_basenames:
                continue
            files.append(
                {
                    "name": parts[0],
                    "path": f"{normalized_path}/{parts[0]}" if normalized_path else parts[0],
                    "size_bytes": None,
                    "updated_at": ts,
                }
            )
        else:
            folders.add(parts[0])

    listing = {
        "folders": sorted(folders),
        "files": sorted(files, key=lambda f: (f.get("updated_at") is None, f["name"])),
    }

    out: list[CloudFolderNodeOut] = []
    # Ensure standard school folders appear under transcript even if empty (classified view)
    if (path or "").strip("/").lower() == "transcript":
        standard = ["LBUSD", "Mayfair_High_School", "St_Anthony_High_School", "Others"]
        missing = [s for s in standard if s not in listing["folders"]]
        listing["folders"].extend(missing)

    for f in sorted(set(listing["folders"])):
        full_path = f"{path.rstrip('/')+'/' if path else ''}{f}"
        out.append(CloudFolderNodeOut(name=f, path=full_path, kind="folder"))
    for file in listing["files"]:
        out.append(CloudFolderNodeOut(kind="file", **file))
    return out


async def _poll_gcs_source(folder: CloudFileLocation, source_uri: str, storage: CloudStorageService) -> dict:
    from google.cloud import storage as gcs

    bucket, prefix = _parse_gs_uri(source_uri)
    client = gcs.Client()
    dest_bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    dest_prefix = storage.build_upload_prefix(folder.year_intake, None).strip("/")
    if dest_prefix and not dest_prefix.endswith("/"):
        dest_prefix = f"{dest_prefix}/"
    # make sure destination prefix exists
    await asyncio.to_thread(storage.ensure_prefix, dest_bucket_name, dest_prefix)

    copied = 0
    skipped = 0
    source_iter = client.list_blobs(bucket, prefix=prefix.strip("/"), delimiter=None)
    dest_bucket = client.bucket(dest_bucket_name)
    for blob in source_iter:
        if blob.name.endswith("/"):
            continue
        rel_path = blob.name[len(prefix):].lstrip("/") if prefix else blob.name
        dest_name = f"{dest_prefix}{rel_path}"
        try:
            await asyncio.to_thread(client.copy_blob, blob, dest_bucket, new_name=dest_name)
            copied += 1
        except Exception:
            skipped += 1
            logger.exception("Failed to copy %s to %s", blob.name, dest_name)
    return {"copied": copied, "skipped": skipped, "source_bucket": bucket, "source_prefix": prefix, "dest_bucket": dest_bucket_name, "dest_prefix": dest_prefix}


@router.post("", response_model=CloudFolderOut)
async def create_folder(
    payload: CloudFolderCreate,
    current_user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Use current user's institution
    inst_id = getattr(current_user, 'institution_id', None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail='User not linked to an institution')

    # Prevent duplicate term entries for same institution/program
    existing_q = select(CloudFileLocation).where(
        CloudFileLocation.institution_id == inst_id,
        CloudFileLocation.year_intake == payload.year_intake,
        CloudFileLocation.is_active.is_(True),
        CloudFileLocation.deleted_at.is_(None),
    )
    existing = (await session.execute(existing_q)).scalar_one_or_none()
    if existing:
        # Return existing mapping; create any missing GCS prefixes in background
        storage = CloudStorageService()
        # Run potentially blocking GCS ops in a background thread so the request
        # returns promptly even if the cloud call is slow or misconfigured.
        asyncio.create_task(
            asyncio.to_thread(
                storage.ensure_term_and_course_prefixes,
                inst_id,
                payload.year_intake,
                None,
                payload.courses or [],
            )
        )
        return CloudFolderOut(
            id=int(existing.id),
            label=existing.label,
            year_intake=str(existing.year_intake) if existing.year_intake is not None else '',
            last_polled=existing.last_polled,
            updated_at=existing.updated_at,
        )

    folder = CloudFileLocation(
        label=payload.label.strip(),
        year_intake=payload.year_intake,
        sync_status="unsynced",
        program_name=None,
        institution_id=inst_id,
        updated_by_user_id=current_user.id,
        is_active=True,
    )

    session.add(folder)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(existing_q)
        ).scalar_one_or_none()
        if existing:
            return CloudFolderOut(
                id=int(existing.id),
                label=existing.label,
                year_intake=str(existing.year_intake) if existing.year_intake is not None else '',
                last_polled=existing.last_polled,
                updated_at=existing.updated_at,
            )
        raise
    await session.refresh(folder)

    # NOTE: do NOT create ProgramCriteria rows here. Programs should be created
    # explicitly via the Program Criteria API so users can add prerequisites
    # in the UI before any GCS resources are provisioned.

    # create bucket & prefixes in GCS for term and courses in background
    storage = CloudStorageService()
    asyncio.create_task(
        asyncio.to_thread(
            storage.ensure_term_and_course_prefixes,
            inst_id,
            payload.year_intake,
            None,
            payload.courses or [],
        )
    )

    return CloudFolderOut(
        id=int(folder.id),
        label=folder.label,
        year_intake=str(folder.year_intake) if folder.year_intake is not None else '',
        last_polled=None,
        updated_at=folder.updated_at,
    )


@router.post("/{folder_id}/poll", response_model=CloudFolderOut)
async def poll_folder(
    folder_id: int,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    raise HTTPException(status_code=400, detail="Polling is disabled")


@router.post("/{folder_id}/extract-jobs", response_model=FolderExtractionJobOut)
async def start_extract_folder_job(
    folder_id: int,
    payload: FolderExtractionJobStart | None = None,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(
            status_code=403,
            detail="Not allowed to extract this folder",
        )

    request = payload or FolderExtractionJobStart()
    selected_file_ids = None
    if request.selected_file_ids is not None:
        selected_file_ids = sorted(
            {
                int(file_id)
                for file_id in request.selected_file_ids
                if int(file_id) > 0
            }
        )
        if not selected_file_ids:
            raise HTTPException(
                status_code=400,
                detail="Select at least one transcript to re-extract.",
            )

        selected_rows = (
            await session.execute(
                select(ExtractionFileDetails.id).where(
                    ExtractionFileDetails.id.in_(selected_file_ids),
                    ExtractionFileDetails.institution_id == inst_id,
                    ExtractionFileDetails.year_intake == folder.year_intake,
                )
            )
        ).scalars().all()
        found_ids = {int(file_id) for file_id in selected_rows}
        missing_ids = [
            file_id
            for file_id in selected_file_ids
            if file_id not in found_ids
        ]
        if missing_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Some selected transcripts do not belong to the current "
                    f"term: {missing_ids}"
                ),
            )

    job, created = extraction_job_service.create_or_get_active_job(
        folder_id=folder_id,
        institution_id=inst_id,
        folder_label=folder.label,
        program_name=None,
        year_intake=folder.year_intake,
    )

    if not created and selected_file_ids is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "An extraction job is already running for this term. "
                "Stop it or wait for it to finish before re-extracting selected transcripts."
            ),
        )

    if created:
        asyncio.create_task(
            _execute_extraction_job(
                job["id"],
                folder_id,
                inst_id,
                force_reextract=bool(request.force_reextract),
                selected_file_ids=selected_file_ids,
            )
        )

    return _job_response(job)


@router.get(
    "/extract-jobs/active",
    response_model=list[FolderExtractionJobOut],
)
async def list_active_extract_folder_jobs(
    current_user=Depends(get_current_user),
):
    """Read-only discovery for backend-created automatic extraction jobs."""
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(
            status_code=403,
            detail="No institution linked to user",
        )

    jobs = extraction_job_service.get_active_jobs(inst_id)
    return [_job_response(job) for job in jobs]


@router.get("/extract-jobs/{job_id}", response_model=FolderExtractionJobOut)
async def get_extract_folder_job(
    job_id: str,
    current_user=Depends(get_current_user),
):
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail="No institution linked to user")

    job = extraction_job_service.get_job(job_id, inst_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    return _job_response(job)


@router.post("/extract-jobs/{job_id}/cancel", response_model=FolderExtractionJobOut)
async def cancel_extract_folder_job(
    job_id: str,
    current_user=Depends(get_current_user),
):
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None:
        raise HTTPException(status_code=403, detail="No institution linked to user")

    job = extraction_job_service.cancel_job(job_id, inst_id, reason="Cancelled by user")
    if job is None:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    return _job_response(job)


@router.post("/{folder_id}/extract", response_model=FolderExtractionOut)
async def extract_folder(
    folder_id: int,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail="Not allowed to extract this folder")

    folder_year_intake = folder.year_intake
    resolved_program_id = None

    project_id = os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript")
    location = os.environ.get("DOC_AI_LOCATION", "us")
    default_processor_id = os.environ.get("DOC_AI_PROCESSOR", "4bf06de9ecadb866")
    processor = TranscriptProcessor(
        ProcessorConfig(project_id=project_id, location=location, processor_id=default_processor_id)
    )

    from google.cloud import documentai_v1 as documentai
    binary_client = documentai.DocumentProcessorServiceClient()
    layout_client = documentai.DocumentProcessorServiceClient()
    ocr_client = documentai.DocumentProcessorServiceClient()

    # List inbox files to pipeline-classify-and-extract
    inbox_prefix = f"{GCS_INPUT_PREFIX}{folder_year_intake}/"
    inbox_blobs = await asyncio.to_thread(gcs_list_pdfs, GCS_BUCKET, inbox_prefix)

    # List already-classified files.
    # Scan the ENTIRE transcript/ tree recursively so every classified school
    # folder is picked up ΓÇö including Others/Grouped_by_school/<school>/ where
    # the classifier places schools it could not map to a known district folder.
    # Previously only LBUSD/Mayfair/St_Anthony were scanned, so files grouped
    # under Others were created in the DB but never extracted (stuck "uploaded").
    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    classified_root = storage.get_classified_root_prefix()
    transcript_prefix = f"{classified_root}/{folder_year_intake}/transcript/"

    all_transcript_files = await asyncio.to_thread(
        storage.list_files, bucket_name, transcript_prefix
    )
    already_classified = [
        item for item in all_transcript_files if _is_extractable_classified_pdf(item)
    ]

    if not inbox_blobs and not already_classified:
        return FolderExtractionOut(ok=True, processed_files=0, skipped_files=0, failed_files=0, details=[])

    semaphore = asyncio.Semaphore(int(os.environ.get("EXTRACTION_CONCURRENCY", "24")))
    pipeline_tasks = [
        _classify_and_extract_one(
            blob_name, inst_id, folder_year_intake,
            binary_client, layout_client, ocr_client,
            processor, resolved_program_id, semaphore,
        )
        for blob_name in inbox_blobs
    ]
    extract_tasks = [
        _extract_one_file(item, inst_id, folder_year_intake, bucket_name, processor, resolved_program_id, semaphore, storage)
        for item in already_classified
    ]
    results = await asyncio.gather(*pipeline_tasks, *extract_tasks, return_exceptions=True)

    # Cluster Others after classification completes
    try:
        await asyncio.to_thread(cluster_and_group_others_gcs, folder_year_intake)
    except Exception as exc:
        logger.warning("Clustering failed (non-fatal): %s", exc)

    processed_files = 0
    skipped_files = 0
    failed_files = 0
    details: list[dict] = []

    for result in results:
        if isinstance(result, Exception):
            failed_files += 1
            details.append({"file_name": "unknown", "status": "failed", "reason": str(result)})
            continue
        details.append(result)
        status = result["status"]
        if status == "processed":
            processed_files += 1
        elif status == "skipped":
            skipped_files += 1
        else:
            failed_files += 1

    return FolderExtractionOut(
        ok=failed_files == 0,
        processed_files=processed_files,
        skipped_files=skipped_files,
        failed_files=failed_files,
        details=details,
    )





@router.put("/{folder_id}", response_model=CloudFolderOut)
async def update_folder(
    folder_id: int,
    payload: CloudFolderUpdate,
    session: AsyncSession = Depends(get_session),
):
    folder = (await session.execute(
        select(CloudFileLocation).where(CloudFileLocation.id == folder_id)
    )).scalar_one_or_none()


    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder.label = payload.label.strip()
    folder.year_intake = payload.year_intake

    await session.commit()
    await session.refresh(folder)

    return CloudFolderOut(
        id=int(folder.id),
        label=folder.label,
        year_intake=str(folder.year_intake),
        last_polled=folder.last_polled,
        updated_at=folder.updated_at,
    )


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: int,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None)  # ignore already deleted
        )
    )
    folder = result.scalar_one_or_none()

    if not folder:
        return {"ok": True}

    folder.deleted_at = datetime.utcnow()  #  soft delete
    folder.is_active = False
    await session.commit()

    return {"ok": True}



# --- Drive OAuth helpers ---


# Hold strong references to fire-and-forget auto-classify tasks. asyncio only
# keeps WEAK references to tasks, so a task with no other reference can be
# garbage-collected mid-run — which silently left uploaded files stuck in 01_
# (never classified into 02_). Keep them here until they finish.
_BACKGROUND_CLASSIFY_TASKS: set = set()


async def _auto_classify_uploaded_blob(blob_name: str) -> None:
    """
    Compatibility helper for explicit one-file classification.

    Normal uploads do not call this helper; they use the single debounced folder
    job so per-file classification cannot race the extraction job.
    """
    try:
        from google.cloud import documentai_v1 as documentai

        def _run() -> None:
            binary_client = documentai.DocumentProcessorServiceClient()
            layout_client = documentai.DocumentProcessorServiceClient()
            ocr_client = documentai.DocumentProcessorServiceClient()

            result = (
                classify_blob_pipeline(
                    blob_name,
                    binary_client,
                    layout_client,
                    ocr_client,
                )
                or {}
            )

            if result.get("ok"):
                try:
                    _rescue_known_transcript_destination(
                        pipeline_result=result,
                        file_name=PurePosixPath(blob_name).name,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Auto-classify rescue failed for %s",
                        blob_name,
                    )

        await asyncio.to_thread(_run)

    except Exception:  # noqa: BLE001
        logger.exception(
            "Auto-classify on upload failed for %s",
            blob_name,
        )


# Debounced per-folder classify+extract trigger. Every uploaded file rearms a
# short timer; after the batch settles exactly one folder job handles all movers.
# This intentionally replaces per-file auto-classification for normal uploads.
_EXTRACT_DEBOUNCE: dict[int, "asyncio.Task"] = {}
_EXTRACT_DEBOUNCE_SECONDS = float(
    os.environ.get("UPLOAD_EXTRACT_DEBOUNCE_SECONDS", "10")
)


def _schedule_folder_extraction(
    folder_id: int,
    institution_id: int,
    folder_label: str,
    year_intake: str | None,
) -> None:
    previous = _EXTRACT_DEBOUNCE.get(folder_id)
    if previous is not None and not previous.done():
        previous.cancel()

    async def _run() -> None:
        try:
            await asyncio.sleep(_EXTRACT_DEBOUNCE_SECONDS)
            job, created = extraction_job_service.create_or_get_active_job(
                folder_id=folder_id,
                institution_id=institution_id,
                folder_label=folder_label,
                program_name=None,
                year_intake=year_intake,
            )
            if created:
                await _execute_extraction_job(
                    job["id"],
                    folder_id,
                    institution_id,
                )
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception(
                "Debounced extraction for folder %s failed",
                folder_id,
            )
        finally:
            if _EXTRACT_DEBOUNCE.get(folder_id) is asyncio.current_task():
                _EXTRACT_DEBOUNCE.pop(folder_id, None)

    _EXTRACT_DEBOUNCE[folder_id] = asyncio.create_task(_run())


# Debounced, per-folder classify+extract trigger. Every uploaded file (re)arms a
# short timer; when uploads stop, exactly ONE extraction job runs for the folder.
# This is the SINGLE classify+extract path — there is no per-file auto-classify
# racing the job, so a file can never be caught half-moved and left unextracted —
# and it's backend-driven, so extraction happens even if the browser never fires
# it. create_or_get_active_job dedups, so this is safe alongside the immediate
# frontend trigger (whichever wins, the other is a no-op).
_EXTRACT_DEBOUNCE: dict[int, "asyncio.Task"] = {}
_EXTRACT_DEBOUNCE_SECONDS = float(os.environ.get("UPLOAD_EXTRACT_DEBOUNCE_SECONDS", "10"))


def _schedule_folder_extraction(
    folder_id: int, institution_id: int, folder_label: str, year_intake: str | None
) -> None:
    prev = _EXTRACT_DEBOUNCE.get(folder_id)
    if prev is not None and not prev.done():
        prev.cancel()

    async def _run() -> None:
        try:
            await asyncio.sleep(_EXTRACT_DEBOUNCE_SECONDS)
            job, created = extraction_job_service.create_or_get_active_job(
                folder_id=folder_id,
                institution_id=institution_id,
                folder_label=folder_label,
                program_name=None,
                year_intake=year_intake,
            )
            if created:
                await _execute_extraction_job(job["id"], folder_id, institution_id)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("Debounced extraction for folder %s failed", folder_id)
        finally:
            if _EXTRACT_DEBOUNCE.get(folder_id) is asyncio.current_task():
                _EXTRACT_DEBOUNCE.pop(folder_id, None)

    _EXTRACT_DEBOUNCE[folder_id] = asyncio.create_task(_run())


@router.post("/{folder_id}/upload")
async def upload_transcript(
    folder_id: int,
    file: UploadFile = File(...),
    course: str | None = Form(None),
    current_user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Upload a transcript file into the term/program/course folder in GCS.

    - Validates that the folder belongs to the current user's institution.
    - Uploads the file to the institution bucket under <year>/<program>/<course>/filename
    - Creates an ExtractionFileDetails row linking to the institution and file name
    """
    # lookup folder
    res = await session.execute(select(CloudFileLocation).where(CloudFileLocation.id == folder_id))
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail='Folder not found')

    inst_id = getattr(current_user, 'institution_id', None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail='Not allowed to upload to this folder')

    # Determine prefix and bucket
    storage = CloudStorageService()
    # Run blocking GCS operations in a thread to avoid blocking the async event loop.
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    year_intake = folder.year_intake
    prefix = storage.build_upload_prefix(year_intake, None, course)

    # ensure prefix exists (thread)
    await asyncio.to_thread(storage.ensure_prefix, bucket_name, prefix)

    # Read the whole file into memory once so we can retry the GCS upload
    # without a consumed/again-unreadable stream.
    try:
        file.file.seek(0)
    except Exception:
        pass
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail=f"Uploaded file '{file.filename}' is empty")

    blob_name = prefix + file.filename
    bucket = storage.client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    content_type = file.content_type or 'application/pdf'

    # Retry the GCS upload up to 3 times so a transient blip does not silently
    # drop the file (this is what caused "27 selected, only 23 uploaded").
    last_exc = None
    for attempt in range(1, 4):
        try:
            await asyncio.to_thread(
                blob.upload_from_string, file_bytes, content_type=content_type
            )
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Upload attempt %d failed for %s: %s", attempt, file.filename, exc)
            if attempt < 3:
                await asyncio.sleep(0.5 * attempt)

    if last_exc is not None:
        logger.exception("All upload attempts failed for %s", file.filename)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to upload '{file.filename}' to storage after 3 attempts: {last_exc}",
        )

    # Record extraction file detail
    ef = ExtractionFileDetails(
        file_name=file.filename,
        process_status='uploaded',
        institution_id=inst_id,
        year_intake=folder.year_intake,
    )

    session.add(ef)
    await session.commit()
    await session.refresh(ef)

    # One debounced folder job owns classification + grouping + extraction.
    # Do NOT start a second per-file classifier here: that was the source of the
    # 01_Inbox stale-path 404 race.
    try:
        _schedule_folder_extraction(
            int(folder.id),
            int(inst_id),
            str(folder.label),
            str(folder.year_intake) if folder.year_intake is not None else None,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to schedule extraction for folder %s",
            folder.id,
        )

    return {
        'ok': True,
        'bucket': bucket_name,
        'object': blob_name,
        'extraction_file_id': ef.id,
    }


@router.get("/{folder_id}/file")
async def view_folder_file(
    folder_id: int,
    name: str,
    current_user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Stream an uploaded transcript for preview by its file name. Classification
    moves files from 01_ to 02_, so we look in both and return the first match."""
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail="Not allowed to view this folder")

    term = folder.year_intake or ""
    base = PurePosixPath(name).name
    storage = CloudStorageService()
    bucket_name = storage.get_bucket_name()
    client = storage.client
    roots = [
        f"{GCS_INPUT_PREFIX}{term}/",
        f"02_Library_Categorized_HS_Transcripts/{term}/",
    ]
    for root in roots:
        for b in client.list_blobs(bucket_name, prefix=root):
            n = b.name
            if n.lower().endswith(".pdf") and PurePosixPath(n).name == base:
                from app.routers.transcript_detector import stream_pdf
                return stream_pdf(n)
    raise HTTPException(status_code=404, detail="File not found in GCS.")


class DeleteObjectsPayload(BaseModel):
    objects: list[str]

class DeleteFilePayload(BaseModel):
    path: str

class DeleteFolderPayload(BaseModel):
    path: str

@router.post("/{folder_id}/delete-objects")
async def delete_objects(
    folder_id: int,
    payload: DeleteObjectsPayload,
    current_user = Depends(get_current_user),
):
    # Validate folder and institution
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(CloudFileLocation).where(
                CloudFileLocation.id == folder_id,
                CloudFileLocation.deleted_at.is_(None),
            )
        )
        folder = res.scalar_one_or_none()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        inst_id = getattr(current_user, 'institution_id', None)
        if inst_id is None or inst_id != folder.institution_id:
            raise HTTPException(status_code=403, detail="Not allowed to modify this folder")

    objects = [o.lstrip("/") for o in payload.objects if o]
    if not objects:
        return {"deleted": 0}

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    bucket = storage.client.bucket(bucket_name)

    deleted = 0
    for obj in objects:
        try:
            blob = bucket.blob(obj)
            await asyncio.to_thread(blob.delete)
            deleted += 1
        except Exception:
            logger.exception("Failed to delete object %s during rollback", obj)
            continue

    return {"deleted": deleted}


@router.post("/{folder_id}/delete-file")
async def delete_file(
    folder_id: int,
    payload: DeleteFilePayload,
    current_user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a single file from GCS (raw + classified) and remove its DB records."""
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail="Not allowed to modify this folder")

    path = (payload.path or "").lstrip("/")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    bucket = storage.client.bucket(bucket_name)
    filename = path.split("/")[-1]

    # Build candidate keys: exact raw path, plus any blobs under the classified prefix
    # that match the filename (classified files live in subdirectories we can't predict).
    raw_prefix = storage.build_upload_prefix(folder.year_intake, None, None)
    classified_prefix = storage.build_classified_upload_prefix(folder.year_intake, None)

    candidate_keys: set[str] = set()
    candidate_keys.add(path)
    candidate_keys.add(f"{raw_prefix.rstrip('/')}/{filename}")

    # Scan classified prefix for the filename ΓÇö it may be nested under a classifier subdir
    def _find_classified_blobs():
        return [
            b.name for b in bucket.list_blobs(prefix=classified_prefix)
            if b.name.endswith(f"/{filename}") or b.name == filename
        ]

    for key in await asyncio.to_thread(_find_classified_blobs):
        candidate_keys.add(key)

    deleted_objects = 0
    for obj_key in candidate_keys:
        blob = bucket.blob(obj_key)
        try:
            if await asyncio.to_thread(blob.exists, storage.client):
                await asyncio.to_thread(blob.delete)
                deleted_objects += 1
        except Exception:
            logger.exception("Failed to delete object %s", obj_key)

    # delete DB rows for this file name (cascades remove students/courses)
    filename = path.split("/")[-1]
    candidates = {filename, path}
    rows = (
        await session.execute(
            select(ExtractionFileDetails).where(
                ExtractionFileDetails.institution_id == folder.institution_id,
                ExtractionFileDetails.year_intake == folder.year_intake,
                ExtractionFileDetails.file_name.in_(list(candidates)),
            )
        )
    ).scalars().all()
    deleted_records = 0
    for row in rows:
        await session.delete(row)
        deleted_records += 1
    if deleted_records:
        await session.commit()

    return {"deleted_objects": deleted_objects, "deleted_records": deleted_records}


@router.post("/{folder_id}/delete-folder")
async def delete_folder_path(
    folder_id: int,
    payload: DeleteFolderPayload,
    current_user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete all files under a folder path (within the term) from storage and DB."""
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail="Not allowed to modify this folder")

    path = (payload.path or "").strip().strip("/")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    client = storage.client

    prefixes = [
        storage.build_upload_prefix(folder.year_intake, None, None),
        storage.build_classified_upload_prefix(folder.year_intake, None),
    ]

    all_filenames: set[str] = set()
    all_fullpaths: set[str] = set()
    deleted_objects = 0

    for base_prefix in prefixes:
        base = base_prefix.strip("/")
        if base:
            base += "/"
        target_prefix = f"{base}{path}/"
        for blob in client.list_blobs(bucket_name, prefix=target_prefix):
            if blob.name.endswith("/"):
                continue
            fname = blob.name.split("/")[-1]
            rel_path = blob.name[len(base):] if blob.name.startswith(base) else blob.name
            all_filenames.add(fname)
            all_fullpaths.add(rel_path)
            try:
                await asyncio.to_thread(blob.delete)
                deleted_objects += 1
            except Exception:
                logger.exception("Failed to delete object %s", blob.name)

    if all_filenames or all_fullpaths:
        candidates = list(all_filenames | all_fullpaths)
        await session.execute(
            delete(ExtractionFileDetails).where(
                ExtractionFileDetails.institution_id == folder.institution_id,
                ExtractionFileDetails.year_intake == folder.year_intake,
                ExtractionFileDetails.file_name.in_(candidates),
            )
        )
        await session.commit()

    return {"deleted_objects": deleted_objects, "deleted_records": len(all_filenames | all_fullpaths)}


@router.delete("/{folder_id}/purge")
async def purge_folder(
    folder_id: int,
    current_user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Hard-delete a cloud folder: remove storage objects (raw + classified) and DB rows for its term."""
    res = await session.execute(
        select(CloudFileLocation).where(
            CloudFileLocation.id == folder_id,
            CloudFileLocation.deleted_at.is_(None),
        )
    )
    folder = res.scalar_one_or_none()
    if not folder:
        return {"ok": True, "deleted_objects": 0, "deleted_records": 0}

    inst_id = getattr(current_user, "institution_id", None)
    if inst_id is None or inst_id != folder.institution_id:
        raise HTTPException(status_code=403, detail="Not allowed to modify this folder")

    storage = CloudStorageService()
    bucket_name = await asyncio.to_thread(storage.ensure_bucket)
    client = storage.client
    prefixes = [
        storage.build_upload_prefix(folder.year_intake, None, None),
        storage.build_classified_upload_prefix(folder.year_intake, None),
    ]
    deleted_objects = 0
    for prefix in prefixes:
        normalized = prefix.strip("/")
        if normalized:
            normalized += "/"
        for blob in client.list_blobs(bucket_name, prefix=normalized):
            try:
                await asyncio.to_thread(blob.delete)
                deleted_objects += 1
            except Exception:
                logger.exception("Failed to delete object %s", blob.name)

    # delete extraction records for this term/institution (cascade removes students/courses)
    del_stmt = delete(ExtractionFileDetails).where(
        ExtractionFileDetails.institution_id == folder.institution_id,
        ExtractionFileDetails.year_intake == folder.year_intake,
    )
    result = await session.execute(del_stmt)
    deleted_records = result.rowcount or 0
    # hard delete folder row
    await session.delete(folder)
    await session.commit()

    return {"ok": True, "deleted_objects": deleted_objects, "deleted_records": deleted_records}
