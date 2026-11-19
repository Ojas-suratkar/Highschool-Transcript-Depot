# semester_classification_clustering.py
#
# DocAI Transcript Pipeline (GCS) — Semester-wise Output (START-to-END)
#
# ✅ Semester-aware routing
# ✅ Layout-family routing (LBUSD/Mayfair/St_Anthony/Others)
# ✅ OCR/Form processor JSONs for Others
# ✅ Strong layout clustering for Others
# ✅ Cluster folder named by MAJORITY school name from JSON["text"] (header-safe)
# ✅ SAFETY NET: if a layout cluster contains multiple schools, auto-split into school folders
# ✅ Split even if a school appears ONCE
# ✅ NO Needs_Review / Unknown folders (only last-resort school_cluster_<id>)
# ✅ Debug CSV per semester (optional) -> OFF by default
#
# REQUIREMENTS:
# pip install google-cloud-storage google-cloud-documentai numpy scikit-learn grpcio scikit-learn

import time
import random
import json
import tempfile
import re
from pathlib import Path, PurePosixPath
from typing import Dict, Any, Tuple, List
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.classifier_registry import (
    get_integrated_classifiers,
    sanitize_classifier_key,
    HARDCODED_CLASSIFIERS,
)

import grpc
import numpy as np

from google.cloud import documentai_v1 as documentai
from google.cloud import storage
from google.api_core.exceptions import (
    InternalServerError,
    ServiceUnavailable,
    DeadlineExceeded,
    ResourceExhausted,
    TooManyRequests,
)
from google.protobuf.json_format import MessageToDict


# -----------------------------
# CONFIG (EDIT THESE)
# -----------------------------
PROJECT_ID = "doc-ai-transcript"
LOCATION = "us"

BINARY_CLASSIFIER_PROCESSOR_ID = "7ffd481485bfc9f6"
LAYOUT_CLASSIFIER_PROCESSOR_ID = "a860d0a957566bc2"
DOCUMENT_OCR_PARSER_ID = "bb6559ebc9c2417c"

GCS_BUCKET = "doc-ai-transcript-us-central1-v1-001"
GCS_INPUT_PREFIX = "01_Inbox_Raw_HS_Transcripts/"
GCS_OUTPUT_PREFIX = "02_Library_Categorized_HS_Transcripts/"

# Only classify (transcript-vs-not and layout/format) from the first pages of a
# PDF. Doc AI online processing caps pages (~15); a large document — a handbook,
# say — would otherwise fail the classify call and get stranded in 01_. The
# header pages carry all the signal needed to classify.
_CLASSIFY_MAX_PAGES = 5

USE_GCS = True
MOVE_FILES = True               # True = copy then delete source (move). False = copy only.
THROTTLE_S = 0.12

MIN_CONFIDENT = 0.70
MIN_MARGIN = 0.15

MAX_RETRIES = 6
BASE_DELAY_S = 1.0
TIMEOUT_S = 120

# ---- Clustering knobs ----
CLUSTER_GRID = 64
CLUSTER_DISTANCE_THRESHOLD = 0.040   # tighten if still merging, e.g. 0.035
CLUSTER_MIN_RECORDS = 1              # cluster even a single new-type document

# ---- Split mixed clusters by school (safety net) ----
SPLIT_CLUSTER_BY_SCHOOL_IF_COUNT_AT_LEAST = 1   # split even if school appears once
SPLIT_CLUSTER_BY_SCHOOL_MIN_SHARE = 0.00        # allow even 1 file in big cluster

# ---- Debug report ----
WRITE_CLUSTER_REPORT_CSV = False     # OFF (you said you don't want CSV)


# -----------------------------
# RETRY HELPERS
# -----------------------------
TRANSIENT_GRPC_CODES = {
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
}

def process_with_retry(
    client,
    request,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY_S,
    timeout: float = TIMEOUT_S
):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return client.process_document(request=request, timeout=timeout)
        except (
            InternalServerError,
            ServiceUnavailable,
            DeadlineExceeded,
            ResourceExhausted,   # 429 quota — retry with backoff instead of skipping
            TooManyRequests,     # HTTP 429
        ) as e:
            last_err = e
        except grpc.RpcError as e:
            if e.code() in TRANSIENT_GRPC_CODES:
                last_err = e
            else:
                raise

        # 429 quota recovers per-minute, so wait longer for it than other transients.
        is_quota = isinstance(last_err, (ResourceExhausted, TooManyRequests)) or (
            isinstance(last_err, grpc.RpcError)
            and last_err.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
        )
        factor = 4.0 if is_quota else 1.0
        sleep_s = base_delay * factor * (2 ** (attempt - 1)) + random.uniform(0, 0.6)
        sleep_s = min(sleep_s, 90.0)
        print(f"Transient DocAI error ({'quota' if is_quota else 'transient'}). "
              f"Retry {attempt}/{max_retries} in {sleep_s:.2f}s")
        time.sleep(sleep_s)

    raise RuntimeError(f"Document AI failed after {max_retries} retries. Last error: {last_err}")


def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _extract_class_scores(doc: documentai.Document) -> List[Tuple[str, float]]:
    scores: List[Tuple[str, float]] = []
    for ent in getattr(doc, "entities", []) or []:
        label = (getattr(ent, "type_", "") or "").strip()
        conf = _safe_float(getattr(ent, "confidence", 0.0))
        if label:
            scores.append((label, conf))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


# -----------------------------
# SEMESTER PATH HELPERS
# -----------------------------
def get_semester_from_input_blob(blob_name: str) -> str:
    p = PurePosixPath(blob_name)
    base = PurePosixPath(GCS_INPUT_PREFIX)
    try:
        rel = p.relative_to(base)
        return rel.parts[0] if len(rel.parts) >= 2 else "Unsorted"
    except Exception:
        return "Unsorted"


def get_semester_from_output_blob(blob_name: str) -> str:
    p = PurePosixPath(blob_name)
    base = PurePosixPath(GCS_OUTPUT_PREFIX)
    try:
        rel = p.relative_to(base)
        return rel.parts[0] if rel.parts else "Unsorted"
    except Exception:
        return "Unsorted"


def make_output_prefix(semester: str, *parts: str) -> str:
    semester = (semester or "Unsorted").strip().strip("/")
    joined = "/".join([str(p).strip().strip("/") for p in parts if p and str(p).strip() != ""])
    if joined:
        return f"{GCS_OUTPUT_PREFIX}{semester}/{joined}/"
    return f"{GCS_OUTPUT_PREFIX}{semester}/"


# -----------------------------
# GCS HELPERS
# -----------------------------
# storage_client = storage.Client() if USE_GCS else None
# -----------------------------
# GCS HELPERS
# -----------------------------
storage_client = None

def get_storage_client():
    global storage_client
    if storage_client is None and USE_GCS:
        storage_client = storage.Client(project=PROJECT_ID)
    return storage_client



def gcs_list_pdfs(bucket_name: str, prefix: str) -> List[str]:
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    blobs = []
    for b in get_storage_client().list_blobs(bucket_name, prefix=prefix):
        if b.name.lower().endswith(".pdf"):
            blobs.append(b.name)
    return sorted(blobs)


def gcs_list_jsons(bucket_name: str, prefix: str) -> List[str]:
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    blobs = []
    for b in get_storage_client().list_blobs(bucket_name, prefix=prefix):
        if b.name.lower().endswith(".json"):
            blobs.append(b.name)
    return sorted(blobs)


def gcs_download_blob_to_file(bucket_name: str, blob_name: str, local_path: Path):
    bucket = get_storage_client().bucket(bucket_name)
    blob = bucket.blob(blob_name)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(local_path))


def gcs_upload_file(bucket_name: str, local_path: Path, dest_blob_name: str):
    bucket = get_storage_client().bucket(bucket_name)
    blob = bucket.blob(dest_blob_name)
    blob.upload_from_filename(str(local_path))


def gcs_copy_blob(bucket_name: str, src_blob_name: str, dest_blob_name: str):
    bucket = get_storage_client().bucket(bucket_name)
    src = bucket.blob(src_blob_name)
    bucket.copy_blob(src, bucket, new_name=dest_blob_name)


def gcs_delete_blob(bucket_name: str, blob_name: str):
    bucket = get_storage_client().bucket(bucket_name)
    bucket.blob(blob_name).delete()


def move_blob_to_prefix(bucket_name: str, src_blob_name: str, dest_prefix: str, delete_source: bool = True):
    if not dest_prefix.endswith("/"):
        dest_prefix += "/"
    dest_blob_name = dest_prefix + PurePosixPath(src_blob_name).name
    try:
        gcs_copy_blob(bucket_name, src_blob_name, dest_blob_name)
    except Exception as exc:  # noqa: BLE001
        # The source was already moved (e.g. a concurrent pass) — if the
        # destination now exists, treat the move as done instead of failing.
        from google.cloud import storage as _storage
        client = _storage.Client()
        if client.bucket(bucket_name).blob(dest_blob_name).exists(client):
            return dest_blob_name
        raise exc
    if delete_source:
        gcs_delete_blob(bucket_name, src_blob_name)
    return dest_blob_name


# -----------------------------
# TEMP FILES
# -----------------------------
tmp_dir = Path(tempfile.gettempdir()) / "docai_pipeline_tmp"
tmp_dir.mkdir(parents=True, exist_ok=True)


def download_pdf_blob_to_local(bucket_name: str, blob_name: str) -> Path:
    local = tmp_dir / blob_name.replace("/", "__")
    gcs_download_blob_to_file(bucket_name, blob_name, local)
    return local


# -----------------------------
# CLASSIFIERS
# -----------------------------
def classify_transcript_vs_non(client: documentai.DocumentProcessorServiceClient, pdf_bytes: bytes = None, *, gcs_uri: str = None) -> Dict[str, Any]:
    name = client.processor_path(PROJECT_ID, LOCATION, BINARY_CLASSIFIER_PROCESSOR_ID)
    # Doc AI online processing caps pages (~15). A handbook or other large PDF
    # exceeds that and the whole classify call throws, leaving the file stuck in
    # 01_ (never sorted into Not a Transcript). The first pages are enough to tell
    # a transcript from a non-transcript, so only process those.
    _opts = documentai.ProcessOptions(from_start=_CLASSIFY_MAX_PAGES)
    if gcs_uri:
        req = documentai.ProcessRequest(
            name=name,
            gcs_document=documentai.GcsDocument(gcs_uri=gcs_uri, mime_type="application/pdf"),
            process_options=_opts,
        )
    else:
        req = documentai.ProcessRequest(
            name=name,
            raw_document=documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf"),
            process_options=_opts,
        )
    res = process_with_retry(client, req)
    scores = _extract_class_scores(res.document)

    top_label, top_conf = ("", 0.0)
    second_conf = 0.0
    if scores:
        top_label, top_conf = scores[0]
        if len(scores) > 1:
            second_conf = scores[1][1]

    return {
        "predicted_label": (top_label or "").strip(),
        "confidence": float(top_conf),
        "second_conf": float(second_conf),
        "margin": float(top_conf - second_conf),
        "all_scores": scores[:5],
    }


def classify_layout_family(client: documentai.DocumentProcessorServiceClient, pdf_bytes: bytes = None, *, gcs_uri: str = None) -> Dict[str, Any]:
    name = client.processor_path(PROJECT_ID, LOCATION, LAYOUT_CLASSIFIER_PROCESSOR_ID)
    # Same page cap as the binary classifier — the header pages carry the layout
    # signal, so a large PDF never fails the format classify on the page limit.
    _opts = documentai.ProcessOptions(from_start=_CLASSIFY_MAX_PAGES)
    if gcs_uri:
        req = documentai.ProcessRequest(
            name=name,
            gcs_document=documentai.GcsDocument(gcs_uri=gcs_uri, mime_type="application/pdf"),
            process_options=_opts,
        )
    else:
        req = documentai.ProcessRequest(
            name=name,
            raw_document=documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf"),
            process_options=_opts,
        )
    res = process_with_retry(client, req)
    scores = _extract_class_scores(res.document)

    top_label, top_conf = ("", 0.0)
    second_conf = 0.0
    if scores:
        top_label, top_conf = scores[0]
        if len(scores) > 1:
            second_conf = scores[1][1]

    return {
        "predicted_label": (top_label or "").strip(),
        "confidence": float(top_conf),
        "second_conf": float(second_conf),
        "margin": float(top_conf - second_conf),
        "all_scores": scores[:5],
    }


# -----------------------------
# STEP 1: ROUTE ALL PDFs (BINARY)
#   transcript / Non_Transcript
# -----------------------------
def _classify_binary_one(blob_name: str, client) -> dict:
    semester = get_semester_from_input_blob(blob_name)
    try:
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        out = classify_transcript_vs_non(client, gcs_uri=gcs_uri)
        label = (out["predicted_label"] or "").strip()
        label_lower = label.lower().replace(" ", "_").replace("-", "_")
        is_non_transcript = (
            label_lower in ("not_a_transcript", "non_transcript", "not_transcript", "not_a_transcript_document")
            or ("not" in label_lower and "transcript" in label_lower)
            or ("non" in label_lower and "transcript" in label_lower)
        )
        dest_prefix = make_output_prefix(semester, "not_a_transcript" if is_non_transcript else "transcript")
        dest_blob = move_blob_to_prefix(GCS_BUCKET, blob_name, dest_prefix, delete_source=True)
        print(f"[BINARY CLASSIFY] {blob_name} -> label={label!r} conf={out['confidence']:.3f} all_scores={out['all_scores']}")
        return {"ok": True, "blob_name": blob_name, "dest_blob": dest_blob, "is_transcript": dest_prefix.endswith("/transcript/"), "semester": semester}
    except Exception as exc:
        error_msg = str(exc)
        print(f"[BINARY CLASSIFY] SKIP {blob_name}: {error_msg}")
        return {"ok": False, "blob_name": blob_name, "file_name": PurePosixPath(blob_name).name, "semester": semester, "stage": "binary_classify", "error": error_msg}


def route_all_pdfs_with_binary_classifier_gcs(pdf_blobs: List[str] | None = None) -> Tuple[List[str], List[Dict]]:
    pdf_blobs = pdf_blobs if pdf_blobs is not None else gcs_list_pdfs(GCS_BUCKET, GCS_INPUT_PREFIX)
    if not pdf_blobs:
        return [], []

    client = documentai.DocumentProcessorServiceClient()
    transcripts_out_blobs: List[str] = []
    failed_blobs: List[Dict] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_classify_binary_one, blob, client): blob for blob in pdf_blobs}
        for i, fut in enumerate(as_completed(futures), start=1):
            blob = futures[fut]
            print(f"[{i}/{len(pdf_blobs)}] Binary classify done: {blob}")
            result = fut.result()
            if result["ok"]:
                if result["is_transcript"]:
                    transcripts_out_blobs.append(result["dest_blob"])
            else:
                failed_blobs.append({
                    "blob_name": result["blob_name"],
                    "file_name": result["file_name"],
                    "semester": result["semester"],
                    "stage": result["stage"],
                    "error": result["error"],
                })

    print("Binary routing complete.")
    return transcripts_out_blobs, failed_blobs


# -----------------------------
# STEP 2: ROUTE TRANSCRIPTS (LAYOUT FAMILY)
#   LBUSD / Mayfair / St_Anthony / Others
# -----------------------------
def _classify_layout_one(blob_name: str, client) -> dict:
    semester = get_semester_from_output_blob(blob_name)
    base_tx = make_output_prefix(semester, "transcript")
    others_prefix = base_tx + "Others/"
    label_to_dir = {
        "LBUSD": base_tx + "LBUSD/",
        "Mayfair_High_School": base_tx + "Mayfair_High_School/",
        "St_Anthony_High_School": base_tx + "St_Anthony_High_School/",
        "Others": others_prefix,
        "Other": others_prefix,
        "Other_transcript": others_prefix,
    }
    try:
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        out = classify_layout_family(client, gcs_uri=gcs_uri)
        label = (out["predicted_label"] or "").strip()
        conf = float(out["confidence"])
        out_margin = float(out["margin"])
        if (not label) or (conf < MIN_CONFIDENT) or (out_margin < MIN_MARGIN):
            dest_prefix = others_prefix
        elif label in label_to_dir:
            dest_prefix = label_to_dir[label]
        else:
            # Runtime-integrated types: the classifier's label, sanitized, IS the
            # type key and the transcript/<key>/ folder. Route there when an
            # extractor has been integrated for that key; otherwise Others.
            key = sanitize_classifier_key(label)
            integrated = get_integrated_classifiers()
            if key and key not in HARDCODED_CLASSIFIERS and key in integrated:
                dest_prefix = base_tx + f"{key}/"
            else:
                dest_prefix = others_prefix
        dest_blob = move_blob_to_prefix(GCS_BUCKET, blob_name, dest_prefix, delete_source=True)
        print(f"[LAYOUT CLASSIFY] {blob_name} -> label={label!r} conf={conf:.3f}")
        return {"ok": True, "blob_name": blob_name, "dest_blob": dest_blob, "is_other": dest_prefix == others_prefix, "semester": semester}
    except Exception as exc:
        error_msg = str(exc)
        print(f"[LAYOUT CLASSIFY] SKIP {blob_name}: {error_msg}")
        return {"ok": False, "blob_name": blob_name, "file_name": PurePosixPath(blob_name).name, "semester": semester, "stage": "layout_classify", "error": error_msg}


def route_transcripts_by_layout_classifier_gcs(transcript_blobs: List[str]) -> Tuple[List[str], List[Dict]]:
    client = documentai.DocumentProcessorServiceClient()
    other_blobs: List[str] = []
    failed_blobs: List[Dict] = []

    sorted_blobs = sorted(transcript_blobs)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_classify_layout_one, blob, client): blob for blob in sorted_blobs}
        for i, fut in enumerate(as_completed(futures), start=1):
            blob = futures[fut]
            print(f"[{i}/{len(sorted_blobs)}] Layout classify done: {blob}")
            result = fut.result()
            if result["ok"]:
                if result["is_other"]:
                    other_blobs.append(result["dest_blob"])
            else:
                failed_blobs.append({
                    "blob_name": result["blob_name"],
                    "file_name": result["file_name"],
                    "semester": result["semester"],
                    "stage": result["stage"],
                    "error": result["error"],
                })

    return other_blobs, failed_blobs


# -----------------------------
# STEP 3: OCR FORM PARSER FOR OTHERS → JSON
# -----------------------------
def _ocr_parse_one(blob_name: str, client) -> dict:
    semester = get_semester_from_output_blob(blob_name)
    try:
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        name = client.processor_path(PROJECT_ID, LOCATION, DOCUMENT_OCR_PARSER_ID)
        req = documentai.ProcessRequest(
            name=name,
            gcs_document=documentai.GcsDocument(gcs_uri=gcs_uri, mime_type="application/pdf")
        )
        res = process_with_retry(client, req)
        d = MessageToDict(res.document._pb, preserving_proto_field_name=True)
        stem = PurePosixPath(blob_name).stem
        json_local = tmp_dir / f"{stem}.json"
        json_local.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        json_blob_name = make_output_prefix(semester, "transcript", "Others", "docai_json") + f"{stem}.json"
        gcs_upload_file(GCS_BUCKET, json_local, json_blob_name)
        try:
            json_local.unlink()
        except Exception:
            pass
        return {"ok": True, "blob_name": blob_name, "json_blob": json_blob_name}
    except Exception as exc:
        return {"ok": False, "blob_name": blob_name, "file_name": PurePosixPath(blob_name).name, "semester": semester, "stage": "ocr_parse", "error": str(exc)}


def form_parse_and_save_jsons_gcs(other_blobs: List[str]) -> Tuple[List[str], List[Dict]]:
    client = documentai.DocumentProcessorServiceClient()
    written_json_blobs: List[str] = []
    failed_blobs: List[Dict] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_ocr_parse_one, blob, client): blob for blob in sorted(other_blobs)}
        for i, fut in enumerate(as_completed(futures), start=1):
            blob = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                result = {"ok": False, "blob_name": blob, "file_name": PurePosixPath(blob).name, "stage": "ocr_parse", "error": str(exc)}
            if result.get("ok"):
                print(f"[{i}/{len(other_blobs)}] OCR parse done: {blob}")
                written_json_blobs.append(result["json_blob"])
            else:
                print(f"[{i}/{len(other_blobs)}] OCR parse FAILED: {blob} — {result.get('error')}")
                failed_blobs.append(result)

    print("OCR JSONs written.")
    return written_json_blobs, failed_blobs


# -----------------------------
# SINGLE-FILE PIPELINE (classify → OCR in one pass per file)
# -----------------------------
def classify_blob_pipeline(blob_name: str, binary_client, layout_client, ocr_client) -> dict:
    """
    Full single-file pipeline: binary classify → layout classify → OCR (if Others).
    blob_name must be in the 01_Inbox input prefix.
    Returns: {ok, blob_name, dest_blob, classifier_name, is_other, json_blob, semester}
    """
    # Step 1: binary classify
    binary_result = _classify_binary_one(blob_name, binary_client)
    if not binary_result.get("ok"):
        return binary_result

    if not binary_result["is_transcript"]:
        return {**binary_result, "classifier_name": "not_a_transcript", "is_other": False, "json_blob": None}

    # Step 2: layout classify (file is now in transcript/ output folder)
    transcript_blob = binary_result["dest_blob"]
    layout_result = _classify_layout_one(transcript_blob, layout_client)
    if not layout_result.get("ok"):
        return layout_result

    # Step 3: OCR for Others
    json_blob = None
    if layout_result["is_other"]:
        ocr_result = _ocr_parse_one(layout_result["dest_blob"], ocr_client)
        if ocr_result.get("ok"):
            json_blob = ocr_result["json_blob"]

    # Infer classifier_name from destination path
    dest_blob = layout_result["dest_blob"]
    path_lower = dest_blob.lower()
    if "/lbusd/" in path_lower:
        classifier_name = "lbusd"
    elif "/mayfair" in path_lower:
        classifier_name = "mayfair_high_school"
    elif "/st_anthony" in path_lower:
        classifier_name = "st_anthony_high_school"
    else:
        classifier_name = "others"
        # Runtime-integrated types: match their transcript/<key>/ folder.
        for key in get_integrated_classifiers():
            if key not in HARDCODED_CLASSIFIERS and f"/{key}/" in path_lower:
                classifier_name = key
                break

    return {
        "ok": True,
        "blob_name": blob_name,
        "dest_blob": dest_blob,
        "classifier_name": classifier_name,
        "is_other": layout_result["is_other"],
        "json_blob": json_blob,
        "semester": binary_result["semester"],
    }


# -----------------------------
# SCHOOL NAME FROM JSON["text"]  (IMPROVED / FALSE-POSITIVE SAFE)
# -----------------------------
SCHOOL_LIKE_RE = re.compile(
    r"\b([A-Z][A-Za-z&.'\- ]{2,80}?\b(?:High School|Charter School|Preparatory|Prep|Academy|School))\b"
)

BAD_SCHOOL_PHRASES_RE = re.compile(
    r"\b("
    r"Graduated High School|"
    r"Transcript of Student Progress|"
    r"Official Transcript|"
    r"Academic Transcript|"
    r"Student Progress|"
    r"School Year|"
    r"School Enter|District Enter|"
    r"Unified School District|School District|"
    r"Junior High School|Middle School|Elementary School|"
    r"Virtual Academy"
    r")\b",
    re.I
)

BAD_COLLEGE_PREP_RE = re.compile(r"\bcollege\s*prep\b", re.I)


def clean_folder_name(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = s.replace("&", " and ")
    s = re.sub(r"\bst\.?\b", "saint", s, flags=re.I)
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    return s[:80] if s else ""


def _pick_header_text(full_text: str) -> str:
    if not full_text:
        return ""
    t = full_text.replace("\r", "\n")
    t = re.sub(r"\n{2,}", "\n", t)

    head = t[:2200]
    idx = t.lower().find("district")
    if idx != -1:
        around = t[max(0, idx - 500): idx + 1800]
        return head + "\n" + around
    return head


def extract_school_candidates_from_text(full_text: str) -> List[str]:
    if not full_text:
        return []

    header_text = _pick_header_text(full_text)
    cands: List[str] = []

    for m in SCHOOL_LIKE_RE.finditer(header_text):
        name = (m.group(1) or "").strip()
        low = name.lower()

        if BAD_SCHOOL_PHRASES_RE.search(name):
            continue
        if BAD_COLLEGE_PREP_RE.search(name):
            continue
        if low.startswith("graduated "):
            continue
        if "district" in low:
            continue
        if len(name) < 8:
            continue

        cands.append(name)

    return cands


def extract_school_name_from_text_majority(full_text: str) -> str:
    if not full_text:
        return ""

    candidates = extract_school_candidates_from_text(full_text)
    if not candidates:
        return ""

    def score_name(name: str) -> float:
        low = name.lower()
        s = 0.0
        if "high school" in low:
            s += 10.0
        if "charter school" in low:
            s += 7.0
        if re.search(r"\bschool\b", low):
            s += 2.0

        if "prep" in low and "school" not in low and "high school" not in low:
            s -= 6.0
        if "academy" in low and "school" not in low and "high school" not in low:
            s -= 2.0

        if BAD_COLLEGE_PREP_RE.search(low):
            s -= 50.0
        return s

    cnt = Counter(candidates)
    best = sorted(cnt.items(), key=lambda x: (x[1], score_name(x[0])), reverse=True)[0][0]
    return clean_folder_name(best)


# -----------------------------
# LAYOUT EMBEDDING (STRONG)
# -----------------------------
def poly_to_bbox(poly):
    if not poly:
        return None
    verts = None
    if isinstance(poly, dict):
        verts = poly.get("normalizedVertices") or poly.get("vertices") or []
    else:
        verts = poly
    xs, ys = [], []
    for v in verts:
        if "x" in v and "y" in v:
            xs.append(v["x"])
            ys.append(v["y"])
    if not xs:
        return None
    return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))


def normalize_bboxes(bboxes):
    arr = np.array(bboxes, dtype=np.float32)
    if arr.size == 0:
        return arr
    m = float(arr.max())
    if m > 2.0:
        arr = arr / (m + 1e-6)
    arr = np.clip(arr, 0.0, 1.0)
    return arr


def build_layout_vector_strong(doc: dict, grid=CLUSTER_GRID):
    d = doc.get("document", doc)
    pages = d.get("pages", [])
    if not pages:
        return None
    p0 = pages[0]

    items = p0.get("blocks") or p0.get("paragraphs") or p0.get("lines") or []
    if not items:
        return None

    bboxes = []
    for it in items:
        layout = (it.get("layout") or {})
        poly = layout.get("boundingPoly") or layout.get("bounding_poly")
        bbox = poly_to_bbox(poly)
        if bbox:
            bboxes.append(bbox)

    if not bboxes:
        return None

    bb = normalize_bboxes(bboxes)
    x0, y0, x1, y1 = bb[:, 0], bb[:, 1], bb[:, 2], bb[:, 3]
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    area = np.clip((x1 - x0) * (y1 - y0), 0.0, 1.0)

    heat = np.zeros((grid, grid), dtype=np.float32)
    for cxi, cyi, ai in zip(cx, cy, area):
        gx = min(grid - 1, max(0, int(cxi * grid)))
        gy = min(grid - 1, max(0, int(cyi * grid)))
        heat[gy, gx] += float(ai + 1e-3)
    heat = heat / (heat.sum() + 1e-6)

    row = heat.sum(axis=1)
    col = heat.sum(axis=0)

    header_mask = cy < 0.20
    body_mask = (cy >= 0.20) & (cy <= 0.80)
    footer_mask = cy > 0.80

    def hist(vals, bins=grid):
        if vals.size == 0:
            return np.zeros((bins,), dtype=np.float32)
        h, _ = np.histogram(vals, bins=bins, range=(0.0, 1.0))
        h = h.astype(np.float32)
        return h / (h.sum() + 1e-6)

    x_header = hist(cx[header_mask], bins=grid)
    x_body = hist(cx[body_mask], bins=grid)
    x_footer = hist(cx[footer_mask], bins=grid)

    stats = np.array([
        float(len(bb)),
        float(area.mean()),
        float(area.std() + 1e-6),
        float(np.quantile(cy, 0.25)),
        float(np.quantile(cy, 0.50)),
        float(np.quantile(cy, 0.75)),
    ], dtype=np.float32)

    feat = np.concatenate([
        heat.flatten(),
        row, col,
        x_header, x_body, x_footer,
        stats
    ])
    feat = feat / (np.linalg.norm(feat) + 1e-6)
    return feat


# -----------------------------
# CLUSTERING
# -----------------------------
def cluster_vectors_agglomerative(X: np.ndarray, distance_threshold: float):
    from sklearn.cluster import AgglomerativeClustering
    try:
        model = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=distance_threshold
        )
    except TypeError:
        model = AgglomerativeClustering(
            n_clusters=None,
            affinity="cosine",
            linkage="average",
            distance_threshold=distance_threshold
        )
    return model.fit_predict(X)


# -----------------------------
# GROUP OTHERS BY LAYOUT, NAME BY MAJORITY SCHOOL, SPLIT MIXED CLUSTERS
# -----------------------------
def cluster_and_group_others_gcs(semester: str) -> Dict[str, int]:
    from sklearn.metrics.pairwise import cosine_distances

    semester = (semester or "Unsorted").strip().strip("/")
    others_prefix = make_output_prefix(semester, "transcript", "Others")
    json_prefix = others_prefix + "docai_json/"

    json_blobs = gcs_list_jsons(GCS_BUCKET, json_prefix)
    if not json_blobs:
        print(f"[{semester}] No JSONs found in gs://{GCS_BUCKET}/{json_prefix}")
        return {"clusters": 0, "moved_pdfs": 0, "moved_jsons": 0, "records": 0}

    bucket = get_storage_client().bucket(GCS_BUCKET)

    pdf_lookup = {}
    for b in get_storage_client().list_blobs(GCS_BUCKET, prefix=others_prefix):
        if b.name.lower().endswith(".pdf"):
            pdf_lookup[PurePosixPath(b.name).name.lower()] = b.name

    records = []
    vectors = []

    for jb in json_blobs:
        local_json = tmp_dir / PurePosixPath(jb).name
        gcs_download_blob_to_file(GCS_BUCKET, jb, local_json)

        try:
            doc = json.loads(local_json.read_text(encoding="utf-8"))
            stem = PurePosixPath(jb).stem

            candidate_pdf = jb.replace("/docai_json/", "/").replace(".json", ".pdf")
            if bucket.blob(candidate_pdf).exists(get_storage_client()):
                pdf_blob = candidate_pdf
            else:
                pdf_blob = pdf_lookup.get((stem + ".pdf").lower())

            if not pdf_blob:
                print(f"[{semester}] Missing PDF for {stem}; skipping.")
                continue

            vec = build_layout_vector_strong(doc, grid=CLUSTER_GRID)
            if vec is None:
                print(f"[{semester}] WARNING: no layout vector for {stem}; skipping from clustering.")
                continue

            school_guess = extract_school_name_from_text_majority(doc.get("text", "") or "")

            records.append({
                "stem": stem,
                "json_blob": jb,
                "pdf_blob": pdf_blob,
                "school_guess": school_guess,
            })
            vectors.append(vec)

        finally:
            try:
                local_json.unlink()
            except Exception:
                pass

    if len(records) < CLUSTER_MIN_RECORDS:
        print(f"[{semester}] Not enough valid records to cluster (records={len(records)}).")
        return {"clusters": 0, "moved_pdfs": 0, "moved_jsons": 0, "records": len(records)}

    X = np.vstack(vectors)

    if len(records) == 1:
        # A single new-type document — no pairwise distances to compute and the
        # clustering algorithm needs >=2 samples, so treat it as one cluster.
        labels = [0]
    else:
        # Distance debug (prints only)
        D = cosine_distances(X)
        vals = D[np.triu_indices(D.shape[0], 1)]
        print(f"\n[{semester}] === LAYOUT DISTANCE DEBUG ===")
        print("pairs:", len(vals))
        print("min:", float(vals.min()))
        print("p25:", float(np.quantile(vals, 0.25)))
        print("median:", float(np.quantile(vals, 0.50)))
        print("p75:", float(np.quantile(vals, 0.75)))
        print("max:", float(vals.max()))
        print("threshold:", CLUSTER_DISTANCE_THRESHOLD)

        labels = cluster_vectors_agglomerative(X, distance_threshold=CLUSTER_DISTANCE_THRESHOLD)
    clusters = defaultdict(list)
    for i, lab in enumerate(labels):
        clusters[int(lab)].append(i)

    print(f"[{semester}] clusters found:", len(clusters))

    grouped_root = others_prefix + "Grouped_by_school/"
    moved_pdfs = 0
    moved_jsons = 0

    def folder_for_school(base: str) -> str:
        # Same school name -> same destination folder (one type), even when the
        # layout model over-splits a school into several clusters. Previously a
        # second cluster voting the same school was suffixed ("Cypress High
        # School_2"), surfacing as a confusing duplicate type on Needs Setup.
        # Collapsing them into a single folder merges the over-split clusters
        # into one type for that school.
        return clean_folder_name(base) or "school_cluster"

    cluster_primary_name = {}
    for cid, idxs in clusters.items():
        votes = [records[i]["school_guess"] for i in idxs if records[i]["school_guess"]]
        chosen = Counter(votes).most_common(1)[0][0] if votes else f"school_cluster_{cid}"
        cluster_primary_name[cid] = folder_for_school(chosen)
        print(f"[{semester}] Cluster {cid}: size={len(idxs)} name={cluster_primary_name[cid]} votes_top={Counter(votes).most_common(5)}")

    # MOVE: with safety-net splitting
    for cid, idxs in clusters.items():
        votes = [records[i]["school_guess"] for i in idxs if records[i]["school_guess"]]
        vote_counts = Counter(votes)
        cluster_size = len(idxs)

        schools_to_split = []
        for school, c in vote_counts.items():
            if c >= SPLIT_CLUSTER_BY_SCHOOL_IF_COUNT_AT_LEAST and (c / cluster_size) >= SPLIT_CLUSTER_BY_SCHOOL_MIN_SHARE:
                schools_to_split.append(school)

        # If not mixed -> move entire cluster
        if len(schools_to_split) <= 1:
            cname = cluster_primary_name[cid]
            dest_prefix = grouped_root + cname + "/"
            dest_json_prefix = dest_prefix + "docai_json/"

            for i in idxs:
                r = records[i]
                src_pdf = r["pdf_blob"]
                src_json = r["json_blob"]
                dst_pdf = dest_prefix + PurePosixPath(src_pdf).name
                dst_json = dest_json_prefix + PurePosixPath(src_json).name

                if src_pdf != dst_pdf:
                    gcs_copy_blob(GCS_BUCKET, src_pdf, dst_pdf)
                    if MOVE_FILES:
                        gcs_delete_blob(GCS_BUCKET, src_pdf)
                    moved_pdfs += 1

                if src_json != dst_json:
                    gcs_copy_blob(GCS_BUCKET, src_json, dst_json)
                    if MOVE_FILES:
                        gcs_delete_blob(GCS_BUCKET, src_json)
                    moved_jsons += 1

            continue

        # Otherwise split into school folders
        print(f"[{semester}] Cluster {cid} is mixed -> splitting by school:", vote_counts)

        by_school = defaultdict(list)
        for i in idxs:
            sg = records[i]["school_guess"] or ""
            by_school[sg].append(i)

        majority_school = vote_counts.most_common(1)[0][0] if vote_counts else cluster_primary_name[cid]

        for school_guess, sub_idxs in by_school.items():
            if not school_guess:
                school_guess = majority_school

            sub_name = folder_for_school(school_guess)
            dest_prefix = grouped_root + sub_name + "/"
            dest_json_prefix = dest_prefix + "docai_json/"

            for i in sub_idxs:
                r = records[i]
                src_pdf = r["pdf_blob"]
                src_json = r["json_blob"]
                dst_pdf = dest_prefix + PurePosixPath(src_pdf).name
                dst_json = dest_json_prefix + PurePosixPath(src_json).name

                if src_pdf != dst_pdf:
                    gcs_copy_blob(GCS_BUCKET, src_pdf, dst_pdf)
                    if MOVE_FILES:
                        gcs_delete_blob(GCS_BUCKET, src_pdf)
                    moved_pdfs += 1

                if src_json != dst_json:
                    gcs_copy_blob(GCS_BUCKET, src_json, dst_json)
                    if MOVE_FILES:
                        gcs_delete_blob(GCS_BUCKET, src_json)
                    moved_jsons += 1

    print(f"[{semester}] Grouped output -> gs://{GCS_BUCKET}/{grouped_root}")
    print(f"[{semester}] Moved PDFs={moved_pdfs}, JSONs={moved_jsons}")

    return {
        "clusters": len(clusters),
        "moved_pdfs": moved_pdfs,
        "moved_jsons": moved_jsons,
        "records": len(records),
    }


# -----------------------------
# DRIVER (returns summary dict)
# -----------------------------
def run_gcs_pipeline(progress_cb=None, should_cancel=None, target_semester: str | None = None) -> Dict[str, Any]:
    if progress_cb is None:
        progress_cb = lambda stage, pct: None
    if should_cancel is None:
        should_cancel = lambda: False

    def _check_cancel():
        if should_cancel():
            raise KeyboardInterrupt("Classification cancelled")

    print("GCS run mode:", USE_GCS)

    pdf_blobs = gcs_list_pdfs(GCS_BUCKET, GCS_INPUT_PREFIX)
    if target_semester:
        pdf_blobs = [b for b in pdf_blobs if get_semester_from_input_blob(b) == target_semester]
    semesters = sorted({get_semester_from_input_blob(b) for b in pdf_blobs})
    print("Semesters detected in input:", semesters)

    all_failed: List[Dict] = []

    if not pdf_blobs:
        progress_cb("done", 100)
        return {
            "semesters": semesters,
            "transcripts_routed": 0,
            "others_routed": 0,
            "json_written": 0,
            "clustering": {},
            "failed_files": [],
        }

    progress_cb("routing_binary", 10)
    _check_cancel()
    transcript_blobs, failed_binary = route_all_pdfs_with_binary_classifier_gcs(pdf_blobs)
    all_failed.extend(failed_binary)

    progress_cb("layout_classify", 40)
    _check_cancel()
    other_blobs, failed_layout = route_transcripts_by_layout_classifier_gcs(transcript_blobs)
    all_failed.extend(failed_layout)

    progress_cb("ocr_others", 65)
    _check_cancel()
    json_blobs, failed_ocr = form_parse_and_save_jsons_gcs(other_blobs)
    all_failed.extend(failed_ocr)

    per_semester = {}
    progress_cb("clustering", 80)
    for sem in semesters:
        _check_cancel()
        per_semester[sem] = cluster_and_group_others_gcs(sem)

    progress_cb("done", 100)
    return {
        "semesters": semesters,
        "transcripts_routed": len(transcript_blobs),
        "others_routed": len(other_blobs),
        "json_written": len(json_blobs),
        "clustering": per_semester,
        "failed_files": all_failed,
    }


# This is what you should call from FastAPI
def run_pipeline_for_all_semesters(progress_cb=None, should_cancel=None) -> Dict[str, Any]:
    return run_gcs_pipeline(progress_cb=progress_cb, should_cancel=should_cancel)


def run_pipeline_for_semester(year_intake: str, progress_cb=None, should_cancel=None) -> Dict[str, Any]:
    """Run classification pipeline for a single semester folder."""
    return run_gcs_pipeline(progress_cb=progress_cb, should_cancel=should_cancel, target_semester=year_intake)
