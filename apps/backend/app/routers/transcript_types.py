from pathlib import PurePosixPath, Path
from typing import List, Dict, Any, Optional

import os
import re
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from google.cloud import storage
from pydantic import BaseModel
from sqlalchemy import select

from app import models
from app.db import AsyncSessionLocal
from app.services.transcript_processor import (
    ProcessorConfig,
    ExtractionContext,
    TranscriptProcessor,
)

router = APIRouter(prefix="/transcript-types", tags=["transcript-types"])

GCS_BUCKET = "doc-ai-transcript-us-central1-v1-001"
GLOBAL_EXISTING_TYPES_FILE = Path("app/data/global_existing_types.json")

READY_FOLDER_TO_CLASSIFIER = {
    "LBUSD": "lbusd",
    "Mayfair_High_School": "mayfair_high_school",
    "St_Anthony_High_School": "st_anthony_high_school",
}


def get_storage_client() -> storage.Client:
    return storage.Client()


def build_prefix(semester: str, stage: str) -> str:
    return f"02_Library_Categorized_HS_Transcripts/{semester}/transcript/Others/{stage}/"


def sanitize_folder_name(folder_name: str) -> str:
    name = str(folder_name or "").strip().lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s-]+", "_", name)
    return name


def normalize_registry_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def make_display_label(folder_name: str) -> str:
    special = {
        "LBUSD": "Long Beach Unified District",
        "Mayfair_High_School": "Mayfair High School",
        "St_Anthony_High_School": "St Anthony High School",
        "lbusd": "Long Beach Unified District",
        "mayfair_high_school": "Mayfair High School",
        "st_anthony_high_school": "St Anthony High School",
    }

    if folder_name in special:
        return special[folder_name]

    return folder_name.replace("_", " ").title()


def load_global_existing_types() -> List[Dict[str, str]]:
    if not GLOBAL_EXISTING_TYPES_FILE.exists():
        return []

    with GLOBAL_EXISTING_TYPES_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return []

    cleaned: List[Dict[str, str]] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()

        if key and label:
            cleaned.append({"key": key, "label": label})

    return cleaned


def save_global_existing_types(items: List[Dict[str, str]]) -> None:
    GLOBAL_EXISTING_TYPES_FILE.parent.mkdir(parents=True, exist_ok=True)

    unique: Dict[str, Dict[str, str]] = {}

    for item in items:
        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()

        if not key or not label:
            continue

        normalized = normalize_registry_key(key) or normalize_registry_key(label)

        if normalized and normalized not in unique:
            unique[normalized] = {"key": key, "label": label}

    cleaned_items = sorted(unique.values(), key=lambda x: x["label"].lower())

    with GLOBAL_EXISTING_TYPES_FILE.open("w", encoding="utf-8") as f:
        json.dump(cleaned_items, f, indent=2)


def register_global_existing_type(folder_name: str) -> Dict[str, str]:
    raw_folder_name = str(folder_name or "").strip()

    if not raw_folder_name:
        raise HTTPException(status_code=400, detail="Folder name is required.")

    key = sanitize_folder_name(raw_folder_name)
    label = make_display_label(key)

    target_key = normalize_registry_key(key)
    target_label = normalize_registry_key(label)

    items = load_global_existing_types()

    for item in items:
        existing_key = normalize_registry_key(item.get("key", ""))
        existing_label = normalize_registry_key(item.get("label", ""))

        if existing_key in {target_key, target_label} or existing_label in {target_key, target_label}:
            return {
                "key": item["key"],
                "label": item["label"],
            }

    items.append({"key": key, "label": label})
    save_global_existing_types(items)

    return {"key": key, "label": label}


def list_all_semesters() -> List[str]:
    client = get_storage_client()
    base_prefix = "02_Library_Categorized_HS_Transcripts/"
    semesters = set()

    for blob in client.list_blobs(GCS_BUCKET, prefix=base_prefix):
        parts = PurePosixPath(blob.name).parts

        if len(parts) >= 2 and parts[0] == "02_Library_Categorized_HS_Transcripts":
            semesters.add(parts[1])

    return sorted(semesters)


def ensure_existing_type_folder_for_all_semesters(
    folder_name: str,
    current_semester: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)

    semesters = set(list_all_semesters())

    if current_semester:
        semesters.add(current_semester)

    created = []
    already_present = []

    for semester in sorted(semesters):
        keep_blob_name = (
            f"02_Library_Categorized_HS_Transcripts/"
            f"{semester}/transcript/{folder_name}/.keep"
        )

        blob = bucket.blob(keep_blob_name)

        if blob.exists(client):
            already_present.append(semester)
            continue

        blob.upload_from_string("", content_type="text/plain")
        created.append(semester)

    return {
        "folder_name": folder_name,
        "created_for_semesters": created,
        "already_present_for_semesters": already_present,
    }


# A trailing "_<n>" on an otherwise identical folder name is how the layout
# clusterer disambiguated a school it over-split into several clusters
# (e.g. "cypress_high_school" + "cypress_high_school_2"). These are the same
# school and should surface as ONE type on Needs Setup.
_SUFFIX_VARIANT_RE = re.compile(r"^(.*)_(\d+)$")


def _merge_oversplit_siblings(
    grouped: Dict[str, List[Dict[str, str]]],
) -> Dict[str, List[Dict[str, str]]]:
    """Collapse "base_<n>" folders into "base" when the un-suffixed base also
    exists in the same listing. Gating on the base's presence avoids falsely
    merging schools whose name legitimately ends in a number. Each file keeps
    its true blob name, so per-file actions still resolve to the right object."""
    merged: Dict[str, List[Dict[str, str]]] = {}
    for folder_name, files in grouped.items():
        m = _SUFFIX_VARIANT_RE.match(folder_name)
        base = m.group(1) if (m and m.group(1) in grouped) else folder_name
        merged.setdefault(base, []).extend(files)
    return merged


def _sibling_type_folders(root_prefix: str, folder_name: str) -> List[str]:
    """`folder_name` plus any "<folder_name>_<n>" over-split variants that
    physically exist under `root_prefix`, so folder-level move/delete operate on
    the whole logical type rather than orphaning a "_2" sibling."""
    client = get_storage_client()
    sib_re = re.compile(rf"^{re.escape(folder_name)}_\d+$")
    names: set = set()
    for blob in client.list_blobs(GCS_BUCKET, prefix=root_prefix):
        rel = blob.name[len(root_prefix):]
        if "/" not in rel:
            continue
        top = rel.split("/", 1)[0]
        if top == folder_name or sib_re.match(top):
            names.add(top)
    return sorted(names)


def read_grouped_folder(prefix: str) -> List[Dict[str, Any]]:
    client = get_storage_client()
    grouped: Dict[str, List[Dict[str, str]]] = {}

    for blob in client.list_blobs(GCS_BUCKET, prefix=prefix):
        blob_name = blob.name

        if blob_name.endswith("/"):
            continue

        rel = PurePosixPath(blob_name).relative_to(PurePosixPath(prefix))
        parts = rel.parts

        if len(parts) != 2:
            continue

        folder_name, file_name = parts

        if not file_name.lower().endswith(".pdf"):
            continue

        if folder_name not in grouped:
            grouped[folder_name] = []

        grouped[folder_name].append(
            {
                "id": blob_name,
                "name": PurePosixPath(file_name).stem,
                "file_name": file_name,
                "blob_name": blob_name,
            }
        )

    grouped = _merge_oversplit_siblings(grouped)
    rows = []

    for folder_name in sorted(grouped.keys()):
        files = sorted(grouped[folder_name], key=lambda x: x["name"].lower())

        rows.append(
            {
                "id": folder_name,
                "transcript_type": folder_name,
                "count": len(files),
                "files": files,
            }
        )

    return rows


def read_grouped_folder_all_semesters(stage: str) -> List[Dict[str, Any]]:
    client = get_storage_client()
    base_prefix = "02_Library_Categorized_HS_Transcripts/"
    grouped: Dict[str, List[Dict[str, str]]] = {}

    for blob in client.list_blobs(GCS_BUCKET, prefix=base_prefix):
        blob_name = blob.name

        if blob_name.endswith("/") or not blob_name.lower().endswith(".pdf"):
            continue

        parts = PurePosixPath(blob_name).parts

        if len(parts) < 7:
            continue

        root_folder = parts[0]
        semester = parts[1]
        transcript_folder = parts[2]
        others_folder = parts[3]
        stage_folder = parts[4]
        folder_name = parts[5]
        file_name = parts[6]

        if root_folder != "02_Library_Categorized_HS_Transcripts":
            continue

        if transcript_folder != "transcript":
            continue

        if others_folder != "Others":
            continue

        if stage_folder != stage:
            continue

        if folder_name not in grouped:
            grouped[folder_name] = []

        grouped[folder_name].append(
            {
                "id": blob_name,
                "name": PurePosixPath(file_name).stem,
                "file_name": file_name,
                "blob_name": blob_name,
                "semester": semester,
            }
        )

    grouped = _merge_oversplit_siblings(grouped)
    rows = []

    for folder_name in sorted(grouped.keys()):
        files = sorted(
            grouped[folder_name],
            key=lambda x: (x.get("semester", ""), x["name"].lower()),
        )

        rows.append(
            {
                "id": folder_name,
                "transcript_type": folder_name,
                "count": len(files),
                "files": files,
            }
        )

    return rows


def move_folder_between_prefixes(
    source_root: str,
    target_root: str,
    folder_name: str,
) -> Dict[str, Any]:
    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)

    # Move the canonical folder AND any over-split "_<n>" siblings, landing every
    # file in the single canonical target folder so the duplicate is healed.
    source_folders = _sibling_type_folders(source_root, folder_name) or [folder_name]
    target_prefix = f"{target_root}{folder_name}/"

    moved_count = 0

    for src_folder in source_folders:
        source_prefix = f"{source_root}{src_folder}/"
        for blob in client.list_blobs(GCS_BUCKET, prefix=source_prefix):
            filename = PurePosixPath(blob.name).name
            if not filename:
                continue
            new_name = f"{target_prefix}{filename}"
            bucket.copy_blob(blob, bucket, new_name=new_name)
            blob.delete()
            moved_count += 1

    if moved_count == 0:
        raise HTTPException(status_code=404, detail="Folder not found or empty.")

    return {
        "status": "success",
        "folder_name": folder_name,
        "moved_count": moved_count,
    }


def promote_ready_folder_to_existing_transcript_type(
    semester: str,
    folder_name: str,
) -> Dict[str, Any]:
    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)

    source_prefix = (
        f"02_Library_Categorized_HS_Transcripts/"
        f"{semester}/transcript/Others/Ready/{folder_name}/"
    )

    target_folder_name = sanitize_folder_name(folder_name)

    target_prefix = (
        f"02_Library_Categorized_HS_Transcripts/"
        f"{semester}/transcript/{target_folder_name}/"
    )

    blobs = list(client.list_blobs(GCS_BUCKET, prefix=source_prefix))

    if not blobs:
        raise HTTPException(status_code=404, detail="Ready folder not found or empty.")

    moved_count = 0

    for blob in blobs:
        old_name = blob.name
        filename = PurePosixPath(old_name).name

        if not filename:
            continue

        new_name = f"{target_prefix}{filename}"

        bucket.copy_blob(blob, bucket, new_name=new_name)
        blob.delete()
        moved_count += 1

    return {
        "status": "success",
        "folder_name": folder_name,
        "target_folder_name": target_folder_name,
        "moved_count": moved_count,
    }


def delete_folder_under_prefix(prefix: str, folder_name: str) -> Dict[str, Any]:
    client = get_storage_client()

    # Delete the canonical folder AND any over-split "_<n>" siblings so the
    # merged type disappears entirely rather than leaving a "_2" orphan behind.
    folders = _sibling_type_folders(prefix, folder_name) or [folder_name]

    deleted_count = 0
    deleted_blob_names: set[str] = set()

    for fname in folders:
        for blob in client.list_blobs(GCS_BUCKET, prefix=f"{prefix}{fname}/"):
            deleted_blob_names.add(blob.name)
            blob.delete()
            deleted_count += 1

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Folder not found or empty.")

    # Drop any 'uploaded' rows orphaned by this deletion so they don't linger as
    # "Not Processed" ghosts.
    from app.services.orphan_cleanup import purge_orphan_rows_for_blobs
    purge_orphan_rows_for_blobs(deleted_blob_names)

    return {
        "status": "success",
        "folder_name": folder_name,
        "deleted_count": deleted_count,
    }


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
        iter([file_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def get_folder_files(prefix: str, folder_name: str) -> List[Dict[str, Any]]:
    rows = read_grouped_folder(prefix)

    for row in rows:
        if row["transcript_type"] == folder_name:
            return row["files"]

    return []


async def get_classifier_row_by_name(classifier_name: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.ClassifiersType).where(
                models.ClassifiersType.classifier_name == classifier_name
            )
        )

        return result.scalar_one_or_none()


class FolderActionRequest(BaseModel):
    folder_name: str
    semester: str
    apply_to_all_semesters: bool = True


@router.get("/needs-setup")
def get_needs_setup(semester: str = Query(...)) -> List[Dict[str, Any]]:
    if semester == "ALL":
        return read_grouped_folder_all_semesters("Grouped_by_school")

    prefix = build_prefix(semester, "Grouped_by_school")
    return read_grouped_folder(prefix)


@router.get("/in-setup")
def get_in_setup(semester: str = Query(...)) -> List[Dict[str, Any]]:
    if semester == "ALL":
        return read_grouped_folder_all_semesters("In_Setup")

    prefix = build_prefix(semester, "In_Setup")
    return read_grouped_folder(prefix)


@router.get("/ready")
def get_ready(semester: str = Query(...)) -> List[Dict[str, Any]]:
    if semester == "ALL":
        return read_grouped_folder_all_semesters("Ready")

    prefix = build_prefix(semester, "Ready")
    return read_grouped_folder(prefix)


@router.get("/existing")
def get_existing_new_types(semester: str = Query(...)) -> List[Dict[str, Any]]:
    if semester == "ALL":
        return read_grouped_folder_all_semesters("Existing")

    prefix = build_prefix(semester, "Existing")
    return read_grouped_folder(prefix)


@router.get("/needs-setup/file")
def open_needs_setup_file(
    semester: str = Query(...),
    blob_name: str = Query(...),
) -> StreamingResponse:
    return stream_pdf(blob_name)


@router.get("/in-setup/file")
def open_in_setup_file(
    semester: str = Query(...),
    blob_name: str = Query(...),
) -> StreamingResponse:
    return stream_pdf(blob_name)


@router.get("/ready/file")
def open_ready_file(
    semester: str = Query(...),
    blob_name: str = Query(...),
) -> StreamingResponse:
    return stream_pdf(blob_name)


@router.get("/existing/file")
def open_existing_file(
    semester: str = Query(...),
    blob_name: str = Query(...),
) -> StreamingResponse:
    return stream_pdf(blob_name)


@router.post("/needs-setup/move-to-setup")
def move_needs_setup_to_in_setup(request: FolderActionRequest):
    if request.semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to move folders.",
        )

    source_prefix = build_prefix(request.semester, "Grouped_by_school")
    target_prefix = build_prefix(request.semester, "In_Setup")

    result = move_folder_between_prefixes(
        source_prefix,
        target_prefix,
        request.folder_name,
    )

    result["message"] = f"{request.folder_name} moved to In Setup for {request.semester}."

    return result


@router.post("/in-setup/move-to-ready")
def move_in_setup_to_ready(request: FolderActionRequest):
    if request.semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to move folders.",
        )

    source_prefix = build_prefix(request.semester, "In_Setup")
    target_prefix = build_prefix(request.semester, "Ready")

    result = move_folder_between_prefixes(
        source_prefix,
        target_prefix,
        request.folder_name,
    )

    result["message"] = f"{request.folder_name} moved to Ready for {request.semester}."

    return result


@router.post("/ready/move-to-existing")
def move_ready_to_existing(request: FolderActionRequest):
    if request.semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to move folders.",
        )

    result = promote_ready_folder_to_existing_transcript_type(
        semester=request.semester,
        folder_name=request.folder_name,
    )

    target_folder_name = result["target_folder_name"]

    registered_type = register_global_existing_type(target_folder_name)

    ensured = None

    if request.apply_to_all_semesters:
        ensured = ensure_existing_type_folder_for_all_semesters(
            folder_name=target_folder_name,
            current_semester=request.semester,
        )

    result["registered_type"] = registered_type
    result["ensured_folders"] = ensured

    if request.apply_to_all_semesters:
        result["message"] = (
            f"{request.folder_name} moved to transcript/{target_folder_name} "
            f"for {request.semester}. Existing type '{registered_type['label']}' "
            f"was registered and added across all semesters."
        )
    else:
        result["message"] = (
            f"{request.folder_name} moved to transcript/{target_folder_name} "
            f"for {request.semester}."
        )

    return result


@router.post("/needs-setup/delete")
def delete_needs_setup_folder(request: FolderActionRequest):
    if request.semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to delete folders.",
        )

    prefix = build_prefix(request.semester, "Grouped_by_school")
    result = delete_folder_under_prefix(prefix, request.folder_name)
    result["message"] = f"{request.folder_name} deleted from Needs Setup for {request.semester}."

    return result


@router.post("/in-setup/delete")
def delete_in_setup_folder(request: FolderActionRequest):
    if request.semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to delete folders.",
        )

    prefix = build_prefix(request.semester, "In_Setup")
    result = delete_folder_under_prefix(prefix, request.folder_name)
    result["message"] = f"{request.folder_name} deleted from In Setup for {request.semester}."

    return result


@router.post("/ready/delete")
def delete_ready_folder(request: FolderActionRequest):
    if request.semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to delete folders.",
        )

    prefix = build_prefix(request.semester, "Ready")
    result = delete_folder_under_prefix(prefix, request.folder_name)
    result["message"] = f"{request.folder_name} deleted from Ready for {request.semester}."

    return result


@router.get("/ready/extractor-availability")
async def get_ready_extractor_availability(semester: str = Query(...)) -> Dict[str, Any]:
    if semester == "ALL":
        raise HTTPException(status_code=400, detail="Please select a specific term.")

    ready_prefix = build_prefix(semester, "Ready")
    rows = read_grouped_folder(ready_prefix)
    items = []

    for row in rows:
        folder_name = row["transcript_type"]
        classifier_name = READY_FOLDER_TO_CLASSIFIER.get(folder_name)

        extractor_available = False
        processor_id = None

        if classifier_name:
            classifier_row = await get_classifier_row_by_name(classifier_name)

            if classifier_row and getattr(classifier_row, "processor_id", None):
                extractor_available = True
                processor_id = classifier_row.processor_id

        items.append(
            {
                "folder_name": folder_name,
                "classifier_name": classifier_name,
                "extractor_available": extractor_available,
                "processor_id": processor_id,
            }
        )

    return {"items": items}


# ---------------------------------------------------------------------------
# Document AI processor integration
#
# Mirrors the Doc AI console onto the In Setup / Ready pages and lets a trained
# extraction processor be wired into the app in one click: it provisions the
# classifier_type registry row, the GCS transcript/<type>/ folder, and the global
# existing-types entry — the same shape LBUSD / Mayfair / St. Anthony already use.
# ---------------------------------------------------------------------------

class IntegrateProcessorRequest(BaseModel):
    processor_id: str
    display_name: Optional[str] = None
    classifier_name: Optional[str] = None  # optional explicit type name


def _provision_type_folders(classifier_name: str) -> List[str]:
    """Create a transcript/<classifier_name>/ folder marker under every semester
    so routed transcripts of this type have a home (mirrors the existing types)."""
    client = get_storage_client()
    bucket = client.bucket(GCS_BUCKET)
    created: List[str] = []

    semesters = list_all_semesters() or []
    for semester in semesters:
        marker = (
            f"02_Library_Categorized_HS_Transcripts/{semester}"
            f"/transcript/{classifier_name}/.keep"
        )
        blob = bucket.blob(marker)
        if not blob.exists():
            blob.upload_from_string(b"", content_type="text/plain")
        created.append(f"02_Library_Categorized_HS_Transcripts/{semester}/transcript/{classifier_name}/")

    return created


@router.get("/processors")
async def list_docai_processors() -> Dict[str, Any]:
    """List custom-extraction Doc AI processors bucketed by lifecycle (ready /
    in_setup), annotated with whether each is already integrated into the app."""
    import asyncio
    from app.services.docai_processor_service import (
        list_extraction_processors,
        docai_project,
        docai_location,
    )

    try:
        processors = await asyncio.to_thread(list_extraction_processors)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to list Document AI processors: {exc}",
        )

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(models.ClassifiersType))).scalars().all()

    integrated_by_pid = {r.processor_id: r for r in rows}

    ready: List[Dict[str, Any]] = []
    in_setup: List[Dict[str, Any]] = []

    for proc in processors:
        existing = integrated_by_pid.get(proc["id"])
        proc["integrated"] = existing is not None
        proc["classifier_name"] = (
            existing.classifier_name if existing else sanitize_folder_name(proc["display_name"])
        )
        proc["label"] = make_display_label(proc["classifier_name"])
        (ready if proc["lifecycle"] == "ready" else in_setup).append(proc)

    return {
        "ready": ready,
        "in_setup": in_setup,
        "project": docai_project(),
        "location": docai_location(),
    }


@router.get("/classifier-labels")
async def list_classifier_labels() -> Dict[str, Any]:
    """Return the layout classifier's actual transcript-type labels (from its
    dataset schema), each with its derived key and whether it's already
    integrated — so Integrate can offer the real labels instead of free text."""
    import asyncio
    from app.services.docai_processor_service import list_layout_classifier_labels
    from app.services.classifier_registry import sanitize_classifier_key

    try:
        labels = await asyncio.to_thread(list_layout_classifier_labels)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Failed to read classifier labels: {exc}",
        )

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(models.ClassifiersType.classifier_name))
        ).scalars().all()
    integrated = {str(r).strip().lower() for r in rows if r}

    items = []
    for label in labels:
        key = sanitize_classifier_key(label)
        # "Others" is the catch-all bucket, not an integratable type.
        if key in ("others", "other"):
            continue
        items.append({"label": label, "key": key, "integrated": key in integrated})

    return {"labels": items}


@router.get("/classifier/groups")
async def list_classifier_groups() -> Dict[str, Any]:
    """New layout groups currently collecting in Needs Setup, with their progress
    toward the auto-train threshold and any training-job status."""
    import asyncio
    from sqlalchemy import text as _text
    from app.services.classifier_autotrain_service import scan_groups, threshold, ensure_table

    try:
        groups = await asyncio.to_thread(scan_groups)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to scan groups: {exc}")

    ensure_table()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                _text("SELECT group_key, status, message FROM classifier_training_jobs")
            )
        ).mappings().all()
    jobs = {r["group_key"]: dict(r) for r in rows}

    thr = threshold()
    items = []
    for g in groups:
        job = jobs.get(g["key"]) or {}
        items.append(
            {
                "key": g["key"],
                "label": g["label"],
                "semester": g["semester"],
                "doc_count": g["doc_count"],
                "threshold": thr,
                "status": job.get("status")
                or ("ready" if g["doc_count"] >= thr else "collecting"),
                "message": job.get("message"),
            }
        )
    items.sort(key=lambda x: -x["doc_count"])
    return {"groups": items, "threshold": thr}


@router.post("/integrate")
async def integrate_processor(request: IntegrateProcessorRequest) -> Dict[str, Any]:
    """Integrate a trained Doc AI extraction processor into the app backend."""
    import asyncio
    from app.services.docai_processor_service import list_extraction_processors

    processor_id = (request.processor_id or "").strip()
    if not processor_id:
        raise HTTPException(status_code=400, detail="processor_id is required.")

    # Verify the processor exists and is actually trained (has a deployed version).
    try:
        processors = await asyncio.to_thread(list_extraction_processors)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to query Document AI: {exc}")

    proc = next((p for p in processors if p["id"] == processor_id), None)
    if proc is None:
        raise HTTPException(
            status_code=404,
            detail="Processor not found among custom extraction processors.",
        )
    if not proc.get("trained"):
        raise HTTPException(
            status_code=400,
            detail="Processor has no trained version deployed yet — it is still in setup.",
        )

    # The type key ties the whole loop together: it must equal the *sanitized
    # classifier label* the layout classifier emits for this type, because that
    # same value is the transcript/<key>/ folder and the routing lookup key. The
    # frontend sends it (defaulted to the sanitized processor name, editable).
    from app.services.classifier_registry import sanitize_classifier_key

    classifier_name = sanitize_classifier_key(
        request.classifier_name or request.display_name or proc["display_name"]
    )
    if not classifier_name:
        raise HTTPException(status_code=400, detail="Could not derive a transcript type name.")

    label = make_display_label(classifier_name)

    # 1) Upsert the classifier_type registry row. status embeds the name to keep
    #    the column's unique constraint satisfied (matches the enabled_<name>
    #    convention used by the existing LBUSD/Mayfair/St. Anthony rows).
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(models.ClassifiersType).where(
                    (models.ClassifiersType.classifier_name == classifier_name)
                    | (models.ClassifiersType.processor_id == processor_id)
                )
            )
        ).scalars().first()

        if existing:
            existing.classifier_name = classifier_name
            existing.processor_id = processor_id
            existing.status = f"enabled_{classifier_name}"
        else:
            session.add(
                models.ClassifiersType(
                    classifier_name=classifier_name,
                    processor_id=processor_id,
                    status=f"enabled_{classifier_name}",
                )
            )
        await session.commit()

    # 2) Provision the GCS transcript/<type>/ folder(s).
    created_folders = _provision_type_folders(classifier_name)

    # 3) Register in the global existing-types registry.
    registry_entry = register_global_existing_type(classifier_name)

    # 4) Refresh the routing cache so new uploads of this type are detected
    #    and routed to this processor without a redeploy.
    try:
        from app.routers.cloud_folder_locations import invalidate_dynamic_classifier_cache

        invalidate_dynamic_classifier_cache()
    except Exception:  # noqa: BLE001 — cache refresh is best-effort
        pass

    try:
        from app.services.notification_service import notify
        notify(
            f"Extractor integrated: {label}",
            f"Processor '{proc['display_name']}' is now linked to transcript/{classifier_name}/. "
            f"{len(created_folders)} folder(s) created. Transcripts of this type will be routed "
            f"to this extractor.",
            level="success",
            category="integration",
            meta={"classifier_name": classifier_name, "processor_id": processor_id},
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "processor_id": processor_id,
        "classifier_name": classifier_name,
        "label": label,
        "created_folders": created_folders,
        "registry": registry_entry,
    }


@router.post("/ready/extract")
async def extract_ready_folder(request: FolderActionRequest):
    folder_name = request.folder_name
    semester = request.semester

    if semester == "ALL":
        raise HTTPException(
            status_code=400,
            detail="Please select a specific term to extract.",
        )

    classifier_name = READY_FOLDER_TO_CLASSIFIER.get(folder_name)

    if not classifier_name:
        raise HTTPException(
            status_code=400,
            detail=f"No classifier mapping configured for folder: {folder_name}",
        )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.ClassifiersType).where(
                models.ClassifiersType.classifier_name == classifier_name
            )
        )

        classifier_row = result.scalar_one_or_none()

        if not classifier_row:
            raise HTTPException(
                status_code=404,
                detail=f"Classifier row not found for: {classifier_name}",
            )

        processor_id = getattr(classifier_row, "processor_id", None)

        if not processor_id:
            raise HTTPException(
                status_code=400,
                detail=f"No processor_id configured for classifier: {classifier_name}",
            )

        institution_id = getattr(classifier_row, "institution_id", None) or 1

        ready_prefix = build_prefix(semester, "Ready")
        files = get_folder_files(ready_prefix, folder_name)

        if not files:
            raise HTTPException(status_code=404, detail="Folder not found or empty.")

        processor = TranscriptProcessor(
            ProcessorConfig(
                project_id=os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript"),
                location=os.environ.get("DOC_AI_LOCATION", "us"),
                processor_id=processor_id,
            )
        )

        storage_client = get_storage_client()
        bucket = storage_client.bucket(GCS_BUCKET)

        processed_files = 0
        total_students = 0
        total_courses = 0

        for file in files:
            blob_name = file["blob_name"]
            blob = bucket.blob(blob_name)

            if not blob.exists(storage_client):
                continue

            content = blob.download_as_bytes()

            ctx = ExtractionContext(
                extraction_file_id=None,
                institution_id=institution_id,
                classifier_type_id=classifier_row.id,
                used_processor_id=processor_id,
                file_name=file["file_name"],
                classifier_name=classifier_name,
            )

            counts = await processor.process_bytes_and_persist(session, ctx, content)

            processed_files += 1
            total_students += counts.get("students", 0)
            total_courses += counts.get("courses", 0)

        if processed_files == 0:
            raise HTTPException(
                status_code=400,
                detail="No valid PDF files were processed.",
            )

        return {
            "status": "success",
            "folder_name": folder_name,
            "semester": semester,
            "classifier_name": classifier_name,
            "processed_files": processed_files,
            "students": total_students,
            "courses": total_courses,
            "message": f"Extraction completed for {folder_name} in {semester}.",
        }