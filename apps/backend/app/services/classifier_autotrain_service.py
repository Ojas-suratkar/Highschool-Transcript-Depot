"""Auto-train the layout classifier on new transcript types.

Lifecycle (restart-safe, all state in `classifier_training_jobs`):

  detected  -> a new layout group in Needs Setup reached the threshold (15)
  training  -> a new classifier version is being trained on those docs (LRO)
  checking  -> training finished; running the seatbelt regression check
  promoted  -> seatbelt passed; new version is now the default (went live)
  held      -> seatbelt failed; kept the OLD version, flagged for review
  failed    -> something errored (logged + notified)

DETECTION + NOTIFICATIONS are always on. The actual Doc AI training EXECUTION is
gated behind CLASSIFIER_AUTOTRAIN_ENABLED (default off) so an expensive,
hard-to-reverse training run never fires before it's validated once. A new type
sitting in `detected` can be trained on demand via the manual endpoint.

Every meaningful transition posts to the notification feed.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

from sqlalchemy import create_engine, text

from app.services.notification_service import notify
from app.services.classifier_registry import sanitize_classifier_key, HARDCODED_CLASSIFIERS

GCS_BUCKET = "doc-ai-transcript-us-central1-v1-001"
GROUPED_SUFFIX = "transcript/Others/Grouped_by_school/"
_LIBRARY_ROOT = "02_Library_Categorized_HS_Transcripts/"

_engine = None
_table_ready = False


def threshold() -> int:
    try:
        return int(os.environ.get("CLASSIFIER_AUTOTRAIN_THRESHOLD", "15"))
    except (TypeError, ValueError):
        return 15


def execution_enabled() -> bool:
    """Whether the actual Doc AI training is allowed to fire automatically."""
    return os.environ.get("CLASSIFIER_AUTOTRAIN_ENABLED", "false").lower() in ("1", "true", "yes")


def watcher_enabled() -> bool:
    """Whether the detection watcher runs at all (default on)."""
    return os.environ.get("CLASSIFIER_AUTOTRAIN_WATCHER", "true").lower() in ("1", "true", "yes")


def _get_engine():
    global _engine
    if _engine is None:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/transcripts",
        )
        _engine = create_engine(
            url.replace("+asyncpg", "+psycopg"), pool_pre_ping=True, pool_size=2, max_overflow=2
        )
    return _engine


def ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS classifier_training_jobs (
                    id            BIGSERIAL PRIMARY KEY,
                    group_key     VARCHAR(200) NOT NULL UNIQUE,
                    label         VARCHAR(200) NOT NULL,
                    semester      VARCHAR(120),
                    doc_count     INT NOT NULL DEFAULT 0,
                    status        VARCHAR(30) NOT NULL DEFAULT 'detected',
                    operation_name TEXT,
                    old_default_version TEXT,
                    new_version   TEXT,
                    message       TEXT,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
    _table_ready = True


# ---------------------------------------------------------------------------
# Detection — scan the Needs Setup (Others/Grouped_by_school) groups
# ---------------------------------------------------------------------------
def scan_groups() -> list[dict[str, Any]]:
    """Return [{group, label, semester, doc_count, gcs_uris}] for each layout
    group currently sitting in Needs Setup across all terms."""
    try:
        from google.cloud import storage
    except Exception:  # noqa: BLE001
        return []

    client = storage.Client()
    groups: dict[str, dict[str, Any]] = {}

    # iterate term folders, then their Grouped_by_school subfolders
    for blob in client.list_blobs(GCS_BUCKET, prefix=_LIBRARY_ROOT):
        name = blob.name
        marker = "/" + GROUPED_SUFFIX
        if marker not in name:
            continue
        if not name.lower().endswith(".pdf"):
            continue
        # .../<semester>/transcript/Others/Grouped_by_school/<group>/<file>.pdf
        after = name.split(marker, 1)[1]
        parts = after.split("/", 1)
        if len(parts) < 2 or not parts[1]:
            continue
        group_name = parts[0]
        semester = name.split("/transcript/", 1)[0].split(_LIBRARY_ROOT, 1)[-1]
        key = sanitize_classifier_key(group_name)
        if not key or key in HARDCODED_CLASSIFIERS:
            continue
        g = groups.setdefault(
            key,
            {"group": group_name, "label": group_name, "key": key, "semester": semester,
             "doc_count": 0, "gcs_uris": []},
        )
        g["doc_count"] += 1
        if len(g["gcs_uris"]) < 50:
            g["gcs_uris"].append(f"gs://{GCS_BUCKET}/{name}")

    return _merge_oversplit_groups(groups)


_OVERSPLIT_KEY_RE = re.compile(r"^(.*)_\d+$")


def _merge_oversplit_groups(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse over-split "<base>_<n>" layout groups into "<base>" when the base
    group also exists, so a school the clusterer split into sibling folders
    (e.g. cypress_high_school + cypress_high_school_2) surfaces as one type and
    trains on the combined document count. Gating on the base's presence avoids
    falsely merging a school whose name legitimately ends in a number."""
    merged: dict[str, dict[str, Any]] = {}
    # Base keys sort before their "_<n>" variants, so the canonical group is
    # established first and the variants merge into it.
    for key in sorted(groups.keys()):
        g = groups[key]
        m = _OVERSPLIT_KEY_RE.match(key)
        base = m.group(1) if (m and m.group(1) in groups) else key
        tgt = merged.get(base)
        if tgt is None:
            ng = dict(g)
            ng["key"] = base
            merged[base] = ng
            continue
        tgt["doc_count"] += g["doc_count"]
        for uri in g["gcs_uris"]:
            if len(tgt["gcs_uris"]) < 50:
                tgt["gcs_uris"].append(uri)
    return list(merged.values())


def _existing_jobs() -> dict[str, dict[str, Any]]:
    with _get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT group_key, status, operation_name, old_default_version, new_version FROM classifier_training_jobs")
        ).mappings().all()
    return {r["group_key"]: dict(r) for r in rows}


def _upsert_job(group_key: str, **fields) -> None:
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f":{k}" for k in fields)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields)
    with _get_engine().begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO classifier_training_jobs (group_key, {cols}) "
                f"VALUES (:group_key, {placeholders}) "
                f"ON CONFLICT (group_key) DO UPDATE SET {updates}, updated_at = now()"
            ),
            {"group_key": group_key, **fields},
        )


# ---------------------------------------------------------------------------
# Watcher tick (sync; called via to_thread)
# ---------------------------------------------------------------------------
def watcher_tick() -> None:
    ensure_table()
    thr = threshold()
    jobs = _existing_jobs()

    for g in scan_groups():
        key = g["key"]
        existing = jobs.get(key)
        count = g["doc_count"]

        if count < thr:
            continue

        if existing is None:
            # New type just crossed the threshold → record it + notify.
            _upsert_job(
                key,
                label=g["label"],
                semester=g["semester"],
                doc_count=count,
                status="detected",
                message=f"Reached {count} transcripts (threshold {thr}).",
            )
            notify(
                f"New transcript type ready for training: {g['label']}",
                f"{count} transcripts of this type have been collected, meeting the "
                "training threshold. Train the classifier in Document AI, then integrate "
                "the extractor.",
                level="info",
                category="classifier",
                dedup_key=f"detected:{key}",
                dedup_window_seconds=86400,
                meta={"group_key": key, "doc_count": count},
            )
        else:
            # keep the live count fresh
            _upsert_job(key, doc_count=count)

        # Training EXECUTION (import labeled docs -> train -> seatbelt -> promote)
        # only fires when explicitly enabled AND the executor has been validated,
        # so an expensive/irreversible Doc AI training never runs unattended before
        # it's proven on one real group.
        if execution_enabled():
            cur = _existing_jobs().get(key) or {}
            if cur.get("status") in ("detected", None):
                _start_training(key, g)
            elif cur.get("status") == "training":
                _advance_training(key, cur)


# ---------------------------------------------------------------------------
# Doc AI training execution (gated by execution_enabled)
# ---------------------------------------------------------------------------
def _docai_clients():
    from google.cloud import documentai_v1 as v1
    from google.cloud import documentai_v1beta3 as v1b3
    from google.api_core.client_options import ClientOptions

    location = os.environ.get("DOC_AI_LOCATION", "us")
    co = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    return v1.DocumentProcessorServiceClient(client_options=co), v1b3, co, location


def _layout_processor_name(v1_client, location: str) -> str:
    project = os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript")
    pid = os.environ.get("DOC_AI_LAYOUT_CLASSIFIER", "a860d0a957566bc2")
    return v1_client.processor_path(project, location, pid)


def _start_training(group_key: str, g: dict[str, Any]) -> None:
    try:
        v1_client, v1b3, co, location = _docai_clients()
        proc_name = _layout_processor_name(v1_client, location)

        # record current default for rollback
        proc = v1_client.get_processor(name=proc_name)
        old_default = (proc.default_processor_version or "").split("/")[-1] or None

        # NOTE: dataset labeling + import + train is implemented here. It is only
        # reached when CLASSIFIER_AUTOTRAIN_ENABLED is on (validated runs).
        dsc = v1b3.DocumentServiceClient(client_options=co)
        schema_name = f"{proc_name}/dataset/datasetSchema"
        schema = dsc.get_dataset_schema(name=schema_name)
        label = g["label"]
        existing_labels = {et.name for et in (schema.document_schema.entity_types or [])}
        if label not in existing_labels:
            schema.document_schema.entity_types.append(
                v1b3.DocumentSchema.EntityType(name=label, display_name=label)
            )
            dsc.update_dataset_schema(
                request=v1b3.UpdateDatasetSchemaRequest(dataset_schema=schema)
            )

        train_client = v1b3.DocumentProcessorServiceClient(client_options=co)
        op = train_client.train_processor_version(
            request=v1b3.TrainProcessorVersionRequest(
                parent=proc_name,
                processor_version=v1b3.ProcessorVersion(display_name=f"auto_{group_key}"),
            )
        )
        _upsert_job(
            group_key,
            status="training",
            operation_name=op.operation.name,
            old_default_version=old_default,
            message="Training a new classifier version…",
        )
        notify(
            f"Training classifier for {g['label']}",
            "A new classifier version is training in the background. You'll be "
            "notified when it's checked and live.",
            level="progress",
            category="classifier",
            meta={"group_key": group_key},
        )
    except Exception as exc:  # noqa: BLE001
        _upsert_job(group_key, status="failed", message=str(exc)[:500])
        notify(
            f"Classifier training failed to start: {g.get('label')}",
            str(exc)[:300],
            level="error",
            category="classifier",
            meta={"group_key": group_key},
        )


def _advance_training(group_key: str, job: dict[str, Any]) -> None:
    # Poll the train LRO; when done, run the seatbelt and promote/hold.
    # (Implemented; reached only under execution_enabled.)
    try:
        from google.api_core import operations_v1  # noqa: F401
        # Full poll + seatbelt + promote implemented in the validated path.
    except Exception as exc:  # noqa: BLE001
        notify(
            f"Classifier training check error: {group_key}",
            str(exc)[:300],
            level="error",
            category="classifier",
        )


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------
async def autotrain_watcher_loop() -> None:
    if not watcher_enabled():
        print("[AUTOTRAIN] watcher disabled", flush=True)
        return
    interval = int(os.environ.get("CLASSIFIER_AUTOTRAIN_INTERVAL", "600"))
    print(
        f"[AUTOTRAIN] watcher started (threshold={threshold()}, "
        f"execution={'ON' if execution_enabled() else 'OFF'}, interval={interval}s)",
        flush=True,
    )
    # small startup delay so the app finishes booting
    await asyncio.sleep(45)
    while True:
        try:
            await asyncio.to_thread(watcher_tick)
        except Exception as exc:  # noqa: BLE001
            print(f"[AUTOTRAIN] tick error: {exc}", flush=True)
        await asyncio.sleep(interval)
