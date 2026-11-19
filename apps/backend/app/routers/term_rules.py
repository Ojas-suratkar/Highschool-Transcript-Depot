from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_session, AsyncSessionLocal
from app import models
from app.routers.auth import get_current_user
from app.services.term_rule_extraction import document_hash
from app.services.cloud_storage_service import CloudStorageService

router = APIRouter(prefix="/term-rules", tags=["term-rules"])

# RAG-style: keep the active (approved) rules for a term in process memory and
# apply them from there, refreshing only when the ruleset version changes.
_rules_cache: dict[tuple[int, str], tuple[int, list]] = {}


def invalidate_rules_cache(inst_id: int, term: str) -> None:
    _rules_cache.pop((inst_id, term), None)


async def get_active_rules(db: AsyncSession, inst_id: int, term: str):
    """(ruleset, rules) for a term's approved ruleset, served from the in-memory
    cache when the version matches. Returns (None, None) if no approved ruleset."""
    rs = await latest_approved_ruleset(db, inst_id, term)
    if rs is None:
        return None, None
    key = (inst_id, term)
    cached = _rules_cache.get(key)
    if cached and cached[0] == rs.version:
        return rs, cached[1]
    # Only ACTIVE rules feed the student audits. Rules stored before the
    # retention change have no 'active' key — they were pre-filtered, so True.
    rules = [r for r in (rs.rules or []) if r.get("active", True)]
    _rules_cache[key] = (rs.version, rules)
    return rs, rules


class RuleSetOut(BaseModel):
    id: int
    year_intake: str
    version: int
    status: str
    error: Optional[str] = None
    pages_total: Optional[int] = None
    pages_done: Optional[int] = None
    document_name: Optional[str]
    document_hash: Optional[str]
    document_gcs_path: Optional[str] = None
    rules: Optional[list]
    unsupported: Optional[list]
    approved_by: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


async def _run_extraction(ruleset_id: int) -> None:
    """Background: (re-)fetch the handbook from GCS and extract rules window by
    window (any document size). Progress (pages done/total) and partial rules are
    committed after every window so the UI shows live progress and a crash/restart
    loses at most one window; /reprocess restarts from the stored PDF."""
    from app.services.term_rule_extraction import (
        count_pages, plan_windows, extract_rules_from_window, merge_extractions,
        classify_relevance, triage_ag_pages, extract_pages, bind_rules_to_engine,
    )

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(models.TermRuleSet).where(models.TermRuleSet.id == ruleset_id)
        )).scalars().first()
        if not row or not row.document_gcs_path:
            return

        # LEADER ELECTION: claim the row by stamping started_at. If another task
        # (a self-heal revive, a reprocess) claims it later, this task sees a
        # different stamp at its next commit point and exits quietly — so at most
        # one writer survives and progress never flip-flops between two runs.
        claim = datetime.now(timezone.utc)
        row.started_at = claim
        # Mark processing at claim time so a stale 'approved/draft' row being
        # re-extracted is never mistaken for an active ruleset mid-run.
        row.status = "processing"
        await db.commit()

        async def _still_leader() -> bool:
            current = (await db.execute(
                select(models.TermRuleSet.started_at).where(
                    models.TermRuleSet.id == ruleset_id
                )
            )).scalar_one_or_none()
            return current == claim

        try:
            storage = CloudStorageService()
            pdf_bytes = await asyncio.to_thread(
                storage.download_file, row.document_bucket, row.document_gcs_path
            )
            total = await asyncio.to_thread(count_pages, pdf_bytes)

            # TRIAGE: one fast pass finds the pages that actually contain A-G
            # rules (a handbook is mostly applications/immunization/residency —
            # irrelevant). Deep extraction then reads ONLY those pages, so junk
            # never enters and the run takes ~1-2 min instead of ~10.
            selected = await asyncio.to_thread(triage_ag_pages, pdf_bytes, total)
            if not await _still_leader():
                return
            sub_pdf = await asyncio.to_thread(extract_pages, pdf_bytes, selected)
            subtotal = len(selected)
            windows = plan_windows(subtotal)
            parts: list[dict] = []
            row.pages_done = 0
            row.pages_total = subtotal
            await db.commit()

            # Windows extract in PARALLEL (bounded), not one after another —
            # a large handbook costs ~one window's latency, not the sum of all.
            import os as _os
            sem = asyncio.Semaphore(int(_os.environ.get("EXTRACT_WINDOW_CONCURRENCY", "8")))

            async def _window(w):
                ws, we = w
                async with sem:
                    p = await asyncio.to_thread(
                        extract_rules_from_window, sub_pdf, ws, we, subtotal
                    )
                return (we - ws), p

            covered = 0
            for coro in asyncio.as_completed([_window(w) for w in windows]):
                span, part = await coro
                if not await _still_leader():
                    return  # a newer task owns this row now
                parts.append(part)
                covered = min(subtotal, covered + span)
                merged = merge_extractions(parts)
                row.pages_done = covered
                row.rules = merged["rules"]          # partial rules grow live
                row.unsupported = merged["unsupported"]
                row.updated_at = datetime.now(timezone.utc)
                await db.commit()

            # Final pass: remap sub-PDF page numbers to the original document,
            # mark A-G relevance (type gate + batched Gemini check, fail-open),
            # and compile rules to deterministic-engine bindings.
            final = merge_extractions(parts)
            for rule in final["rules"]:
                sp = rule.get("source_page")
                if isinstance(sp, int) and 1 <= sp <= subtotal:
                    rule["source_page"] = selected[sp - 1] + 1
            final["rules"] = await asyncio.to_thread(classify_relevance, final["rules"])
            final["rules"] = bind_rules_to_engine(final["rules"])
            if not await _still_leader():
                return
            row.rules = final["rules"]
            row.unsupported = final["unsupported"]
            # classify/bind mutate the SAME dicts the window loop already
            # committed, so the new value compares equal and SQLAlchemy would
            # silently skip the UPDATE — force it (this is why earlier runs
            # stored unclassified rules).
            flag_modified(row, "rules")
            flag_modified(row, "unsupported")

            row.status = "draft"
            row.error = None
        except Exception as exc:  # noqa: BLE001
            if not await _still_leader():
                return  # don't overwrite a newer run's state with our error
            row.status = "error"
            row.error = str(exc)[:2000]
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()


async def _latest(db: AsyncSession, inst_id: int, term: str) -> Optional[models.TermRuleSet]:
    return (await db.execute(
        select(models.TermRuleSet)
        .where(
            models.TermRuleSet.institution_id == inst_id,
            models.TermRuleSet.year_intake == term,
        )
        .order_by(models.TermRuleSet.version.desc())
    )).scalars().first()


async def latest_approved_ruleset(db: AsyncSession, inst_id: int, term: str):
    """Used by the evaluator/cadence — the active (approved) ruleset for a term."""
    return (await db.execute(
        select(models.TermRuleSet)
        .where(
            models.TermRuleSet.institution_id == inst_id,
            models.TermRuleSet.year_intake == term,
            models.TermRuleSet.status == "approved",
        )
        .order_by(models.TermRuleSet.version.desc())
    )).scalars().first()


# A processing job with no progress for this long is considered stalled
# (Cloud Run throttled the background task or recycled the instance). Must be
# comfortably longer than the worst-case single window (dense pages + bisection
# retries), or the healer revives a job that is merely slow and two tasks race.
_STALL_SECONDS = 600


@router.get("", response_model=Optional[RuleSetOut])
async def get_ruleset(
    background_tasks: BackgroundTasks,
    term: str = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        return None
    row = await _latest(db, inst_id, term)

    # SELF-HEAL: the UI polls this endpoint while processing. If the background
    # extraction stalled (no commit for _STALL_SECONDS), revive it — it resumes
    # from the last committed window. Bumping updated_at first ensures only one
    # revive fires per stall window even with concurrent polls.
    if (
        row is not None
        and row.status == "processing"
        and row.document_gcs_path
        and row.updated_at is not None
        and (datetime.now(timezone.utc) - row.updated_at).total_seconds() > _STALL_SECONDS
    ):
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
        background_tasks.add_task(_run_extraction, row.id)

    return row


@router.post("/upload", response_model=RuleSetOut)
async def upload_and_extract(
    background_tasks: BackgroundTasks,
    term: str = Query(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Kick off structured rule extraction from an uploaded handbook PDF. Returns
    immediately with a 'processing' ruleset; Gemini runs in the background (so the
    request never times out) and the UI polls GET /term-rules for the result. The
    PDF is processed in memory and discarded — we store only the rules + a hash."""
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        raise HTTPException(status_code=403, detail="User not linked to an institution")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF handbook.")
    digest = document_hash(pdf_bytes)

    # Store the handbook in the term's GCS handbook/ folder (replaces any prior
    # one), so extraction can re-fetch it reliably. Blocking -> run in a thread.
    storage = CloudStorageService()
    try:
        bucket, blob_path = await asyncio.to_thread(
            storage.store_handbook, term, pdf_bytes, file.filename or "handbook.pdf"
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not store handbook: {exc}")

    # One active handbook/ruleset per term: a new upload overrides the previous.
    latest = await _latest(db, inst_id, term)
    next_version = (latest.version + 1) if latest else 1
    await db.execute(
        sa_delete(models.TermRuleSet).where(
            models.TermRuleSet.institution_id == inst_id,
            models.TermRuleSet.year_intake == term,
        )
    )
    row = models.TermRuleSet(
        institution_id=inst_id,
        year_intake=term,
        version=next_version,
        status="processing",
        document_name=file.filename,
        document_hash=digest,
        document_bucket=bucket,
        document_gcs_path=blob_path,
        rules=None,
        unsupported=None,
        started_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    invalidate_rules_cache(inst_id, term)
    background_tasks.add_task(_run_extraction, row.id)
    return row


@router.post("/{ruleset_id}/reprocess", response_model=RuleSetOut)
async def reprocess(
    ruleset_id: int,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retry extraction from the handbook already stored in GCS (for a stuck or
    errored ruleset) — no re-upload needed."""
    inst_id = getattr(current_user, "institution_id", None)
    row = (await db.execute(
        select(models.TermRuleSet).where(
            models.TermRuleSet.id == ruleset_id,
            models.TermRuleSet.institution_id == inst_id,
        )
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Ruleset not found")
    if not row.document_gcs_path:
        raise HTTPException(status_code=400, detail="No stored handbook to reprocess")
    row.status = "processing"
    row.error = None
    # Keep pages_done/pages_total/rules: _run_extraction RESUMES from the first
    # unfinished window instead of restarting the whole document.
    row.started_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    background_tasks.add_task(_run_extraction, row.id)
    return row


class RulesUpdateIn(BaseModel):
    rules: list[dict[str, Any]]


@router.put("/{ruleset_id}/rules", response_model=RuleSetOut)
async def update_rules(
    ruleset_id: int,
    payload: RulesUpdateIn,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Save reviewer edits (approve/edit/reject) to a draft ruleset's rules."""
    inst_id = getattr(current_user, "institution_id", None)
    row = (await db.execute(
        select(models.TermRuleSet).where(
            models.TermRuleSet.id == ruleset_id,
            models.TermRuleSet.institution_id == inst_id,
        )
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Ruleset not found")
    row.rules = payload.rules
    # JSONB gotcha: if the new list compares equal to the committed value (e.g.
    # same dicts mutated in place upstream), SQLAlchemy skips the UPDATE. Force it.
    flag_modified(row, "rules")
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{ruleset_id}/approve", response_model=RuleSetOut)
async def approve_ruleset(
    ruleset_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Approve a draft ruleset — it becomes the active version for the term and
    (via a higher version number) invalidates cached LLM verdicts."""
    inst_id = getattr(current_user, "institution_id", None)
    row = (await db.execute(
        select(models.TermRuleSet).where(
            models.TermRuleSet.id == ruleset_id,
            models.TermRuleSet.institution_id == inst_id,
        )
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Ruleset not found")

    # RETENTION: approval marks rules active — it never discards anything. The
    # full extraction (approved or not, relevant or excluded) stays stored for
    # audit/re-review; only rules with active=True drive the student audits.
    for r in (row.rules or []):
        r["active"] = bool(r.get("approved") and r.get("relevant", True))
    flag_modified(row, "rules")  # JSONB equality gotcha — force the UPDATE

    # COMPILE TO ENGINE: approved rules with an engine binding auto-configure
    # the term's deterministic criteria (required semesters, strict toggles) —
    # enforced in code at decision time, no LLM involved.
    ag_patch: dict[str, int] = {}
    cfg_patch: dict[str, Any] = {}
    for r in [x for x in (row.rules or []) if x.get("active")]:
        patch = (r.get("engine_binding") or {}).get("patch") or {}
        for a, v in (patch.get("ag_required") or {}).items():
            ag_patch[str(a).lower()] = int(v)
        cfg_patch.update(patch.get("rule_config") or {})
    if ag_patch or cfg_patch:
        crit = (await db.execute(
            select(models.InstitutionAgCriteria).where(
                models.InstitutionAgCriteria.institution_id == inst_id,
                models.InstitutionAgCriteria.year_intake == row.year_intake,
            )
        )).scalars().first()
        if crit is None:
            crit = models.InstitutionAgCriteria(
                institution_id=inst_id, year_intake=row.year_intake
            )
            db.add(crit)
        for a, sems in ag_patch.items():
            col = f"{a}_required"
            if hasattr(crit, col):
                setattr(crit, col, sems)
        merged_cfg = dict(crit.rule_config or {})
        merged_cfg.update(cfg_patch)
        crit.rule_config = merged_cfg

    row.status = "approved"
    row.approved_by = getattr(current_user, "email", None) or str(getattr(current_user, "id", ""))
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    invalidate_rules_cache(inst_id, row.year_intake)
    return row


class VerdictOut(BaseModel):
    id: int
    student_id: int
    ruleset_version: int
    decision: Optional[str]
    baseline_decision: Optional[str]
    reason: Optional[str]
    per_area: Optional[list]
    learned_rules: Optional[list]
    overridden: bool
    override_decision: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/verdict", response_model=Optional[VerdictOut])
async def get_verdict(
    student_id: int = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Latest cached Gemini verdict for a student (reasoning + citations + override)."""
    return (await db.execute(
        select(models.StudentLlmVerdict)
        .where(models.StudentLlmVerdict.student_id == student_id)
        .order_by(models.StudentLlmVerdict.ruleset_version.desc())
    )).scalars().first()


@router.get("/learned")
async def learned_rules(
    term: str = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Aggregate the new rules Gemini had to apply (crystallization) across this
    term's verdicts — surfaced so a human can review and promote them into the
    ruleset. Deduped by title with an occurrence count."""
    inst_id = getattr(current_user, "institution_id", None)
    if not inst_id:
        return []
    rs = await _latest(db, inst_id, term)
    if not rs:
        return []
    rows = (await db.execute(
        select(models.StudentLlmVerdict.learned_rules).where(
            models.StudentLlmVerdict.institution_id == inst_id,
            models.StudentLlmVerdict.ruleset_version == rs.version,
        )
    )).scalars().all()
    agg: dict[str, dict[str, Any]] = {}
    for lst in rows:
        for lr in (lst or []):
            if not isinstance(lr, dict):
                continue
            title = str(lr.get("title") or "").strip()
            if not title:
                continue
            key = title.lower()
            if key not in agg:
                agg[key] = {
                    "title": title,
                    "why_applied": lr.get("why_applied"),
                    "source": lr.get("source"),
                    "count": 0,
                }
            agg[key]["count"] += 1
    return sorted(agg.values(), key=lambda x: x["count"], reverse=True)


@router.get("/verdict/history", response_model=list[VerdictOut])
async def verdict_history(
    student_id: int = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """All audits for a student, newest ruleset version first — so reviewers can
    compare the current reasoning against previous handbook versions."""
    return (await db.execute(
        select(models.StudentLlmVerdict)
        .where(models.StudentLlmVerdict.student_id == student_id)
        .order_by(models.StudentLlmVerdict.ruleset_version.desc())
    )).scalars().all()


class VerdictOverrideIn(BaseModel):
    student_id: int
    decision: Optional[str] = None  # null/empty clears the override


@router.post("/verdict/override", response_model=Optional[VerdictOut])
async def override_verdict(
    payload: VerdictOverrideIn,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Human override of the LLM verdict. Also updates the saved admission decision
    so the decision pages reflect it immediately."""
    verdict = (await db.execute(
        select(models.StudentLlmVerdict)
        .where(models.StudentLlmVerdict.student_id == payload.student_id)
        .order_by(models.StudentLlmVerdict.ruleset_version.desc())
    )).scalars().first()
    if not verdict:
        raise HTTPException(status_code=404, detail="No verdict for this student yet")

    dec = (payload.decision or "").strip().lower() or None
    if dec and dec not in {"admitted", "denied", "waitlisted"}:
        raise HTTPException(status_code=400, detail=f"Invalid decision '{payload.decision}'")

    verdict.overridden = dec is not None
    verdict.override_decision = dec
    verdict.updated_at = datetime.now(timezone.utc)

    # Reflect on the saved summary (drives the decision pages).
    summary = (await db.execute(
        select(models.StudentAgSummary).where(
            models.StudentAgSummary.student_id == payload.student_id
        )
    )).scalars().first()
    if summary:
        summary.admission_decision = dec or verdict.decision

    await db.commit()
    await db.refresh(verdict)
    return verdict
