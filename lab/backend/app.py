"""Transcript Extraction Lab — isolated FastAPI backend.

Runs on port 8900, uses its own SQLite DB and its own file store under lab/data.
It does NOT import or touch the main app in apps/backend.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from . import db, sample, vlm
from .pipeline import extract, render_pages

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
PAGES_DIR = os.path.join(DATA_DIR, "pages")
FRONTEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")

app = FastAPI(title="Transcript Extraction Lab")


@app.on_event("startup")
def _startup() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(PAGES_DIR, exist_ok=True)
    db.init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "vlm": vlm.health()}


@app.get("/api/runs")
def runs() -> list:
    return db.list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


def _ingest(filename: str, pdf_bytes: bytes) -> dict:
    run_id = db.create_run(filename)
    pdf_path = os.path.join(UPLOADS_DIR, f"{run_id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    # render page images now so the UI can show the transcript immediately
    page_count = render_pages(pdf_path, run_id)
    db.update_run(run_id, page_count=page_count)
    return db.get_run(run_id)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a PDF")
    data = await file.read()
    return _ingest(file.filename, data)


@app.post("/api/sample")
def make_sample() -> dict:
    tmp = os.path.join(DATA_DIR, "_sample_tmp.pdf")
    sample.generate(tmp)
    with open(tmp, "rb") as f:
        data = f.read()
    os.remove(tmp)
    return _ingest("sample_transcript.pdf", data)


@app.post("/api/extract/{run_id}")
def run_extract(run_id: int) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    pdf_path = os.path.join(UPLOADS_DIR, f"{run_id}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "pdf file missing")
    db.update_run(run_id, status="extracting")
    try:
        result = extract(pdf_path, run_id)
    except Exception as e:  # noqa: BLE001
        db.update_run(run_id, status="error", error=str(e))
        raise HTTPException(500, f"extraction failed: {e}")

    import json
    db.update_run(
        run_id,
        status="error" if result.get("vlm_error") else "done",
        model=result.get("model"),
        vlm_status="error" if result.get("vlm_error") else "ok",
        latency_ms=result.get("latency_ms"),
        error=result.get("vlm_error"),
        result_json=json.dumps(result),
    )
    return db.get_run(run_id)


@app.get("/api/pdf/{run_id}")
def get_pdf(run_id: int) -> FileResponse:
    path = os.path.join(UPLOADS_DIR, f"{run_id}.pdf")
    if not os.path.exists(path):
        raise HTTPException(404, "pdf not found")
    return FileResponse(path, media_type="application/pdf")


@app.get("/api/page/{run_id}/{page_no}")
def get_page(run_id: int, page_no: int) -> FileResponse:
    path = os.path.join(PAGES_DIR, f"{run_id}_p{page_no}.png")
    if not os.path.exists(path):
        raise HTTPException(404, "page image not found")
    return FileResponse(path, media_type="image/png")


# convenience for `python -m lab.backend.app` style runs is handled by run.sh
