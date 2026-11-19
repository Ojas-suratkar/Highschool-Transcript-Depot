"""Shared cleanup for orphaned 'uploaded' extraction_file_details rows.

A row at status ``uploaded`` whose source PDF has been removed from GCS is a
ghost: it has no file and no extracted content, yet the "Not Processed" badge
counts it forever. These helpers guarantee such ghosts never persist, via three
layers of defense:

  1. In-app delete handlers call :func:`purge_orphan_rows_for_blobs` right after
     deleting a blob, so the row goes with the file (event-driven).
  2. The startup / periodic reaper calls :func:`sweep_orphaned_uploaded`, a
     path-independent net that also catches files deleted directly in GCS or by
     any code path that forgot to clean up its row.
  3. ``POST /extractor/cleanup-orphaned-uploaded`` for on-demand use.

Only rows with ``process_status == 'uploaded'`` are ever removed; extracted
files (completed / needs_review / processing) are never touched.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("ORPHAN_SWEEP_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )


def _matches(blob_name: str, file_name: str) -> bool:
    """Exact match of a stored file_name against a full GCS blob path.

    Uses ``==`` / ``endswith('/<file_name>')`` rather than SQL LIKE because
    transcript file names contain underscores, which LIKE treats as wildcards
    and would over-match (deleting the wrong rows).
    """
    return blob_name == file_name or blob_name.endswith(f"/{file_name}")


def purge_orphan_rows_for_blobs(blob_names) -> int:
    """Delete ``uploaded`` rows whose file_name matches one of the just-removed
    blob names. Safe to call from any delete handler; returns rows removed.
    """
    clean = {b for b in (blob_names or []) if b}
    if not clean:
        return 0

    from app.db import SessionLocal
    from app.models import ExtractionFileDetails

    db = SessionLocal()
    try:
        rows = (
            db.query(ExtractionFileDetails)
            .filter(ExtractionFileDetails.process_status == "uploaded")
            .all()
        )
        to_delete = [
            r.id
            for r in rows
            if r.file_name and any(_matches(b, r.file_name) for b in clean)
        ]
        if to_delete:
            db.query(ExtractionFileDetails).filter(
                ExtractionFileDetails.id.in_(to_delete),
                ExtractionFileDetails.process_status == "uploaded",
            ).delete(synchronize_session=False)
            db.commit()
        return len(to_delete)
    except Exception:
        db.rollback()
        logger.exception("[ORPHAN-CLEANUP] purge_orphan_rows_for_blobs failed")
        return 0
    finally:
        db.close()


def sweep_orphaned_uploaded(min_age_seconds: int | None = None) -> list[int]:
    """Path-independent net: delete every ``uploaded`` row older than a guard
    window whose PDF is absent from the bucket. Returns the deleted ids.

    Conservative by design:
      - Only rows older than ``ORPHAN_SWEEP_MIN_AGE_SECONDS`` (default 1800s) are
        eligible, so a freshly uploaded or mid-batch file is never removed.
      - If the GCS listing raises OR comes back empty, nothing is deleted (an
        empty/partial read must never trigger a mass delete).
      - Only rows with a non-empty file_name and status still 'uploaded' at
        DELETE time are removed.
    """
    if not _enabled():
        return []

    if min_age_seconds is None:
        min_age_seconds = int(os.environ.get("ORPHAN_SWEEP_MIN_AGE_SECONDS", "1800"))

    from sqlalchemy import text
    from app.db import SessionLocal
    from app.services.cloud_storage_service import CloudStorageService

    # 1. Candidate rows (old enough to be safe).
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT id, file_name FROM extraction_file_details "
                "WHERE process_status = 'uploaded' "
                "AND upload_date < now() - (:age * interval '1 second')"
            ),
            {"age": min_age_seconds},
        ).fetchall()
    except Exception:
        logger.exception("[ORPHAN-SWEEP] candidate query failed")
        return []
    finally:
        db.close()

    if not rows:
        return []

    # 2. One full-bucket listing to test existence.
    try:
        storage = CloudStorageService()
        bucket_name = storage.ensure_bucket()
        bucket = storage.client.bucket(bucket_name)
        blob_names = [b.name for b in bucket.list_blobs()]
    except Exception:
        logger.exception("[ORPHAN-SWEEP] bucket listing failed; skipping (no deletions)")
        return []

    # An empty listing is treated as unsafe: never mass-delete on a zero-length
    # or partial read.
    if not blob_names:
        return []

    orphan_ids = [
        r[0]
        for r in rows
        if r[1] and not any(_matches(n, r[1]) for n in blob_names)
    ]
    if not orphan_ids:
        return []

    # 3. Delete (re-asserting status so a row that just started processing in a
    # concurrent request is never removed).
    db = SessionLocal()
    try:
        db.execute(
            text(
                "DELETE FROM extraction_file_details "
                "WHERE id = ANY(:ids) AND process_status = 'uploaded'"
            ),
            {"ids": orphan_ids},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("[ORPHAN-SWEEP] delete failed")
        return []
    finally:
        db.close()

    logger.info(
        "[ORPHAN-SWEEP] removed %d orphaned 'uploaded' rows (PDF missing): %s",
        len(orphan_ids),
        orphan_ids,
    )
    return orphan_ids
