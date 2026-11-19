import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse

logger = logging.getLogger(__name__)
from .routers.auth import router as auth_router
from .routers.microsoft_auth import router as microsoft_auth_router
from .routers.transcript_detector import router as transcript_detector_router
from .routers.transcript_types import router as transcript_types_router
from .routers.pipeline import router as pipeline_router
from app.routers.cloud_folder_locations import router as cloud_folder_locations
from app.routers.academic_term import router as academic_term
from app.routers.program_criteria import router as program_criteria
from app.routers.program_versions import router as program_versions
from app.routers.extractor import router as extractor_router
from app.routers.cloud_folder_batch import router as cloud_folder_batch_router
from app.routers.uc_doorway_course_mapping import router as uc_doorway_course_mapping_router
from app.routers.student_details import router as student_details_router
from app.routers.admissions import router as admissions_router
from app.routers.institution_ag_criteria import router as institution_ag_criteria_router
from app.routers.course_mapping import router as course_mapping_router
from app.routers.term_rules import router as term_rules_router
from app.routers.classifier_training import router as classifier_training_router
from app.routers.student_ag_summary import router as student_ag_summary_router
from app.routers.transcript_course_codes import router as transcript_course_codes_router
from app.routers.notifications import router as notifications_router

# Load environment variables from .env file
load_dotenv()


async def _map_pending_files():
    """On startup, trigger UC mapping for any files that have courses but no mappings yet."""
    await asyncio.sleep(3)  # let the DB pool settle first
    try:
        from sqlalchemy import text
        from app.db import AsyncSessionLocal
        from app.services.uc_doorway_course_mapping_service import run_uc_mapping_for_file

        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                SELECT DISTINCT sd.source_file
                FROM student_details sd
                JOIN course_details cd ON cd.s_id = sd.id
                WHERE sd.source_file IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM course_detail_mapping_uc_doorway_courses cdm
                      WHERE cdm.course_details_id = cd.id
                  )
            """))
            file_ids = [row[0] for row in result.fetchall()]

        if file_ids:
            logger.info(f"[STARTUP] Found {len(file_ids)} files with unmapped courses: {file_ids}")
            for fid in file_ids:
                await run_uc_mapping_for_file(AsyncSessionLocal, fid)
        else:
            logger.info("[STARTUP] All courses already mapped.")

        # Populate AG summary calc columns for students that don't have a summary yet
        from app.services.student_ag_computation_service import compute_ag_summaries_for_file
        from sqlalchemy import text as _text
        async with AsyncSessionLocal() as session:
            res = await session.execute(_text("""
                SELECT DISTINCT sd.source_file
                FROM student_details sd
                WHERE sd.source_file IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM student_ag_summary sas WHERE sas.student_id = sd.id
                  )
            """))
            unsummarized = [row[0] for row in res.fetchall()]
        for fid in unsummarized:
            await compute_ag_summaries_for_file(AsyncSessionLocal, fid)
    except Exception:
        logger.exception("[STARTUP] auto-mapping failed")


async def _reaper_loop():
    """Self-healing extraction watchdog so a batch can never stay frozen.

    1. On startup, EVERY file still in 'processing' is orphaned — the background
       task that owned it died with the previous container (deploy/crash/scale).
       Reset them to 'uploaded' so they can be picked up again.
    2. Periodically, a file that is still 'processing' across two passes (~20 min
       apart — far longer than a normal extraction) is treated as hung and reset.
    """
    from sqlalchemy import text
    from app.db import AsyncSessionLocal

    await asyncio.sleep(8)  # let the DB pool settle
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(
                "UPDATE extraction_file_details SET process_status='uploaded' "
                "WHERE process_status='processing' RETURNING id"
            ))
            reset = [r[0] for r in result.fetchall()]
            await session.commit()
            if reset:
                logger.info(f"[REAPER] startup: reset {len(reset)} orphaned 'processing' files -> uploaded: {reset}")
    except Exception:
        logger.exception("[REAPER] startup reset failed")

    # Startup pass: purge 'uploaded' rows whose PDF is gone from GCS, so a file
    # deleted while the service was down (or directly in the bucket) never
    # lingers as a "Not Processed" ghost. Path-independent safety net.
    try:
        from app.services.orphan_cleanup import sweep_orphaned_uploaded
        removed = await asyncio.to_thread(sweep_orphaned_uploaded)
        if removed:
            logger.info(f"[REAPER] startup: swept {len(removed)} orphaned 'uploaded' rows (PDF missing)")
    except Exception:
        logger.exception("[REAPER] startup orphan sweep failed")

    seen_processing: set[int] = set()
    while True:
        await asyncio.sleep(1200)  # 20 minutes
        try:
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(text(
                    "SELECT id FROM extraction_file_details WHERE process_status='processing'"
                ))).fetchall()
                current = {r[0] for r in rows}
                # Files 'processing' in BOTH the previous pass and now are hung.
                hung = current & seen_processing
                if hung:
                    await session.execute(text(
                        "UPDATE extraction_file_details SET process_status='uploaded' "
                        "WHERE id = ANY(:ids)"
                    ), {"ids": list(hung)})
                    await session.commit()
                    logger.info(f"[REAPER] reset {len(hung)} hung 'processing' files -> uploaded: {sorted(hung)}")
                    try:
                        from app.services.notification_service import notify
                        notify(
                            "Recovered stalled files",
                            f"{len(hung)} file(s) were stalled during extraction and have been "
                            "reset for reprocessing.",
                            level="warning",
                            category="extraction",
                            dedup_key="reaper-hung",
                            dedup_window_seconds=600,
                        )
                    except Exception:
                        pass
                # Carry forward only the ones we did NOT just reset.
                seen_processing = current - hung
        except Exception:
            logger.exception("[REAPER] periodic pass failed")

        # Periodic orphan sweep: any 'uploaded' row (older than the guard window)
        # whose PDF no longer exists gets removed, regardless of how it was
        # deleted — including a manual GCS deletion the app never saw.
        try:
            from app.services.orphan_cleanup import sweep_orphaned_uploaded
            removed = await asyncio.to_thread(sweep_orphaned_uploaded)
            if removed:
                logger.info(f"[REAPER] swept {len(removed)} orphaned 'uploaded' rows (PDF missing): {sorted(removed)}")
        except Exception:
            logger.exception("[REAPER] periodic orphan sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enlarge the default thread pool used by asyncio.to_thread. Extraction is
    # I/O-bound (Document AI + Gemini + GCS calls), and the default pool is only
    # min(32, cpu+4) = ~6 threads on a 2-CPU instance, which caps real parallelism
    # far below our Semaphore. A larger pool lets many Doc AI/Gemini calls run
    # concurrently and dramatically speeds up batch extraction.
    try:
        import concurrent.futures
        loop = asyncio.get_running_loop()
        pool_size = int(os.environ.get("EXTRACTION_THREAD_POOL", "48"))
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(
                max_workers=pool_size,
                thread_name_prefix="io-pool",
            )
        )
        print(f"[STARTUP] asyncio default thread pool set to {pool_size} workers", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[STARTUP] could not enlarge thread pool: {exc}", flush=True)

    # Ensure the notifications table exists up front so the feed is ready.
    try:
        from app.services.notification_service import ensure_table as _ensure_notif
        _ensure_notif()
    except Exception as exc:  # noqa: BLE001
        print(f"[STARTUP] notifications table init skipped: {exc}", flush=True)

    asyncio.create_task(_map_pending_files())
    asyncio.create_task(_reaper_loop())
    # Background watcher: auto-train the layout classifier when a new layout
    # group reaches the threshold (see classifier_autotrain_service).
    try:
        from app.services.classifier_autotrain_service import autotrain_watcher_loop
        asyncio.create_task(autotrain_watcher_loop())
    except Exception as exc:  # noqa: BLE001
        print(f"[STARTUP] autotrain watcher not started: {exc}", flush=True)
    yield


app = FastAPI(title="Transcript Hub Backend", lifespan=lifespan)


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    # Never leak internal error details / stack info to clients. Log server-side,
    # return a generic message. (Leaking str(exc) exposed SQL, file paths, etc.)
    import logging
    logging.getLogger("app").exception("Unhandled error on %s %s", request.method, request.url.path)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )

# configure CORS to allow Next.js frontend (read origin from env, default localhost)
FRONTEND_ORIGIN = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')
# also allow Vite default origin and localhost:5173 during dev
extra_origins = ['http://localhost:5173', 'http://127.0.0.1:5173']
origins = [FRONTEND_ORIGIN] + extra_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip-compress responses. The extractor list endpoints return multi-MB JSON
# (students + their courses + reconciliation); JSON compresses ~8-10x, so this
# turns a ~2.5 MB transfer into ~300 KB and makes those pages load much faster.
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Shared auth dependency. Routers serving sensitive data (student PII,
# transcripts, admission decisions, extraction/pipeline controls) are protected
# at the router level so no endpoint can be reached without a valid token.
# get_current_user accepts a Bearer header, X-Access-Token header, or the
# access_token cookie (the cookie keeps the PDF <iframe> authenticated).
from .routers.auth import get_current_user
_auth = [Depends(get_current_user)]

# Public routers (login / OTP / SSO callbacks) — must NOT require auth.
app.include_router(auth_router, prefix="/api")
app.include_router(microsoft_auth_router, prefix="/api")

# Protected routers.
app.include_router(pipeline_router, prefix="/api", dependencies=_auth)
app.include_router(cloud_folder_locations, prefix="/api", dependencies=_auth)
app.include_router(academic_term, prefix="/api", dependencies=_auth)
app.include_router(program_criteria, prefix="/api", dependencies=_auth)
app.include_router(program_versions, prefix="/api", dependencies=_auth)
app.include_router(extractor_router, prefix="/api", dependencies=_auth)
app.include_router(cloud_folder_batch_router, prefix="/api", dependencies=_auth)
app.include_router(uc_doorway_course_mapping_router, prefix="/api", dependencies=_auth)
app.include_router(student_details_router, prefix="/api", dependencies=_auth)
app.include_router(transcript_detector_router, prefix="/api", dependencies=_auth)
app.include_router(transcript_types_router, prefix="/api", dependencies=_auth)
app.include_router(admissions_router, prefix="/api", dependencies=_auth)
app.include_router(institution_ag_criteria_router, prefix="/api", dependencies=_auth)
app.include_router(course_mapping_router, prefix="/api", dependencies=_auth)
app.include_router(term_rules_router, prefix="/api", dependencies=_auth)
app.include_router(classifier_training_router, prefix="/api", dependencies=_auth)
app.include_router(student_ag_summary_router, prefix="/api", dependencies=_auth)
app.include_router(transcript_course_codes_router, prefix="/api", dependencies=_auth)
app.include_router(notifications_router, prefix="/api", dependencies=_auth)


@app.get('/health')
def health():
    return {'status': 'ok', 'time': __import__('time').time()}


# ── Google Search Console ownership verification ──────────────────────────────
# Cloud Run's *.run.app hostnames cannot be verified by DNS, so Search Console
# needs either the HTML file or the HTML meta tag. Both are driven by env vars
# and are inert until those are set, so this changes nothing until you deploy
# with the values Search Console hands you.
#
#   GOOGLE_SITE_VERIFICATION_FILE   full filename, e.g. google1a2b3c4d5e6f.html
#   GOOGLE_SITE_VERIFICATION_TOKEN  the content= value from the HTML-tag method
_GSV_FILE = os.environ.get("GOOGLE_SITE_VERIFICATION_FILE", "").strip()
_GSV_TOKEN = os.environ.get("GOOGLE_SITE_VERIFICATION_TOKEN", "").strip()


@app.get("/google{suffix}.html", include_in_schema=False)
def google_site_verification_file(suffix: str):
    """Serve the verification file Search Console fetches from the site root."""
    requested = f"google{suffix}.html"
    if not _GSV_FILE or requested != _GSV_FILE:
        raise HTTPException(status_code=404, detail="Not Found")
    return PlainTextResponse(f"google-site-verification: {_GSV_FILE}\n")


@app.get("/")
def root(request: Request):
    # Google's verifier asks for HTML. Only then, and only once a token is
    # configured, does this return a page carrying the meta tag; every other
    # caller keeps getting the JSON it has always received.
    if _GSV_TOKEN and "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            "<!doctype html><html><head>"
            f'<meta name="google-site-verification" content="{_GSV_TOKEN}">'
            "<title>Transcript Hub</title></head>"
            "<body>Transcript Hub backend.</body></html>"
        )
    return {"status": "ok", "service": "transcript-hub-backend"}
