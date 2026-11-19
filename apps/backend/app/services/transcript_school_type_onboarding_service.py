from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import TranscriptSchoolType, TranscriptSchoolTypeSample


DEFAULT_REQUIRED_SAMPLE_COUNT = int(
    os.getenv("DOC_AI_OTHERS_REQUIRED_SAMPLE_COUNT", "15")
)

OTHERS_CLASSIFIER_LABEL = "Others"
OTHERS_DISPLAY_NAME = "Others"


def strip_duplicate_folder_suffix(folder_name: str) -> str:
    """
    Merge duplicate clustering folders.

    Examples:
      cypress_high_school      -> cypress_high_school
      cypress_high_school_2    -> cypress_high_school
      cypress_high_school_3    -> cypress_high_school
    """
    cleaned = folder_name.strip().replace("-", "_")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    cleaned = re.sub(r"_[0-9]+$", "", cleaned)
    return cleaned


def normalize_school_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def display_name_from_folder_name(folder_name: str) -> str:
    canonical_folder = strip_duplicate_folder_suffix(folder_name)
    return canonical_folder.replace("_", " ").title()


def make_classifier_label(display_name: str) -> str:
    label = display_name.strip().lower()
    label = label.replace("&", "and")
    label = re.sub(r"[^a-z0-9]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")

    if not label:
        raise ValueError("Could not create classifier label from empty school name.")

    if not label[0].isalpha():
        label = f"school_{label}"

    return label[:64]


def _valid_pdf_blob_names(file_blob_names: Iterable[str]) -> list[str]:
    valid: list[str] = []
    seen: set[str] = set()

    for blob_name in file_blob_names:
        clean_blob = (blob_name or "").strip()

        if not clean_blob:
            continue

        if not clean_blob.lower().endswith(".pdf"):
            continue

        if clean_blob in seen:
            continue

        seen.add(clean_blob)
        valid.append(clean_blob)

    return valid


def _get_or_create_others_school_type(db: Session) -> TranscriptSchoolType:
    now = datetime.utcnow()

    others = (
        db.query(TranscriptSchoolType)
        .filter(TranscriptSchoolType.classifier_label == OTHERS_CLASSIFIER_LABEL)
        .first()
    )

    if others:
        others.display_name = OTHERS_DISPLAY_NAME
        others.normalized_name = normalize_school_name(OTHERS_DISPLAY_NAME)
        others.required_sample_count = others.required_sample_count or 0
        others.extractor_profile = others.extractor_profile or "generic_transcript"

        # Keep Others hidden from normal Needs Setup / Ready workflow.
        # The classifier_training_service reads it directly by label.
        if not others.status:
            others.status = "held"

        others.updated_at = now
        db.flush()
        return others

    others = TranscriptSchoolType(
        display_name=OTHERS_DISPLAY_NAME,
        normalized_name=normalize_school_name(OTHERS_DISPLAY_NAME),
        classifier_label=OTHERS_CLASSIFIER_LABEL,
        status="held",
        sample_count=0,
        required_sample_count=0,
        cluster_confidence=None,
        gcs_raw_prefix=None,
        extractor_profile="generic_transcript",
        created_at=now,
        updated_at=now,
    )
    db.add(others)
    db.flush()

    return others


def _sync_low_count_school_samples_into_others(
    db: Session,
    *,
    source_school_type: TranscriptSchoolType,
    display_name: str,
    bucket_name: str,
    file_blob_names: list[str],
    semester: str | None,
) -> None:
    """
    Add every PDF from a low-count school group into the Others sample pool.

    Important:
      - No maximum cap.
      - No minimum requirement.
      - A low-count group with 1 file goes into Others.
      - A low-count group with 14 files goes into Others.
      - All low-count groups together become the Others training pool.
    """
    now = datetime.utcnow()
    others = _get_or_create_others_school_type(db)

    for blob_name in file_blob_names:
        gcs_uri = f"gs://{bucket_name}/{blob_name}"

        existing = (
            db.query(TranscriptSchoolTypeSample)
            .filter(
                TranscriptSchoolTypeSample.school_type_id == others.id,
                TranscriptSchoolTypeSample.gcs_uri == gcs_uri,
            )
            .first()
        )

        if existing:
            existing.verified = True
            existing.detected_school_name = display_name
            existing.cluster_id = semester
            existing.source_file = existing.source_file or gcs_uri
            continue

        db.add(
            TranscriptSchoolTypeSample(
                school_type_id=others.id,
                extraction_file_id=None,
                source_file=gcs_uri,
                gcs_uri=gcs_uri,
                detected_school_name=display_name,
                cluster_id=semester,
                cluster_confidence=None,
                verified=True,
                created_at=now,
            )
        )

    db.flush()

    others.sample_count = (
        db.query(TranscriptSchoolTypeSample)
        .filter(
            TranscriptSchoolTypeSample.school_type_id == others.id,
            TranscriptSchoolTypeSample.verified.is_(True),
        )
        .count()
    )
    others.updated_at = now

    # Keep source school updated too.
    source_school_type.updated_at = now

    db.flush()


def _remove_school_samples_from_others(
    db: Session,
    *,
    source_school_type: TranscriptSchoolType,
) -> None:
    """
    When a school reaches the threshold and becomes its own classifier label,
    remove those same PDF samples from Others.

    This prevents Cypress/Edison/etc. from being trained as Others after they
    already have enough samples to become their own class.
    """
    others = (
        db.query(TranscriptSchoolType)
        .filter(TranscriptSchoolType.classifier_label == OTHERS_CLASSIFIER_LABEL)
        .first()
    )

    if not others:
        return

    source_samples = (
        db.query(TranscriptSchoolTypeSample.gcs_uri)
        .filter(TranscriptSchoolTypeSample.school_type_id == source_school_type.id)
        .filter(TranscriptSchoolTypeSample.verified.is_(True))
        .all()
    )

    source_gcs_uris = [row[0] for row in source_samples if row[0]]

    if not source_gcs_uris:
        return

    (
        db.query(TranscriptSchoolTypeSample)
        .filter(TranscriptSchoolTypeSample.school_type_id == others.id)
        .filter(TranscriptSchoolTypeSample.gcs_uri.in_(source_gcs_uris))
        .delete(synchronize_session=False)
    )

    others.sample_count = (
        db.query(TranscriptSchoolTypeSample)
        .filter(
            TranscriptSchoolTypeSample.school_type_id == others.id,
            TranscriptSchoolTypeSample.verified.is_(True),
        )
        .count()
    )
    others.updated_at = datetime.utcnow()

    db.flush()


def _recalculate_school_sample_count(
    db: Session,
    school_type: TranscriptSchoolType,
) -> int:
    count = (
        db.query(TranscriptSchoolTypeSample)
        .filter(TranscriptSchoolTypeSample.school_type_id == school_type.id)
        .filter(TranscriptSchoolTypeSample.verified.is_(True))
        .count()
    )

    school_type.sample_count = count
    school_type.updated_at = datetime.utcnow()
    db.flush()

    return count


def sync_grouped_school_folder(
    db: Session,
    *,
    folder_name: str,
    gcs_group_prefix: str,
    file_blob_names: Iterable[str],
    bucket_name: str,
    semester: str | None = None,
) -> TranscriptSchoolType:
    """
    Sync one GCS grouped-school folder into Needs Setup.

    Writes/updates:
      - transcript_school_types
      - transcript_school_type_samples

    Rules:
      - cypress_high_school and cypress_high_school_2 merge into one school type
      - each PDF is stored as a sample row under that school
      - sample_count is recalculated from verified sample rows
      - existing in_setup/ready/failed status is not reset
      - if the school has fewer than 15 total samples, ALL of its PDFs are also
        copied into the Others sample pool
      - no max cap is applied to Others
      - no minimum is required to add samples into Others
      - once the school reaches 15+, its PDFs are removed from Others
    """
    canonical_folder_name = strip_duplicate_folder_suffix(folder_name)
    display_name = display_name_from_folder_name(canonical_folder_name)
    normalized_name = normalize_school_name(display_name)
    classifier_label = make_classifier_label(display_name)
    now = datetime.utcnow()

    valid_blob_names = _valid_pdf_blob_names(file_blob_names)

    school_type = (
        db.query(TranscriptSchoolType)
        .filter(TranscriptSchoolType.classifier_label == classifier_label)
        .first()
    )

    if not school_type:
        school_type = TranscriptSchoolType(
            display_name=display_name,
            normalized_name=normalized_name,
            classifier_label=classifier_label,
            status="needs_setup",
            sample_count=0,
            required_sample_count=DEFAULT_REQUIRED_SAMPLE_COUNT,
            cluster_confidence=None,
            gcs_raw_prefix=gcs_group_prefix,
            extractor_profile="generic_transcript",
            created_at=now,
            updated_at=now,
        )
        db.add(school_type)
        db.flush()
    else:
        school_type.display_name = display_name
        school_type.normalized_name = normalized_name

        # Keep the first prefix as the display folder, but samples can come from
        # many term folders through transcript_school_type_samples.
        school_type.gcs_raw_prefix = school_type.gcs_raw_prefix or gcs_group_prefix

        school_type.required_sample_count = (
            school_type.required_sample_count or DEFAULT_REQUIRED_SAMPLE_COUNT
        )

        if not school_type.status:
            school_type.status = "needs_setup"

        # Do not reset in_setup / ready / failed.
        school_type.updated_at = now
        db.flush()

    for blob_name in valid_blob_names:
        gcs_uri = f"gs://{bucket_name}/{blob_name}"

        existing_sample = (
            db.query(TranscriptSchoolTypeSample)
            .filter(
                TranscriptSchoolTypeSample.school_type_id == school_type.id,
                TranscriptSchoolTypeSample.gcs_uri == gcs_uri,
            )
            .first()
        )

        if existing_sample:
            existing_sample.verified = True
            existing_sample.detected_school_name = display_name
            existing_sample.cluster_id = semester
            existing_sample.source_file = existing_sample.source_file or gcs_uri
            continue

        db.add(
            TranscriptSchoolTypeSample(
                school_type_id=school_type.id,
                extraction_file_id=None,
                source_file=gcs_uri,
                gcs_uri=gcs_uri,
                detected_school_name=display_name,
                cluster_id=semester,
                cluster_confidence=None,
                verified=True,
                created_at=now,
            )
        )

    db.flush()

    total_school_samples = _recalculate_school_sample_count(db, school_type)
    required_count = school_type.required_sample_count or DEFAULT_REQUIRED_SAMPLE_COUNT

    if total_school_samples < required_count:
        _sync_low_count_school_samples_into_others(
            db,
            source_school_type=school_type,
            display_name=display_name,
            bucket_name=bucket_name,
            file_blob_names=valid_blob_names,
            semester=semester,
        )
    else:
        _remove_school_samples_from_others(
            db,
            source_school_type=school_type,
        )

    db.flush()
    return school_type
