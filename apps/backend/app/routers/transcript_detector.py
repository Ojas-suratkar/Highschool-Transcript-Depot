from collections import defaultdict
from pathlib import PurePosixPath, Path
from typing import Any, Optional
from io import BytesIO
import json
import logging

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import storage
from pydantic import BaseModel

from app.db import SessionLocal
from app.models import TranscriptClassifierRoute
from app.services.orphan_cleanup import (
    purge_orphan_rows_for_blobs as _purge_orphan_rows_for_blobs,
)


router = APIRouter(prefix="/transcript-detector", tags=["transcript-detector"])
logger = logging.getLogger(__name__)

GCS_BUCKET = "doc-ai-transcript-us-central1-v1-001"
GCS_INPUT_PREFIX = "01_Inbox_Raw_HS_Transcripts/"
GLOBAL_EXISTING_TYPES_FILE = Path("app/data/global_existing_types.json")

# These 3 should always show first on Existing Transcript Type page.
KNOWN_TRANSCRIPT_FOLDERS = [
    "LBUSD",
    "Mayfair_High_School",
    "St_Anthony_High_School",
]

KNOWN_TRANSCRIPT_LABELS = {
    "LBUSD": "Long Beach Unified District",
    "Mayfair_High_School": "Mayfair High School",
    "St_Anthony_High_School": "St Anthony High School",
}


def get_storage_client() -> storage.Client:
    return storage.Client()


def gcs_list_pdfs(bucket_name: str, prefix: str) -> list[str]:
    client = get_storage_client()

    if prefix and not prefix.endswith("/"):
        prefix += "/"

    blobs = []
    for b in client.list_blobs(bucket_name, prefix=prefix):
        if not b.name.lower().endswith(".pdf"):
            continue
        # The term's handbook/ folder holds the admissions-rules document, not a
        # transcript — never sweep it into classification/extraction.
        if "/handbook/" in b.name.lower():
            continue
        blobs.append(b.name)

    return sorted(blobs)


def get_semester_from_input_blob(blob_name: str) -> str:
    p = PurePosixPath(blob_name)
    base = PurePosixPath(GCS_INPUT_PREFIX)

    try:
        rel = p.relative_to(base)
        return rel.parts[0] if len(rel.parts) >= 2 else "Unsorted"
    except Exception:
        return "Unsorted"


def stream_pdf(blob_name: str) -> StreamingResponse:
    if not blob_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)

    if not blob.exists(client):
        raise HTTPException(status_code=404, detail="File not found in GCS.")

    file_bytes = blob.download_as_bytes()
    filename = PurePosixPath(blob_name).name

    return StreamingResponse(
        BytesIO(file_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def normalize_folder_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def format_existing_type_label(folder_name: str) -> str:
    if folder_name in KNOWN_TRANSCRIPT_LABELS:
        return KNOWN_TRANSCRIPT_LABELS[folder_name]

    return folder_name.replace("_", " ").title()


def get_folder_name_from_label(label: str) -> str:
    reverse_map = {
        "Long Beach Unified District": "LBUSD",
        "Mayfair High School": "Mayfair_High_School",
        "St Anthony High School": "St_Anthony_High_School",
    }

    if label in reverse_map:
        return reverse_map[label]

    return label.replace(" ", "_")


def load_global_existing_types() -> list[dict[str, str]]:
    """
    Legacy fallback.

    Older code stored moved custom types in app/data/global_existing_types.json.
    New code should use transcript_classifier_routes, but we keep this so old
    moved types do not disappear.
    """
    if not GLOBAL_EXISTING_TYPES_FILE.exists():
        return []

    try:
        with GLOBAL_EXISTING_TYPES_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    cleaned = []

    for item in data:
        if not isinstance(item, dict):
            continue

        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()

        if key and label:
            cleaned.append({"key": key, "label": label})

    return cleaned


def save_global_existing_types(items: list[dict[str, str]]) -> None:
    GLOBAL_EXISTING_TYPES_FILE.parent.mkdir(parents=True, exist_ok=True)

    with GLOBAL_EXISTING_TYPES_FILE.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def load_active_classifier_routes() -> list[dict[str, str]]:
    """
    Main source for custom existing transcript types.

    When Ready -> Move to Existing is clicked, classifier_training.py creates or
    updates transcript_classifier_routes. Existing Transcript Type should read
    from this table so the moved type appears globally across all semesters,
    even when the selected semester has 0 files for that type.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(TranscriptClassifierRoute)
            .filter(TranscriptClassifierRoute.status == "active")
            .order_by(TranscriptClassifierRoute.display_name.asc())
            .all()
        )

        items: list[dict[str, str]] = []

        for row in rows:
            classifier_label = str(row.classifier_label or "").strip()
            display_name = str(row.display_name or "").strip()
            extractor_profile = str(row.extractor_profile or "").strip()

            if not classifier_label or not display_name:
                continue

            items.append(
                {
                    "key": classifier_label,
                    "label": display_name,
                    "extractor_profile": extractor_profile,
                    "source": "db_route",
                }
            )

        return items
    except Exception:
        logger.exception(
            "[TRANSCRIPT_DETECTOR] Failed to load active classifier routes."
        )
        return []
    finally:
        db.close()


def load_existing_type_registry(
    folder_keys_with_pdfs_any_semester: set[str],
) -> list[dict[str, str]]:
    """
    Merge:
      1. Active DB routes from transcript_classifier_routes.
      2. Legacy global JSON entries, only when they are still backed by PDFs.

    DB routes always show globally because they represent transcript types that
    were explicitly moved to Existing.
    """
    merged_by_key: dict[str, dict[str, str]] = {}

    for item in load_active_classifier_routes():
        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()

        if not key or not label:
            continue

        merged_by_key[normalize_folder_key(key)] = item

    for item in load_global_existing_types():
        if not should_show_legacy_global_existing_type(
            item,
            folder_keys_with_pdfs_any_semester,
        ):
            continue

        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()

        if not key or not label:
            continue

        normalized_key = normalize_folder_key(key)

        if normalized_key not in merged_by_key:
            merged_by_key[normalized_key] = {
                "key": key,
                "label": label,
                "extractor_profile": "",
                "source": "legacy_json",
            }

    return sorted(
        merged_by_key.values(),
        key=lambda item: sort_existing_type_label(item["label"]),
    )


def sort_existing_type_label(label: str):
    priority = {
        "Long Beach Unified District": 0,
        "Mayfair High School": 1,
        "St Anthony High School": 2,
    }

    return (priority.get(label, 100), label.lower())


def should_show_legacy_global_existing_type(
    item: dict[str, Any],
    folder_keys_with_pdfs_any_semester: set[str],
) -> bool:
    """
    For legacy JSON only.

    Old JSON entries should not create random empty folders on every semester
    unless they have PDFs somewhere. New DB routes do not use this rule because
    Move to Existing intentionally creates a global route.
    """
    key = str(item.get("key", "")).strip()
    label = str(item.get("label", "")).strip()

    if not key or not label:
        return False

    key_norm = normalize_folder_key(key)
    label_norm = normalize_folder_key(label)

    return (
        key_norm in folder_keys_with_pdfs_any_semester
        or label_norm in folder_keys_with_pdfs_any_semester
    )


def find_matching_existing_folder_name(
    semester: str,
    transcript_type_label: str,
) -> Optional[str]:
    client = get_storage_client()
    prefix = f"02_Library_Categorized_HS_Transcripts/{semester}/transcript/"

    target_key = normalize_folder_key(transcript_type_label)
    folder_names = set()

    for blob in client.list_blobs(GCS_BUCKET, prefix=prefix):
        parts = PurePosixPath(blob.name).parts

        if len(parts) < 4:
            continue

        folder_name = parts[3]

        if folder_name == "Others":
            continue

        folder_names.add(folder_name)

    for folder_name in folder_names:
        folder_key = normalize_folder_key(folder_name)
        label_key = normalize_folder_key(format_existing_type_label(folder_name))

        if target_key == folder_key or target_key == label_key:
            return folder_name

    return None


def deactivate_matching_classifier_route(transcript_type_label: str) -> None:
    """
    If user deletes a custom existing type from the Existing page, also disable
    the DB route so it no longer appears globally.
    """
    target_key = normalize_folder_key(transcript_type_label)

    db = SessionLocal()
    try:
        rows = (
            db.query(TranscriptClassifierRoute)
            .filter(TranscriptClassifierRoute.status == "active")
            .all()
        )

        changed = False

        for row in rows:
            label_key = normalize_folder_key(row.display_name or "")
            classifier_key = normalize_folder_key(row.classifier_label or "")

            if label_key == target_key or classifier_key == target_key:
                row.status = "inactive"
                changed = True

        if changed:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        logger.exception(
            "[TRANSCRIPT_DETECTOR] Failed to deactivate classifier route."
        )
    finally:
        db.close()


# ----------------------------
# Incoming
# ----------------------------

@router.get("/incoming/semesters")
def get_incoming_semesters():
    pdf_blobs = gcs_list_pdfs(GCS_BUCKET, GCS_INPUT_PREFIX)

    semesters = set()

    for blob_name in pdf_blobs:
        sem = get_semester_from_input_blob(blob_name)

        if sem:
            semesters.add(sem)

    return [
        {"label": semester, "value": semester}
        for semester in sorted(semesters)
    ]


@router.get("/incoming")
def get_incoming(semester: Optional[str] = Query(default=None)):
    pdf_blobs = gcs_list_pdfs(GCS_BUCKET, GCS_INPUT_PREFIX)

    grouped = defaultdict(list)

    for blob_name in pdf_blobs:
        p = PurePosixPath(blob_name)
        sem = get_semester_from_input_blob(blob_name)

        if semester and sem != semester:
            continue

        grouped[sem].append(
            {
                "id": blob_name,
                "name": p.stem,
                "file_name": p.name,
                "blob_name": blob_name,
            }
        )

    result = []

    for sem in sorted(grouped.keys()):
        files = grouped[sem]

        result.append(
            {
                "semester": sem,
                "count": len(files),
                "files": files,
            }
        )

    return result


@router.get("/incoming/file")
def open_incoming_file(blob_name: str = Query(...)):
    return stream_pdf(blob_name)


class IncomingDeleteRequest(BaseModel):
    blob_name: str


@router.post("/incoming/delete")
def delete_incoming_file(request: IncomingDeleteRequest):
    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(request.blob_name)

    if not blob.exists(client):
        raise HTTPException(status_code=404, detail="File not found in GCS.")

    blob.delete()

    removed_rows = _purge_orphan_rows_for_blobs({request.blob_name})

    return {
        "status": "success",
        "blob_name": request.blob_name,
        "removed_rows": removed_rows,
        "message": "Incoming transcript deleted successfully.",
    }


# ----------------------------
# Existing Transcript Type
# ----------------------------

@router.get("/existing")
def get_existing(semester: Optional[str] = Query(default=None)):
    client = get_storage_client()
    base_prefix = "02_Library_Categorized_HS_Transcripts/"

    grouped: dict[str, dict[str, Any]] = {}
    seen_semesters = set()
    folder_keys_with_pdfs_any_semester: set[str] = set()

    for b in client.list_blobs(GCS_BUCKET, prefix=base_prefix):
        name = b.name
        p = PurePosixPath(name)
        parts = p.parts

        if len(parts) < 4:
            continue

        root_folder = parts[0]
        file_semester = parts[1]
        category = parts[2]
        transcript_type = parts[3]

        if root_folder != "02_Library_Categorized_HS_Transcripts":
            continue

        if category != "transcript":
            continue

        if transcript_type == "Others":
            continue

        # Only PDFs count as files.
        if not name.lower().endswith(".pdf"):
            continue

        folder_keys_with_pdfs_any_semester.add(normalize_folder_key(transcript_type))
        folder_keys_with_pdfs_any_semester.add(
            normalize_folder_key(format_existing_type_label(transcript_type))
        )

        if semester and file_semester != semester:
            continue

        seen_semesters.add(file_semester)

        label = format_existing_type_label(transcript_type)

        if file_semester not in grouped:
            grouped[file_semester] = {
                "semester": file_semester,
                "types": {},
            }

        if label not in grouped[file_semester]["types"]:
            grouped[file_semester]["types"][label] = {
                "type": label,
                "classifier_label": None,
                "extractor_profile": None,
                "source": "gcs_folder",
                "files": [],
            }

        grouped[file_semester]["types"][label]["files"].append(
            {
                "id": name,
                "name": p.stem,
                "file_name": p.name,
                "blob_name": name,
            }
        )

    if semester:
        seen_semesters.add(semester)

    # If no semester is passed and GCS has no PDFs yet, still return a stable
    # empty group instead of nothing.
    if not seen_semesters and semester:
        seen_semesters.add(semester)

    existing_type_registry = load_existing_type_registry(
        folder_keys_with_pdfs_any_semester
    )

    for sem in seen_semesters:
        if sem not in grouped:
            grouped[sem] = {
                "semester": sem,
                "types": {},
            }

        # Always show the 3 default folders first for the selected semester.
        for folder_name in KNOWN_TRANSCRIPT_FOLDERS:
            label = format_existing_type_label(folder_name)

            if label not in grouped[sem]["types"]:
                grouped[sem]["types"][label] = {
                    "type": label,
                    "classifier_label": folder_name,
                    "extractor_profile": None,
                    "source": "default_known",
                    "files": [],
                }

        # Show DB routes globally across all semesters.
        # This is what makes Cypress appear after Ready -> Move to Existing,
        # even when the selected semester has 0 Cypress files.
        for item in existing_type_registry:
            label = item["label"]

            if label not in grouped[sem]["types"]:
                grouped[sem]["types"][label] = {
                    "type": label,
                    "classifier_label": item.get("key"),
                    "extractor_profile": item.get("extractor_profile"),
                    "source": item.get("source", "db_route"),
                    "files": [],
                }
            else:
                grouped[sem]["types"][label]["classifier_label"] = (
                    grouped[sem]["types"][label].get("classifier_label")
                    or item.get("key")
                )
                grouped[sem]["types"][label]["extractor_profile"] = (
                    grouped[sem]["types"][label].get("extractor_profile")
                    or item.get("extractor_profile")
                )
                grouped[sem]["types"][label]["source"] = (
                    grouped[sem]["types"][label].get("source")
                    or item.get("source", "db_route")
                )

    result = []

    for sem in sorted(grouped.keys()):
        semester_entry = grouped[sem]
        type_rows = []

        for label in sorted(
            semester_entry["types"].keys(),
            key=sort_existing_type_label,
        ):
            type_entry = semester_entry["types"][label]
            files = sorted(
                type_entry["files"],
                key=lambda x: x["name"].lower(),
            )

            type_rows.append(
                {
                    "type": label,
                    "count": len(files),
                    "files": files,
                    "classifier_label": type_entry.get("classifier_label"),
                    "extractor_profile": type_entry.get("extractor_profile"),
                    "source": type_entry.get("source"),
                    "is_global_route": type_entry.get("source") == "db_route",
                }
            )

        result.append(
            {
                "semester": sem,
                "types": type_rows,
            }
        )

    return result


@router.get("/existing/file")
def open_existing_file(blob_name: str = Query(...)):
    return stream_pdf(blob_name)


class ExistingFileDeleteRequest(BaseModel):
    blob_name: str


@router.post("/existing/delete-file")
def delete_existing_file(request: ExistingFileDeleteRequest):
    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(request.blob_name)

    if not blob.exists(client):
        raise HTTPException(status_code=404, detail="File not found in GCS.")

    blob.delete()

    removed_rows = _purge_orphan_rows_for_blobs({request.blob_name})

    return {
        "status": "success",
        "blob_name": request.blob_name,
        "removed_rows": removed_rows,
        "message": "Existing transcript file deleted successfully.",
    }


class ExistingFolderDeleteRequest(BaseModel):
    semester: str
    transcript_type: str


@router.post("/existing/delete-folder")
def delete_existing_folder(request: ExistingFolderDeleteRequest):
    client = get_storage_client()

    target_key = normalize_folder_key(request.transcript_type)

    folder_name = find_matching_existing_folder_name(
        semester=request.semester,
        transcript_type_label=request.transcript_type,
    )

    deleted_count = 0

    if folder_name:
        prefix = (
            "02_Library_Categorized_HS_Transcripts/"
            f"{request.semester}/transcript/{folder_name}/"
        )

        blobs = list(client.list_blobs(GCS_BUCKET, prefix=prefix))

        deleted_blob_names: set[str] = set()
        for blob in blobs:
            deleted_blob_names.add(blob.name)
            blob.delete()
            deleted_count += 1

        # Drop any 'uploaded' rows orphaned by this folder deletion so they don't
        # linger as "Not Processed" ghosts.
        _purge_orphan_rows_for_blobs(deleted_blob_names)

    # Remove legacy JSON entry if it exists.
    items = load_global_existing_types()
    filtered = []

    for item in items:
        item_label = str(item.get("label", ""))
        item_key = str(item.get("key", ""))

        if (
            normalize_folder_key(item_label) == target_key
            or normalize_folder_key(item_key) == target_key
        ):
            continue

        filtered.append(item)

    save_global_existing_types(filtered)

    # Also deactivate DB route if this was a moved custom existing type.
    deactivate_matching_classifier_route(request.transcript_type)

    return {
        "status": "success",
        "folder_name": folder_name,
        "deleted_count": deleted_count,
        "message": f"Deleted existing type '{request.transcript_type}' successfully.",
    }


# ----------------------------
# New Transcript Type
# ----------------------------

def sync_new_type_folders_to_needs_setup(grouped_result: list[dict[str, Any]]) -> None:
    """
    Bridge between the New Transcript Type page and the Needs Setup page.

    New Transcript Type reads GCS folders from:
      Others/Grouped_by_school/<school>/

    Needs Setup reads DB rows from:
      transcript_school_types

    This sync keeps the existing New Transcript Type response unchanged while
    also inserting/updating DB rows for the new classifier setup flow.
    """

    try:
        from app.services.transcript_school_type_onboarding_service import (
            sync_grouped_school_folder,
        )

        db = SessionLocal()

        try:
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

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    except Exception:
        logger.exception(
            "[TRANSCRIPT_DETECTOR] Failed to sync grouped school folders "
            "into transcript_school_types."
        )


def read_grouped_school_folders_for_new_types(semester: Optional[str] = None):
    client = get_storage_client()
    base_prefix = "02_Library_Categorized_HS_Transcripts/"

    grouped: dict[str, dict[str, Any]] = {}

    for b in client.list_blobs(GCS_BUCKET, prefix=base_prefix):
        name = b.name

        if not name.lower().endswith(".pdf"):
            continue

        p = PurePosixPath(name)
        parts = p.parts

        if len(parts) < 5:
            continue

        root_folder = parts[0]
        file_semester = parts[1]
        category = parts[2]
        others_folder = parts[3]

        if root_folder != "02_Library_Categorized_HS_Transcripts":
            continue

        if semester and file_semester != semester:
            continue

        if category != "transcript":
            continue

        if others_folder != "Others":
            continue

        # Two shapes live under transcript/Others/:
        #   .../Others/Grouped_by_school/<school>/<file>.pdf → clustered new type
        #   .../Others/<file>.pdf → classified as Others but not yet clustered
        #     (e.g. the upload-time auto-classify guard drops files here). Without
        #     this, those files show in NO bucket and look lost. Surface them as a
        #     pending group (empty folder name) so they appear in Needs AI
        #     Extractor; the frontend leaves their format blank until clustering
        #     assigns a school.
        if len(parts) >= 7 and parts[4] == "Grouped_by_school":
            folder_name = parts[5]
        elif len(parts) == 5:
            folder_name = ""
        else:
            continue

        if file_semester not in grouped:
            grouped[file_semester] = {
                "semester": file_semester,
                "folders": {},
            }

        if folder_name not in grouped[file_semester]["folders"]:
            grouped[file_semester]["folders"][folder_name] = []

        grouped[file_semester]["folders"][folder_name].append(
            {
                "id": name,
                "name": p.stem,
                "file_name": p.name,
                "blob_name": name,
            }
        )

    result = []

    for sem in sorted(grouped.keys()):
        semester_entry = grouped[sem]
        folder_rows = []

        for folder_name in sorted(semester_entry["folders"].keys()):
            files = sorted(
                semester_entry["folders"][folder_name],
                key=lambda x: x["name"].lower(),
            )

            folder_rows.append(
                {
                    "folder_name": folder_name,
                    "count": len(files),
                    "files": files,
                }
            )

        result.append(
            {
                "semester": sem,
                "folders": folder_rows,
            }
        )

    sync_new_type_folders_to_needs_setup(result)

    return result


@router.get("/new")
def get_new(semester: Optional[str] = Query(default=None)):
    return read_grouped_school_folders_for_new_types(semester)


@router.get("/new/file")
def open_new_file(blob_name: str = Query(...)):
    return stream_pdf(blob_name)


# ----------------------------
# Unknown Transcript Type
# ----------------------------

def read_unknown_files(semester: Optional[str] = None):
    client = get_storage_client()
    base_prefix = "02_Library_Categorized_HS_Transcripts/"

    grouped: dict[str, dict[str, Any]] = {}

    for b in client.list_blobs(GCS_BUCKET, prefix=base_prefix):
        name = b.name

        if not name.lower().endswith(".pdf"):
            continue

        p = PurePosixPath(name)
        parts = p.parts

        if len(parts) != 4:
            continue

        root_folder = parts[0]
        file_semester = parts[1]
        category = parts[2]
        file_name = parts[3]

        if root_folder != "02_Library_Categorized_HS_Transcripts":
            continue

        if semester and file_semester != semester:
            continue

        if category != "not_a_transcript":
            continue

        if file_semester not in grouped:
            grouped[file_semester] = {
                "semester": file_semester,
                "count": 0,
                "files": [],
            }

        grouped[file_semester]["files"].append(
            {
                "id": name,
                "name": PurePosixPath(file_name).stem,
                "file_name": file_name,
                "blob_name": name,
            }
        )

        grouped[file_semester]["count"] += 1

    # A term's uploaded handbook isn't a transcript either, so surface it here
    # too. It STAYS in 01_.../<term>/handbook/ (admission-rule extraction still
    # reads it from there) — we only list it, never move it.
    for b in client.list_blobs(GCS_BUCKET, prefix=GCS_INPUT_PREFIX):
        name = b.name
        if not name.lower().endswith(".pdf"):
            continue
        parts = PurePosixPath(name).parts
        # 01_Inbox_Raw_HS_Transcripts/<term>/handbook/<file>.pdf
        if len(parts) < 4 or parts[2].lower() != "handbook":
            continue
        file_semester = parts[1]
        if semester and file_semester != semester:
            continue
        hb_name = parts[-1]
        if file_semester not in grouped:
            grouped[file_semester] = {
                "semester": file_semester,
                "count": 0,
                "files": [],
            }
        grouped[file_semester]["files"].append(
            {
                "id": name,
                "name": PurePosixPath(hb_name).stem,
                "file_name": hb_name,
                "blob_name": name,
            }
        )
        grouped[file_semester]["count"] += 1

    return sorted(grouped.values(), key=lambda x: x["semester"])


@router.get("/unknown")
def get_unknown(semester: Optional[str] = Query(default=None)):
    return read_unknown_files(semester)


@router.get("/unknown/file")
def open_unknown_file(blob_name: str = Query(...)):
    return stream_pdf(blob_name)
