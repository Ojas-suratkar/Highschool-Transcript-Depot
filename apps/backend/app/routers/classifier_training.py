from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func

from app.db import SessionLocal
from app.models import (
    TranscriptClassifierRoute,
    TranscriptSchoolType,
    TranscriptSchoolTypeSample,
)
from app.services.classifier_training_service import ClassifierTrainingService


router = APIRouter(prefix="/classifier-training", tags=["classifier-training"])
logger = logging.getLogger(__name__)

DEFAULT_REQUIRED_SAMPLE_COUNT = 10


class SchoolTypeSampleResponse(BaseModel):
    id: int
    file_name: str
    blob_name: str | None = None
    gcs_uri: str
    semester: str | None = None
    detected_school_name: str | None = None
    created_at: datetime | None = None


class SchoolTypeResponse(BaseModel):
    id: int
    display_name: str
    normalized_name: str | None = None
    classifier_label: str
    status: str
    sample_count: int
    required_sample_count: int
    cluster_confidence: float | None = None
    gcs_raw_prefix: str | None = None
    gcs_training_prefix: str | None = None
    document_ai_processor_id: str | None = None
    document_ai_processor_version_id: str | None = None
    import_operation_name: str | None = None
    training_operation_name: str | None = None
    deploy_operation_name: str | None = None
    extractor_profile: str | None = None
    error_message: str | None = None
    samples: list[SchoolTypeSampleResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RouteResponse(BaseModel):
    id: int
    classifier_label: str
    display_name: str
    extractor_profile: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ClassifierTrainingRunResponse(BaseModel):
    status: str
    result: dict[str, Any]
    school_type: SchoolTypeResponse | None = None


class MoveSchoolTypeToExistingResponse(BaseModel):
    status: str
    message: str
    school_type: SchoolTypeResponse
    route: RouteResponse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _blob_name_from_gcs_uri(gcs_uri: str | None) -> str | None:
    if not gcs_uri:
        return None

    prefix = "gs://"

    if not gcs_uri.startswith(prefix):
        return gcs_uri

    without_scheme = gcs_uri[len(prefix) :]
    parts = without_scheme.split("/", 1)

    if len(parts) != 2:
        return None

    return parts[1]


def _semester_from_blob_name(blob_name: str | None) -> str | None:
    if not blob_name:
        return None

    parts = PurePosixPath(blob_name).parts

    if len(parts) >= 2 and parts[0] == "02_Library_Categorized_HS_Transcripts":
        return parts[1]

    return None


def _file_name_from_blob_name(
    blob_name: str | None,
    fallback: str | None = None,
) -> str:
    if blob_name:
        return PurePosixPath(blob_name).name

    if fallback:
        return PurePosixPath(fallback).name

    return "Transcript"


def _serialize_sample(row: TranscriptSchoolTypeSample) -> SchoolTypeSampleResponse:
    gcs_uri = row.gcs_uri or row.source_file or ""
    blob_name = _blob_name_from_gcs_uri(gcs_uri)
    semester = row.cluster_id or _semester_from_blob_name(blob_name)

    return SchoolTypeSampleResponse(
        id=row.id,
        file_name=_file_name_from_blob_name(blob_name, gcs_uri),
        blob_name=blob_name,
        gcs_uri=gcs_uri,
        semester=semester,
        detected_school_name=row.detected_school_name,
        created_at=row.created_at,
    )


def _load_samples_by_school_type_ids(
    db,
    school_type_ids: list[int],
) -> dict[int, list[SchoolTypeSampleResponse]]:
    if not school_type_ids:
        return {}

    sample_rows = (
        db.query(TranscriptSchoolTypeSample)
        .filter(
            TranscriptSchoolTypeSample.school_type_id.in_(school_type_ids),
            TranscriptSchoolTypeSample.verified.is_(True),
        )
        .order_by(
            TranscriptSchoolTypeSample.school_type_id.asc(),
            TranscriptSchoolTypeSample.cluster_id.asc(),
            TranscriptSchoolTypeSample.created_at.asc(),
            TranscriptSchoolTypeSample.id.asc(),
        )
        .all()
    )

    grouped: dict[int, list[SchoolTypeSampleResponse]] = {}

    for sample_row in sample_rows:
        grouped.setdefault(sample_row.school_type_id, []).append(
            _serialize_sample(sample_row)
        )

    return grouped


def _serialize_school_type(
    row: TranscriptSchoolType,
    *,
    samples: list[SchoolTypeSampleResponse] | None = None,
) -> SchoolTypeResponse:
    return SchoolTypeResponse(
        id=row.id,
        display_name=row.display_name,
        normalized_name=getattr(row, "normalized_name", None),
        classifier_label=row.classifier_label,
        status=row.status,
        sample_count=row.sample_count or 0,
        required_sample_count=(
            row.required_sample_count or DEFAULT_REQUIRED_SAMPLE_COUNT
        ),
        cluster_confidence=row.cluster_confidence,
        gcs_raw_prefix=row.gcs_raw_prefix,
        gcs_training_prefix=row.gcs_training_prefix,
        document_ai_processor_id=row.document_ai_processor_id,
        document_ai_processor_version_id=row.document_ai_processor_version_id,
        import_operation_name=row.import_operation_name,
        training_operation_name=row.training_operation_name,
        deploy_operation_name=row.deploy_operation_name,
        extractor_profile=row.extractor_profile,
        error_message=row.error_message,
        samples=samples or [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _serialize_route(row: TranscriptClassifierRoute) -> RouteResponse:
    return RouteResponse(
        id=row.id,
        classifier_label=row.classifier_label,
        display_name=row.display_name,
        extractor_profile=row.extractor_profile,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _sync_gcs_grouped_folders_for_needs_setup() -> None:
    """
    Sync GCS grouped-school folders into transcript_school_types.

    This runs when Needs Setup opens so real clustering folders appear in DB.
    """
    try:
        from app.routers.transcript_detector import (
            GCS_BUCKET,
            read_grouped_school_folders_for_new_types,
        )
        from app.services.transcript_school_type_onboarding_service import (
            sync_grouped_school_folder,
        )

        grouped_result = read_grouped_school_folders_for_new_types()

        db = SessionLocal()
        try:
            total_folders = 0
            total_files = 0

            for semester_entry in grouped_result:
                file_semester = semester_entry.get("semester")
                folders = semester_entry.get("folders", [])

                for folder in folders:
                    folder_name = str(folder.get("folder_name", "")).strip()
                    files = folder.get("files", [])

                    if not folder_name:
                        continue

                    file_blob_names = [
                        str(file_item.get("blob_name", ""))
                        for file_item in files
                        if file_item.get("blob_name")
                    ]

                    if not file_blob_names:
                        continue

                    gcs_group_prefix = (
                        f"gs://{GCS_BUCKET}/"
                        "02_Library_Categorized_HS_Transcripts/"
                        f"{file_semester}/transcript/Others/Grouped_by_school/"
                        f"{folder_name}/"
                    )

                    sync_grouped_school_folder(
                        db,
                        folder_name=folder_name,
                        gcs_group_prefix=gcs_group_prefix,
                        file_blob_names=file_blob_names,
                        bucket_name=GCS_BUCKET,
                        semester=file_semester,
                    )

                    total_folders += 1
                    total_files += len(file_blob_names)

            db.commit()

            logger.info(
                "[CLASSIFIER_TRAINING] Synced grouped folders into Needs Setup. "
                "semesters=%s folders=%s files=%s",
                len(grouped_result),
                total_folders,
                total_files,
            )

        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "[CLASSIFIER_TRAINING] Failed to sync GCS grouped folders "
            "before listing school types."
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync grouped school folders into Needs Setup: {exc}",
        )


@router.get("/school-types/counts")
def school_type_counts() -> dict[str, int]:
    """Real per-page badge counts for the New Transcript Types sidebar.

    A single GROUP BY over transcript_school_types.status — deliberately does NOT
    run the GCS grouped-folder sync (that is heavy and belongs to the page load),
    so the sidebar can refresh cheaply. The three pages map to:
      - Needs Setup -> needs_setup
      - In Setup    -> in_setup + failed  (the In Setup page shows both)
      - Ready       -> ready
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(
                TranscriptSchoolType.status,
                func.count(TranscriptSchoolType.id),
            )
            .group_by(TranscriptSchoolType.status)
            .all()
        )
        by_status = {status: int(count) for status, count in rows}
        return {
            "needs_setup": by_status.get("needs_setup", 0),
            "in_setup": by_status.get("in_setup", 0) + by_status.get("failed", 0),
            "ready": by_status.get("ready", 0),
            "failed": by_status.get("failed", 0),
            "held": by_status.get("held", 0),
            "existing": by_status.get("existing", 0),
        }
    finally:
        db.close()


@router.get("/school-types", response_model=list[SchoolTypeResponse])
def list_school_types(
    status: str | None = Query(default=None),
) -> list[SchoolTypeResponse]:
    """
    Used by the app UI to show:
    - Needs Setup
    - In Setup
    - Ready
    - Failed
    """

    include_samples = status in {None, "needs_setup", "in_setup"}

    if status in {None, "needs_setup"}:
        _sync_gcs_grouped_folders_for_needs_setup()

    db = SessionLocal()
    try:
        query = db.query(TranscriptSchoolType)

        if status:
            query = query.filter(TranscriptSchoolType.status == status)

        rows = (
            query.order_by(
                TranscriptSchoolType.status.asc(),
                desc(TranscriptSchoolType.updated_at),
                desc(TranscriptSchoolType.id),
            )
            .all()
        )

        samples_by_school_type_id: dict[int, list[SchoolTypeSampleResponse]] = {}

        if include_samples:
            samples_by_school_type_id = _load_samples_by_school_type_ids(
                db,
                [row.id for row in rows],
            )

        return [
            _serialize_school_type(
                row,
                samples=samples_by_school_type_id.get(row.id, []),
            )
            for row in rows
        ]
    finally:
        db.close()


@router.get("/routes", response_model=list[RouteResponse])
def list_classifier_routes() -> list[RouteResponse]:
    """
    Shows active classifier label -> extractor profile mappings.
    Existing transcript types should have a row here.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(TranscriptClassifierRoute)
            .order_by(TranscriptClassifierRoute.display_name.asc())
            .all()
        )
        return [_serialize_route(row) for row in rows]
    finally:
        db.close()


@router.post("/run-ready", response_model=ClassifierTrainingRunResponse)
def run_ready_school_types() -> ClassifierTrainingRunResponse:
    """
    App-safe/manual action:
    Run setup for queued school types.

    This processes rows already marked in_setup.
    """
    db = SessionLocal()
    try:
        service = ClassifierTrainingService(db)
        result = service.promote_ready_school_types()
        return ClassifierTrainingRunResponse(
            status="ok",
            result=result,
            school_type=None,
        )
    finally:
        db.close()


@router.post(
    "/school-types/{school_type_id}/start",
    response_model=ClassifierTrainingRunResponse,
)
def start_school_type_setup(
    school_type_id: int,
) -> ClassifierTrainingRunResponse:
    """
    App button action.

    This should be fast:
      Needs Setup / Failed -> In Setup

    It does not run the full Document AI import/train/deploy synchronously.
    The worker/manual setup process should continue from in_setup.
    """
    db = SessionLocal()
    try:
        school_type = (
            db.query(TranscriptSchoolType)
            .filter(TranscriptSchoolType.id == school_type_id)
            .first()
        )

        if not school_type:
            raise HTTPException(status_code=404, detail="School type not found.")

        if school_type.status not in {"needs_setup", "failed"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    "School type is not startable. "
                    f"Current status: {school_type.status}"
                ),
            )

        required_count = (
            school_type.required_sample_count or DEFAULT_REQUIRED_SAMPLE_COUNT
        )

        if (school_type.sample_count or 0) < required_count:
            raise HTTPException(
                status_code=400,
                detail="School type does not have enough samples yet.",
            )

        # Important for Retry Classifier:
        # A failed row should restart from clean operation state.
        if school_type.status == "failed":
            school_type.import_operation_name = None
            school_type.training_operation_name = None
            school_type.document_ai_processor_version_id = None
            school_type.deploy_operation_name = None

        school_type.status = "in_setup"
        school_type.error_message = (
            "Setup queued. Waiting for classifier import/training worker."
        )
        school_type.updated_at = _utc_now()

        db.commit()
        db.refresh(school_type)

        samples_by_school_type_id = _load_samples_by_school_type_ids(
            db,
            [school_type.id],
        )

        return ClassifierTrainingRunResponse(
            status="ok",
            result={
                "queued": True,
                "message": "School type moved to In Setup.",
            },
            school_type=_serialize_school_type(
                school_type,
                samples=samples_by_school_type_id.get(school_type.id, []),
            ),
        )
    finally:
        db.close()


@router.post(
    "/school-types/{school_type_id}/move-to-existing",
    response_model=MoveSchoolTypeToExistingResponse,
)
def move_school_type_to_existing(
    school_type_id: int,
) -> MoveSchoolTypeToExistingResponse:
    """
    Frontend button action:
      Ready -> Existing Transcript Type

    This creates/updates transcript_classifier_routes, then removes the school
    from Ready by setting transcript_school_types.status='held'.

    The route is global and not semester-specific.
    """
    db = SessionLocal()
    try:
        school_type = (
            db.query(TranscriptSchoolType)
            .filter(TranscriptSchoolType.id == school_type_id)
            .first()
        )

        if not school_type:
            raise HTTPException(status_code=404, detail="School type not found.")

        if school_type.status != "ready":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Only Ready transcript types can be moved to Existing. "
                    f"Current status: {school_type.status}"
                ),
            )

        if not school_type.classifier_label:
            raise HTTPException(
                status_code=400,
                detail="Classifier label is missing.",
            )

        if not school_type.document_ai_processor_version_id:
            raise HTTPException(
                status_code=400,
                detail="Classifier processor version is missing.",
            )

        if (
            not school_type.extractor_profile
            or school_type.extractor_profile == "generic_transcript"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Extractor profile is not ready yet. "
                    "Set a real extractor profile before moving to Existing."
                ),
            )

        now = _utc_now()

        route = (
            db.query(TranscriptClassifierRoute)
            .filter(
                TranscriptClassifierRoute.classifier_label
                == school_type.classifier_label
            )
            .first()
        )

        if not route:
            route = TranscriptClassifierRoute(
                classifier_label=school_type.classifier_label,
                display_name=school_type.display_name,
                extractor_profile=school_type.extractor_profile,
                status="active",
                created_at=now,
                updated_at=now,
            )
            db.add(route)
            db.flush()
        else:
            route.display_name = school_type.display_name
            route.extractor_profile = school_type.extractor_profile
            route.status = "active"
            route.updated_at = now

        school_type.status = "held"
        school_type.error_message = "Moved to Existing Transcript Type."
        school_type.updated_at = now

        db.commit()
        db.refresh(route)
        db.refresh(school_type)

        return MoveSchoolTypeToExistingResponse(
            status="ok",
            message="Transcript type moved to Existing.",
            school_type=_serialize_school_type(school_type),
            route=_serialize_route(route),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
