from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import google.auth
from google.api_core.client_options import ClientOptions
from google.auth.transport.requests import AuthorizedSession
from google.cloud import documentai
from sqlalchemy.orm import Session

from app.models import (
    TranscriptClassifierRoute,
    TranscriptSchoolType,
    TranscriptSchoolTypeSample,
)

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


logger = logging.getLogger(__name__)

READY_TO_PROMOTE_STATUSES = {"in_setup"}
DEFAULT_IMPORT_BATCH_SIZE = 100
DEFAULT_OPERATION_TIMEOUT_SECONDS = 1800
OTHERS_CLASSIFIER_LABEL = "Others"


def _load_env_files() -> None:
    if load_dotenv is None:
        return

    candidates = [
        "env",
        ".env",
        "apps/backend/env",
        "apps/backend/.env",
    ]

    for path in candidates:
        if os.path.exists(path):
            load_dotenv(path, override=False)


_load_env_files()


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y"}


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def make_classifier_label(display_name: str) -> str:
    label = (display_name or "").strip().lower()
    label = label.replace("&", "and")
    label = re.sub(r"[^a-z0-9]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")

    if not label:
        raise ValueError("Could not create classifier label from an empty school name.")

    if not label[0].isalpha():
        label = f"school_{label}"

    return label[:64]


def make_display_name(label_or_name: str) -> str:
    cleaned = re.sub(r"[_\s]+", " ", (label_or_name or "").strip())
    return cleaned.title() if cleaned else label_or_name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_manual_marker(value: str | None) -> bool:
    return bool(value) and value.startswith("manual_")


def _is_existing_version_marker(value: str | None) -> bool:
    return bool(value) and value.startswith("existing_trained_version:")


def _is_retryable_setup_error(exc: Exception) -> bool:
    message = str(exc).lower()

    retryable_patterns = [
        "429",
        "quota",
        "concurrenttraining",
        "concurrent training",
        "rate limit",
        "resource exhausted",
        "temporarily unavailable",
        "unavailable",
        "timeout",
        "deadline",
        "try again",
        "retry",
    ]

    return any(pattern in message for pattern in retryable_patterns)


def _setup_error_message(exc: Exception) -> str:
    message = str(exc).strip()

    if not message:
        message = exc.__class__.__name__

    if _is_retryable_setup_error(exc):
        return f"Setup paused. Retry later. Reason: {message}"

    return (
        "Setup failed. Review the error and click Retry Setup after fixing it. "
        f"Reason: {message}"
    )


def _chunked(values: list[str], chunk_size: int) -> list[list[str]]:
    return [
        values[index : index + chunk_size]
        for index in range(0, len(values), chunk_size)
    ]


def _mime_type_for_gcs_uri(gcs_uri: str) -> str:
    clean_uri = gcs_uri.split("?", 1)[0].lower()

    if clean_uri.endswith(".pdf"):
        return "application/pdf"

    if clean_uri.endswith(".png"):
        return "image/png"

    if clean_uri.endswith(".jpg") or clean_uri.endswith(".jpeg"):
        return "image/jpeg"

    if clean_uri.endswith(".tif") or clean_uri.endswith(".tiff"):
        return "image/tiff"

    return "application/pdf"


def _is_supported_training_document(gcs_uri: str) -> bool:
    clean_uri = gcs_uri.split("?", 1)[0].lower()

    return clean_uri.endswith(
        (
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
        )
    )


class ClassifierTrainingService:
    """
    Resumable Document AI classifier setup service.

    This service completes the CLASSIFIER side only:
      - sync classifier label in Document AI schema
      - import verified samples with documentType=<label>
      - import/verify Others sample pool
      - train classifier version
      - detect already-trained matching versions
      - deploy classifier version
      - set deployed classifier version as default
      - verify default version actually changed

    Important:
      This service does NOT move a school type to Ready automatically.

      Ready should happen only after:
        1. classifier setup is complete
        2. extractor/profile setup is complete
        3. the user confirms/moves it forward

    The browser does not need to stay open. Each run resumes from saved DB
    operation/version fields in transcript_school_types.
    """

    def __init__(self, db: Session):
        _load_env_files()

        self.db = db

        # Resolve project/processor the same way the rest of the app does. The
        # existing (working) classifier autotrain service reads DOC_AI_PROJECT
        # (default "doc-ai-transcript") and DOC_AI_LAYOUT_CLASSIFIER
        # (default "a860d0a957566bc2" — the shared classifier processor). This
        # service originally only looked at DOC_AI_PROJECT_ID / *_CLASSIFIER_
        # PROCESSOR_ID, which are not set in this deployment, so promote_ready
        # silently skipped with "missing_project_id". Fall back to the shared
        # names/defaults so training works with zero extra config.
        self.project_id = _first_env(
            "DOC_AI_PROJECT_ID",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_PROJECT_ID",
            "DOC_AI_PROJECT",
            default="doc-ai-transcript",
        )

        self.location = _first_env(
            "DOC_AI_LOCATION",
            default="us",
        )

        self.processor_id = _first_env(
            "DOC_AI_CLASSIFIER_PROCESSOR_ID",
            "DOC_AI_PROCESSOR_ID",
            "DOC_AI_LAYOUT_CLASSIFIER",
            default="a860d0a957566bc2",
        )

        self.min_cluster_confidence = float(
            os.getenv("DOC_AI_MIN_CLUSTER_CONFIDENCE", "0.90")
        )

        self.training_split_ratio = float(
            os.getenv("DOC_AI_TRAINING_SPLIT_RATIO", "0.80")
        )

        self.import_batch_size = int(
            os.getenv("DOC_AI_IMPORT_BATCH_SIZE", str(DEFAULT_IMPORT_BATCH_SIZE))
        )

        self.others_required_sample_count = int(
            os.getenv("DOC_AI_OTHERS_REQUIRED_SAMPLE_COUNT", "12")
        )

        self.operation_timeout_seconds = int(
            os.getenv(
                "DOC_AI_OPERATION_TIMEOUT_SECONDS",
                str(DEFAULT_OPERATION_TIMEOUT_SECONDS),
            )
        )

        self.train_and_deploy_enabled = _env_bool(
            "DOC_AI_AUTO_TRAIN_AND_DEPLOY",
            "false",
        )

        if self.location == "us":
            self.api_base = "https://us-documentai.googleapis.com/v1beta3"
        else:
            self.api_base = f"https://{self.location}-documentai.googleapis.com/v1beta3"

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.authed_session = AuthorizedSession(credentials)

        client_options = ClientOptions(
            api_endpoint=f"{self.location}-documentai.googleapis.com"
        )
        self.processor_client = documentai.DocumentProcessorServiceClient(
            client_options=client_options
        )

    def promote_ready_school_types(self) -> dict[str, Any]:
        if not self.project_id:
            return {
                "processed": 0,
                "ready": 0,
                "in_progress": 0,
                "failed": 0,
                "skipped": "missing_project_id",
            }

        if not self.processor_id:
            return {
                "processed": 0,
                "ready": 0,
                "in_progress": 0,
                "failed": 0,
                "skipped": "missing_classifier_processor_id",
            }

        candidates = (
            self.db.query(TranscriptSchoolType)
            .filter(TranscriptSchoolType.status.in_(list(READY_TO_PROMOTE_STATUSES)))
            .filter(
                TranscriptSchoolType.sample_count
                >= TranscriptSchoolType.required_sample_count
            )
            .filter(TranscriptSchoolType.classifier_label != OTHERS_CLASSIFIER_LABEL)
            .all()
        )

        processed = 0
        ready = 0
        in_progress = 0
        failed = 0
        skipped = 0

        for school_type in candidates:
            try:
                if not self._passes_automatic_gates(school_type):
                    skipped += 1
                    continue

                self._promote_one_school_type(school_type)
                processed += 1
                in_progress += 1

            except Exception as exc:
                logger.exception(
                    "Failed to promote school type id=%s label=%s",
                    school_type.id,
                    school_type.classifier_label,
                )

                if _is_retryable_setup_error(exc):
                    school_type.status = "in_setup"
                    in_progress += 1
                else:
                    school_type.status = "failed"
                    failed += 1

                school_type.error_message = _setup_error_message(exc)
                school_type.updated_at = _now()
                self.db.commit()

        return {
            "candidates": len(candidates),
            "processed": processed,
            "ready": ready,
            "in_progress": in_progress,
            "failed": failed,
            "skipped": skipped,
            "project_id": self.project_id,
            "location": self.location,
            "processor_id": self.processor_id,
            "train_and_deploy_enabled": self.train_and_deploy_enabled,
            "others_required_sample_count": self.others_required_sample_count,
        }

    def _promote_one_school_type(self, school_type: TranscriptSchoolType) -> bool:
        label_source = school_type.classifier_label or school_type.display_name
        label = make_classifier_label(label_source)

        school_type.status = "in_setup"
        school_type.classifier_label = label
        school_type.document_ai_processor_id = self.processor_id
        school_type.updated_at = _now()
        self.db.commit()

        logger.info("Running classifier setup step for label=%s", label)

        self.sync_classifier_label(label)

        # If GCP already trained a matching version manually or from a previous run,
        # attach it and continue to deploy/default.
        self._attach_existing_trained_version_if_available(label, school_type)

        if not school_type.document_ai_processor_version_id:
            if not self._ensure_import_complete(
                label=label,
                school_type=school_type,
                import_reason="real_school",
            ):
                return False

            if not self._ensure_others_pool_imported():
                return False

            if not self.train_and_deploy_enabled:
                school_type.status = "in_setup"
                school_type.error_message = (
                    "Samples imported. Training/deploy is disabled. "
                    "Set DOC_AI_AUTO_TRAIN_AND_DEPLOY=true to continue."
                )
                school_type.updated_at = _now()
                self.db.commit()
                return False

            if not self._ensure_training_complete(label, school_type):
                return False

        if not school_type.document_ai_processor_version_id:
            raise RuntimeError(
                f"Training finished but no processor version id was found for {label}."
            )

        if not self._ensure_deploy_complete(school_type):
            return False

        if not self._ensure_default_version(school_type):
            return False

        school_type.status = "in_setup"
        school_type.error_message = (
            "Classifier setup complete: trained, deployed, and set as default. "
            "Waiting for extractor setup before moving to Ready."
        )
        school_type.updated_at = _now()
        self.db.commit()

        logger.info(
            "Classifier setup complete but waiting for extractor. label=%s version=%s",
            label,
            school_type.document_ai_processor_version_id,
        )

        return True

    def _passes_automatic_gates(self, school_type: TranscriptSchoolType) -> bool:
        required_count = school_type.required_sample_count or 10
        verified_sample_count = self._verified_sample_count(school_type)

        school_type.sample_count = verified_sample_count
        school_type.updated_at = _now()
        self.db.commit()

        if verified_sample_count < required_count:
            school_type.status = "in_setup"
            school_type.error_message = (
                f"Not enough verified sample PDFs found: "
                f"{verified_sample_count} / {required_count}."
            )
            school_type.updated_at = _now()
            self.db.commit()
            return False

        if (
            school_type.cluster_confidence is not None
            and school_type.cluster_confidence < self.min_cluster_confidence
        ):
            school_type.status = "in_setup"
            school_type.error_message = (
                f"Cluster confidence {school_type.cluster_confidence:.3f} "
                f"is below required {self.min_cluster_confidence:.3f}."
            )
            school_type.updated_at = _now()
            self.db.commit()
            return False

        return True

    def _verified_sample_count(self, school_type: TranscriptSchoolType) -> int:
        return (
            self.db.query(TranscriptSchoolTypeSample)
            .filter(TranscriptSchoolTypeSample.school_type_id == school_type.id)
            .filter(TranscriptSchoolTypeSample.verified.is_(True))
            .count()
        )

    def _verified_sample_gcs_uris(self, school_type: TranscriptSchoolType) -> list[str]:
        sample_rows = (
            self.db.query(TranscriptSchoolTypeSample)
            .filter(TranscriptSchoolTypeSample.school_type_id == school_type.id)
            .filter(TranscriptSchoolTypeSample.verified.is_(True))
            .order_by(
                TranscriptSchoolTypeSample.cluster_id.asc(),
                TranscriptSchoolTypeSample.created_at.asc(),
                TranscriptSchoolTypeSample.id.asc(),
            )
            .all()
        )

        uris: list[str] = []
        seen: set[str] = set()
        skipped_invalid: list[str] = []

        for sample in sample_rows:
            gcs_uri = (sample.gcs_uri or "").strip()

            if not gcs_uri:
                continue

            if not gcs_uri.startswith("gs://"):
                skipped_invalid.append(gcs_uri)
                continue

            if not _is_supported_training_document(gcs_uri):
                skipped_invalid.append(gcs_uri)
                continue

            if gcs_uri in seen:
                continue

            seen.add(gcs_uri)
            uris.append(gcs_uri)

        if skipped_invalid:
            logger.warning(
                "Skipped unsupported/non-GCS samples for school_type_id=%s: %s",
                school_type.id,
                skipped_invalid[:10],
            )

        return uris

    def _others_school_type(self) -> TranscriptSchoolType | None:
        return (
            self.db.query(TranscriptSchoolType)
            .filter(TranscriptSchoolType.classifier_label == OTHERS_CLASSIFIER_LABEL)
            .first()
        )

    def _ensure_others_pool_imported(self) -> bool:
        others = self._others_school_type()

        if not others:
            raise RuntimeError(
                "Others sample pool row does not exist. Run Needs Setup refresh "
                "or clustering sync first."
            )

        verified_count = self._verified_sample_count(others)

        others.sample_count = verified_count
        others.required_sample_count = (
            others.required_sample_count or self.others_required_sample_count
        )
        others.document_ai_processor_id = self.processor_id
        others.updated_at = _now()
        self.db.commit()

        if verified_count < self.others_required_sample_count:
            raise RuntimeError(
                "Not enough verified Others samples for classifier training. "
                f"Found {verified_count}; required {self.others_required_sample_count}."
            )

        self.sync_classifier_label(OTHERS_CLASSIFIER_LABEL)

        return self._ensure_import_complete(
            label=OTHERS_CLASSIFIER_LABEL,
            school_type=others,
            import_reason="others_pool",
        )

    def _ensure_import_complete(
        self,
        *,
        label: str,
        school_type: TranscriptSchoolType,
        import_reason: str,
    ) -> bool:
        if _is_manual_marker(school_type.import_operation_name):
            return True

        if school_type.import_operation_name:
            done, _operation = self._poll_rest_operation(
                school_type.import_operation_name
            )

            if not done:
                school_type.status = school_type.status or "in_setup"
                school_type.error_message = (
                    f"Import is still running for {label}. "
                    f"Operation: {school_type.import_operation_name}"
                )
                school_type.updated_at = _now()
                self.db.commit()
                return False

            school_type.error_message = None
            school_type.updated_at = _now()
            self.db.commit()
            return True

        operation_name = self.start_import_labeled_samples(
            label=label,
            school_type=school_type,
        )

        school_type.import_operation_name = operation_name
        school_type.document_ai_processor_id = self.processor_id
        school_type.error_message = (
            f"Import started for {label} ({import_reason}). "
            "Backend worker will continue automatically."
        )
        school_type.updated_at = _now()
        self.db.commit()

        return False

    def _ensure_training_complete(
        self,
        label: str,
        school_type: TranscriptSchoolType,
    ) -> bool:
        self._attach_existing_trained_version_if_available(label, school_type)

        if school_type.document_ai_processor_version_id:
            return True

        if _is_manual_marker(school_type.training_operation_name):
            self._attach_existing_trained_version_if_available(label, school_type)
            return bool(school_type.document_ai_processor_version_id)

        if _is_existing_version_marker(school_type.training_operation_name):
            self._attach_existing_trained_version_if_available(label, school_type)
            return bool(school_type.document_ai_processor_version_id)

        if school_type.training_operation_name:
            done, operation = self._poll_rest_operation(
                school_type.training_operation_name
            )

            if not done:
                school_type.error_message = (
                    f"Training is still running for {label}. "
                    f"Operation: {school_type.training_operation_name}"
                )
                school_type.updated_at = _now()
                self.db.commit()
                return False

            processor_version_name = self._extract_processor_version_name(operation)

            if not processor_version_name:
                existing_version = self._find_existing_trained_version(label)
                if not existing_version:
                    raise RuntimeError(
                        "Training operation completed, but processor version could "
                        f"not be found for label={label}."
                    )
                processor_version_name = existing_version["name"]

            processor_version_id = processor_version_name.split("/")[-1]

            school_type.document_ai_processor_version_id = processor_version_id
            school_type.error_message = (
                f"Training complete. Processor version: {processor_version_id}. "
                "Deployment will continue automatically."
            )
            school_type.updated_at = _now()
            self.db.commit()

            return True

        operation_name = self.start_train_processor_version(label)

        school_type.training_operation_name = operation_name
        school_type.error_message = (
            f"Training started for {label}. Backend worker will continue automatically."
        )
        school_type.updated_at = _now()
        self.db.commit()

        return False

    def _ensure_deploy_complete(self, school_type: TranscriptSchoolType) -> bool:
        processor_version_id = school_type.document_ai_processor_version_id

        if not processor_version_id:
            raise RuntimeError("Cannot deploy because processor version id is missing.")

        state = self._processor_version_state(processor_version_id)

        if state and state.upper() == "DEPLOYED":
            if not school_type.deploy_operation_name:
                school_type.deploy_operation_name = (
                    f"manual_or_existing_deployed_version:{processor_version_id}"
                )
                school_type.updated_at = _now()
                self.db.commit()
            return True

        if _is_manual_marker(school_type.deploy_operation_name):
            return True

        if school_type.deploy_operation_name:
            done, _operation = self._poll_rest_operation(
                school_type.deploy_operation_name
            )

            if not done:
                school_type.error_message = (
                    f"Deploy is still running for version {processor_version_id}. "
                    f"Operation: {school_type.deploy_operation_name}"
                )
                school_type.updated_at = _now()
                self.db.commit()
                return False

            school_type.error_message = (
                f"Deploy complete for version {processor_version_id}. "
                "Default version will be set next."
            )
            school_type.updated_at = _now()
            self.db.commit()

            return True

        operation_name = self.start_deploy_processor_version(processor_version_id)

        school_type.deploy_operation_name = operation_name
        school_type.error_message = (
            f"Deploy started for version {processor_version_id}. "
            "Backend worker will continue automatically."
        )
        school_type.updated_at = _now()
        self.db.commit()

        return False

    def _ensure_default_version(self, school_type: TranscriptSchoolType) -> bool:
        processor_version_id = school_type.document_ai_processor_version_id

        if not processor_version_id:
            raise RuntimeError(
                "Cannot set default because processor version id is missing."
            )

        state = self._processor_version_state(processor_version_id)
        if state and state.upper() != "DEPLOYED":
            school_type.error_message = (
                f"Processor version {processor_version_id} is not deployed yet "
                f"(state={state}). Default will be set after deployment."
            )
            school_type.updated_at = _now()
            self.db.commit()
            return False

        current_default_id = self._default_processor_version_id()

        if current_default_id == processor_version_id:
            school_type.error_message = None
            school_type.updated_at = _now()
            self.db.commit()
            return True

        school_type.error_message = (
            f"Setting processor version {processor_version_id} as default. "
            "Backend worker is continuing automatically."
        )
        school_type.updated_at = _now()
        self.db.commit()

        operation_name = self.set_default_processor_version(processor_version_id)

        school_type.error_message = (
            f"Set-default operation finished: {operation_name}. "
            "Verifying default version."
        )
        school_type.updated_at = _now()
        self.db.commit()

        current_default_id = self._default_processor_version_id()

        if current_default_id != processor_version_id:
            raise RuntimeError(
                "Set-default operation completed, but default processor version "
                f"is still {current_default_id or 'unknown'}, expected {processor_version_id}."
            )

        school_type.error_message = None
        school_type.updated_at = _now()
        self.db.commit()

        return True

    def _dataset_schema_name(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/processors/{self.processor_id}/dataset/datasetSchema"
        )

    def _dataset_name(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/processors/{self.processor_id}/dataset"
        )

    def _processor_name(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/processors/{self.processor_id}"
        )

    def _processor_versions_url(self) -> str:
        return f"{self.api_base}/{self._processor_name()}/processorVersions"

    def _processor_url(self) -> str:
        return f"{self.api_base}/{self._processor_name()}"

    def _processor_version_url(self, processor_version_id: str) -> str:
        return (
            f"{self.api_base}/{self._processor_name()}"
            f"/processorVersions/{processor_version_id}"
        )

    def sync_classifier_label(self, label: str) -> None:
        schema_name = self._dataset_schema_name()
        url = f"{self.api_base}/{schema_name}"

        response = self.authed_session.get(
            url,
            params={"visibleFieldsOnly": "false"},
        )
        response.raise_for_status()

        schema = response.json()
        document_schema = schema.setdefault("documentSchema", {})
        entity_types = document_schema.setdefault("entityTypes", [])

        existing = {
            entity.get("name") or entity.get("type")
            for entity in entity_types
            if isinstance(entity, dict)
        }

        if label in existing:
            logger.info("Document AI classifier label already exists: %s", label)
            return

        entity_types.append(
            {
                "name": label,
                "baseTypes": ["document"],
                "displayName": make_display_name(label),
            }
        )

        patch_response = self.authed_session.patch(
            url,
            params={"updateMask": "document_schema"},
            json=schema,
        )
        patch_response.raise_for_status()

        logger.info("Added Document AI classifier label: %s", label)

    def start_import_labeled_samples(
        self,
        label: str,
        school_type: TranscriptSchoolType,
    ) -> str:
        gcs_uris = self._verified_sample_gcs_uris(school_type)

        if not gcs_uris:
            raise RuntimeError(
                f"No verified sample GCS URIs found for classifier import "
                f"for label={label}."
            )

        required_count = (
            self.others_required_sample_count
            if label == OTHERS_CLASSIFIER_LABEL
            else school_type.required_sample_count or 10
        )

        if len(gcs_uris) < required_count:
            raise RuntimeError(
                f"Not enough valid sample GCS URIs for label={label}: "
                f"{len(gcs_uris)} / {required_count}."
            )

        url = f"{self.api_base}/{self._dataset_name()}:importDocuments"

        import_configs: list[dict[str, Any]] = []

        for uri_batch in _chunked(gcs_uris, self.import_batch_size):
            import_configs.append(
                {
                    "batchInputConfig": {
                        "gcsDocuments": {
                            "documents": [
                                {
                                    "gcsUri": gcs_uri,
                                    "mimeType": _mime_type_for_gcs_uri(gcs_uri),
                                }
                                for gcs_uri in uri_batch
                            ]
                        }
                    },
                    "documentType": label,
                    "autoSplitConfig": {
                        "trainingSplitRatio": self.training_split_ratio,
                    },
                }
            )

        response = self.authed_session.post(
            url,
            json={"batchDocumentsImportConfigs": import_configs},
        )

        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                "Document AI importDocuments request failed before operation "
                f"creation. Status={response.status_code}. Body={response.text[:2000]}"
            ) from exc

        operation = response.json()
        operation_name = operation.get("name", "")

        if not operation_name:
            raise RuntimeError(
                f"Document AI importDocuments did not return operation name: {operation}"
            )

        logger.info(
            "Started import for label=%s docs=%s operation=%s",
            label,
            len(gcs_uris),
            operation_name,
        )

        return operation_name

    def start_train_processor_version(self, label: str) -> str:
        parent = self.processor_client.processor_path(
            self.project_id,
            self.location,
            self.processor_id,
        )

        display_name = (
            f"classifier_{datetime.now(timezone.utc).strftime('%Y_%m_%d_%H_%M')}"
            f"_add_{label}"
        )

        processor_version = documentai.ProcessorVersion(display_name=display_name)

        request = documentai.TrainProcessorVersionRequest(
            parent=parent,
            processor_version=processor_version,
        )

        operation = self.processor_client.train_processor_version(request=request)
        operation_name = operation.operation.name

        logger.info("Started training operation: %s", operation_name)

        return operation_name

    def start_deploy_processor_version(self, processor_version_id: str) -> str:
        name = self.processor_client.processor_version_path(
            self.project_id,
            self.location,
            self.processor_id,
            processor_version_id,
        )

        operation = self.processor_client.deploy_processor_version(name=name)
        operation_name = operation.operation.name

        logger.info("Started deployment operation: %s", operation_name)

        return operation_name

    def set_default_processor_version(self, processor_version_id: str) -> str:
        processor_name = self.processor_client.processor_path(
            self.project_id,
            self.location,
            self.processor_id,
        )

        version_name = self.processor_client.processor_version_path(
            self.project_id,
            self.location,
            self.processor_id,
            processor_version_id,
        )

        request = documentai.SetDefaultProcessorVersionRequest(
            processor=processor_name,
            default_processor_version=version_name,
        )

        operation = self.processor_client.set_default_processor_version(request=request)
        operation_name = operation.operation.name

        logger.info(
            "Started set-default operation. processor=%s version=%s operation=%s",
            processor_name,
            processor_version_id,
            operation_name,
        )

        operation.result(timeout=self.operation_timeout_seconds)

        logger.info("Default classifier version is now requested as: %s", version_name)

        return operation_name

    def _poll_rest_operation(
        self,
        operation_name: str,
    ) -> tuple[bool, dict[str, Any]]:
        if not operation_name:
            raise RuntimeError("Missing Document AI operation name.")

        if _is_manual_marker(operation_name) or _is_existing_version_marker(
            operation_name
        ):
            return True, {}

        url = f"{self.api_base}/{operation_name}"

        response = self.authed_session.get(url)
        response.raise_for_status()

        operation = response.json()

        if not operation.get("done"):
            return False, operation

        if "error" in operation:
            raise RuntimeError(self._describe_failed_operation(operation))

        return True, operation

    def _describe_failed_operation(self, operation: dict[str, Any]) -> str:
        error = operation.get("error") or {}
        metadata = operation.get("metadata") or {}

        parts = []

        if error:
            parts.append(f"operation_error={error}")

        individual_statuses = (
            metadata.get("individualImportStatuses")
            or metadata.get("individualImportStatus")
            or metadata.get("individual_import_statuses")
            or []
        )

        failed_items = []

        for item in individual_statuses:
            status = item.get("status") or {}
            code = status.get("code")
            message = status.get("message")
            source = item.get("inputGcsSource") or item.get("input_gcs_source")

            if code or message:
                failed_items.append(
                    {
                        "source": source,
                        "code": code,
                        "message": message,
                    }
                )

        if failed_items:
            parts.append(f"sample_failures={failed_items[:10]}")

        if not parts:
            parts.append(f"operation={operation}")

        return "Document AI operation failed. " + " ".join(parts)

    def _extract_processor_version_name(self, operation: dict[str, Any]) -> str | None:
        response = operation.get("response") or {}

        possible = [
            response.get("processorVersion"),
            response.get("processor_version"),
            response.get("name"),
        ]

        for value in possible:
            if value and "/processorVersions/" in value:
                return value

        return None

    def _list_processor_versions(self) -> list[dict[str, Any]]:
        versions: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token

            response = self.authed_session.get(
                self._processor_versions_url(),
                params=params,
            )
            response.raise_for_status()

            payload = response.json()
            versions.extend(payload.get("processorVersions", []))

            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        return versions

    def _find_existing_trained_version(self, label: str) -> dict[str, Any] | None:
        marker = f"_add_{label}"
        matches: list[dict[str, Any]] = []

        for version in self._list_processor_versions():
            display_name = version.get("displayName") or ""
            name = version.get("name") or ""
            state = (version.get("state") or "").upper()

            if marker not in display_name and not display_name.endswith(label):
                continue

            if state in {"FAILED", "DELETING", "CREATING"}:
                continue

            if not name:
                continue

            matches.append(version)

        matches.sort(
            key=lambda item: item.get("createTime") or item.get("updateTime") or "",
            reverse=True,
        )

        return matches[0] if matches else None

    def _attach_existing_trained_version_if_available(
        self,
        label: str,
        school_type: TranscriptSchoolType,
    ) -> None:
        if school_type.document_ai_processor_version_id:
            return

        existing_version = self._find_existing_trained_version(label)

        if not existing_version:
            return

        version_name = existing_version.get("name") or ""
        version_id = version_name.split("/")[-1]

        if not version_id:
            return

        school_type.document_ai_processor_version_id = version_id
        school_type.training_operation_name = (
            f"existing_trained_version:{existing_version.get('displayName') or version_id}"
        )
        school_type.error_message = (
            f"Found existing trained GCP version {version_id}. "
            "Deployment/default setup will continue automatically."
        )
        school_type.updated_at = _now()
        self.db.commit()

        logger.info(
            "Attached existing trained version for label=%s version=%s",
            label,
            version_id,
        )

    def _processor_version_state(self, processor_version_id: str) -> str | None:
        response = self.authed_session.get(
            self._processor_version_url(processor_version_id)
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        payload = response.json()
        state = payload.get("state")

        if state is None:
            return None

        return str(state)

    def _default_processor_version_id(self) -> str | None:
        response = self.authed_session.get(self._processor_url())
        response.raise_for_status()

        payload = response.json()
        default_version_name = payload.get("defaultProcessorVersion") or ""

        if not default_version_name:
            return None

        return default_version_name.split("/")[-1]

    def activate_route(self, school_type: TranscriptSchoolType) -> None:
        """
        Keep this helper for Move-to-Existing / final activation.

        Do not call it from automatic classifier setup.
        The route should become active only after extractor/profile setup is done.
        """
        route = (
            self.db.query(TranscriptClassifierRoute)
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
                extractor_profile=school_type.extractor_profile or "generic_transcript",
                status="active",
            )
            self.db.add(route)
        else:
            route.display_name = school_type.display_name
            route.extractor_profile = (
                school_type.extractor_profile or route.extractor_profile
            )
            route.status = "active"
            route.updated_at = _now()

        self.db.commit()
