"""Generalized, training-free transcript extraction pipeline.

Design (the architecture we're testing):
  1. Anchor    - ground-truth text tokens from the PDF text layer (when present).
  2. Organize  - a VLM reads the page, but split into overlapping horizontal BANDS
                 (full width) so it never loses its place on a dense/two-column
                 transcript. Each band is extracted in parallel, one record per
                 graded semester cell (S1/S2/Sum), then merged + de-duplicated.
  3. Verify    - deterministic gates: grades must be real grade tokens, credits
                 must sum to the printed total, values should match the anchor.
                 Anything that fails is flagged for review. Never silently wrong.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

from . import vlm

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PAGES_DIR = os.path.join(DATA_DIR, "pages")
RENDER_DPI = 150
MAX_PAGES_TO_VLM = 4

# Banding config (overridable via env for tuning without a code change).
# Defaults tuned for a slow hosted model: SEQUENTIAL small bands so no single
# request is heavy enough — and no concurrency contention — to trip the endpoint's
# gateway timeout. Each band is a light call the 90B can finish in time.
TILE_BANDS = max(1, int(os.getenv("LAB_TILE_BANDS", "5")))        # bands per page
TILE_OVERLAP = float(os.getenv("LAB_TILE_OVERLAP", "0.16"))       # fractional overlap
TILE_DPI = int(os.getenv("LAB_TILE_DPI", "190"))
# Parallel: with a FAST model each band call completes quickly, so running them at
# once gives ~single-call wall time (target < 30s) without tripping the gateway.
TILE_WORKERS = max(1, int(os.getenv("LAB_TILE_WORKERS", "4")))
MAX_BAND_PAGES = max(1, int(os.getenv("LAB_TILE_MAX_PAGES", "3")))

GRADE_WHITELIST = {
    "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F",
    "P", "NP", "CR", "NC", "I", "W", "WF", "AU", "S", "U",
}

# Term-block headers (school name / district / year range) are NOT courses — the
# VLM sometimes emits them as rows. Drop any "course" whose title looks like one.
_HEADER_RE = re.compile(
    r"(high\s*school|middle\s*school|\bunified\b|\bU\.?S\.?D\.?\b|\bdistrict\b"
    r"|^\s*'?\d{2}\s*[-/]\s*'?\d{2}\b|\b\d{4}\s*[-/]\s*\d{4}\b)",
    re.I,
)


def _is_header_row(r: dict[str, Any]) -> bool:
    title = str(r.get("title") or "").strip()
    if not title:
        return False
    if _HEADER_RE.search(title):
        return True
    # a "course" whose title is just the term header it sits under
    if _norm(title) and _norm(title) == _norm(r.get("term")):
        return True
    return False


def _term_sig(term: Any) -> str:
    """A STABLE signature for a term header: grade level + season + year. This
    distinguishes the same course taken in different terms (so real repeats are
    kept) while ignoring band-to-band variation in the header's exact wording
    (so an overlap duplicate still merges). e.g. 'Grade 9 Spring 2021-2022' and
    'Spring 2021-2022' both -> '9spring2122'."""
    s = str(term or "").lower()
    parts: list[str] = []
    # season + year uniquely identifies a term for one student (one grade level per
    # academic year), and is more robust than the "Grade N" label to a band edge.
    for season in ("fall", "spring", "summer", "winter", "intersession"):
        if season in s:
            parts.append(season)
            break
    m = re.search(r"\b(\d{2})\s*[-/]\s*(\d{2})\b", s) or re.search(r"\b(20\d{2})\b", s)
    parts.append(re.sub(r"\D", "", m.group(0)) if m else "")
    sig = "".join(parts)
    return sig or _norm(term)[:10]


# --------------------------------------------------------------------------- #
# 1. Anchor + page render
# --------------------------------------------------------------------------- #

def render_pages(pdf_path: str, run_id: int) -> int:
    """Render each page to a PNG (so the UI can show it immediately). Returns page count."""
    os.makedirs(PAGES_DIR, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(os.path.join(PAGES_DIR, f"{run_id}_p{i + 1}.png"))
        return doc.page_count
    finally:
        doc.close()


def render_and_anchor(pdf_path: str, run_id: int) -> dict[str, Any]:
    """Ensure page PNGs exist and extract the ground-truth token layer."""
    os.makedirs(PAGES_DIR, exist_ok=True)
    doc = fitz.open(pdf_path)
    pages: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    try:
        mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
        for i, page in enumerate(doc):
            png_path = os.path.join(PAGES_DIR, f"{run_id}_p{i + 1}.png")
            if not os.path.exists(png_path):
                page.get_pixmap(matrix=mat, alpha=False).save(png_path)
            pages.append({"page": i + 1, "png": png_path})
            for w in page.get_text("words"):
                x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]
                if str(word).strip():
                    tokens.append({"page": i + 1, "text": str(word),
                                   "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]})
            full_text_parts.append(page.get_text("text") or "")
    finally:
        doc.close()

    full_text = "\n".join(full_text_parts)
    return {
        "pages": pages,
        "page_count": len(pages),
        "tokens": tokens,
        "full_text": full_text,
        "has_text_layer": len("".join(full_text.split())) > 30,
    }


def _encode_pil_for_vlm(img: Image.Image, max_b64: int = 170_000) -> str:
    """JPEG-encode a PIL image, stepping quality/scale down until it fits under the
    hosted endpoint's inline-image cap (~180 KB base64). A band has fewer rows than
    the full page, so within this fixed byte budget each row keeps more detail."""
    img = img.convert("RGB")
    for quality, scale in ((88, 1.0), (82, 1.0), (78, 0.9), (72, 0.8), (66, 0.65), (60, 0.5)):
        im = img if scale == 1.0 else img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        if len(b64) <= max_b64:
            return b64
    return b64  # best effort


def _band_tiles(pdf_path: str) -> list[dict[str, Any]]:
    """Split each page into overlapping full-width horizontal bands. Full width keeps
    every row (and both columns of a two-column layout) intact; the overlap makes
    sure a row split by a band edge is captured whole in the neighbouring band."""
    doc = fitz.open(pdf_path)
    tiles: list[dict[str, Any]] = []
    try:
        mat = fitz.Matrix(TILE_DPI / 72, TILE_DPI / 72)
        for pi, page in enumerate(doc):
            if pi >= MAX_BAND_PAGES:
                break
            r = page.rect
            step = r.height / TILE_BANDS
            for bi in range(TILE_BANDS):
                y0 = max(r.y0, r.y0 + step * bi - TILE_OVERLAP * step)
                y1 = min(r.y1, r.y0 + step * (bi + 1) + TILE_OVERLAP * step)
                pix = page.get_pixmap(matrix=mat, alpha=False, clip=fitz.Rect(r.x0, y0, r.x1, y1))
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                tiles.append({"page": pi + 1, "band": bi + 1, "b64": _encode_pil_for_vlm(img)})
    finally:
        doc.close()
    return tiles


# --------------------------------------------------------------------------- #
# 2. VLM organize
# --------------------------------------------------------------------------- #

TILE_PROMPT = """You are reading ONE horizontal strip cropped from a United States high school transcript.

The strip may contain TWO course tables side by side (a LEFT table and a RIGHT table).
Read BOTH — the entire left table first, then the entire right table.

Each course row may show grades in several term/semester columns (for example S1, S2,
Sum, or Fall / Spring). Output ONE record for EACH grade cell that has a grade: a course
with an S1 grade and an S2 grade becomes TWO records.

Extract ONLY what is literally printed. Do not guess, translate, or compute anything.

Respond in JSON exactly (respond in JSON):
{
  "issuer": { "school_name": string or null,
              "printed_totals": { "gpa": number or null, "total_credits": number or null } },
  "student": { "name": string or null },
  "courses": [
    {
      "term": string or null,      // the term-block header this row sits under,
                                   // e.g. "21-22 California High School", "24-25 La Mirada High School"
      "course_id": string or null, // the course number/code from the Crse / Course-ID column
                                   // if the transcript has one, e.g. "0855", "P 2986" (else null)
      "title": string,             // course title, normal reading order
      "semester": string or null,  // which grade column this grade came from: "S1","S2","Sum" (or "Fall"/"Spring")
      "grade": string or null,     // the mark exactly as printed, e.g. "A", "B+", "C-"
      "credits": number or null,   // credits for THIS grade cell, e.g. 5.00
      "confidence": number,        // 0.0-1.0
      "uncertain_fields": [string]
    }
  ]
}

Rules:
- A line that is a term/section HEADER — a school or district name or a year range
  (e.g. "21-22 California High School", "24-25 La Mirada High School",
  "Norwalk-La Mirada USD") — is NOT a course. Never output it as a course row; use it
  as the "term" value for the course rows listed beneath it.
- Read EVERY course row visible in the strip, top to bottom, in BOTH columns. Do not skip any, do not stop early.
- One record per graded semester cell (S1 and S2 of the same course are two records).
- Only include a row whose title and at least one grade are clearly readable in this strip
  (rows cut off at the very top/bottom edge will be captured whole in the neighbouring strip).
- Fill issuer / student / printed_totals only if they are visible in this strip, else null.
Return ONLY the JSON, no markdown, no commentary.
"""


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # salvage the outermost {...}
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except Exception:
            pass
    # repair a truncated response: cut to the last complete element, then
    # append the closing brackets that are still open (small models often stop
    # a brace or two short). This keeps whatever rows DID come through so the
    # verification gates can judge them, rather than discarding everything.
    return _repair_truncated_json(text)


def _repair_truncated_json(text: str) -> dict[str, Any] | None:
    a = text.find("{")
    if a == -1:
        return None
    s = text[a:]
    # cut to the last structural close so we drop any dangling partial object
    cut = max(s.rfind("}"), s.rfind("]"))
    if cut == -1:
        return None
    s = s[:cut + 1].rstrip().rstrip(",")
    # figure out which brackets are still open (ignoring those inside strings)
    stack: list[str] = []
    in_str = esc = False
    for ch in s:
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    s += "".join("}" if b == "{" else "]" for b in reversed(stack))
    try:
        return json.loads(s)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 3. Verification gates
# --------------------------------------------------------------------------- #

def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _in_anchor(value: Any, anchor_norm: str, anchor_lines_norm: list[str]) -> bool:
    v = _norm(value)
    if not v:
        return True  # nothing to check
    if len(v) <= 2:
        return v in anchor_norm  # short tokens: substring only
    if v in anchor_norm:
        return True
    # fuzzy: does any line contain a close match?
    for line in anchor_lines_norm:
        if v in line:
            return True
        if SequenceMatcher(None, v, line).ratio() >= 0.85:
            return True
    return False


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)))
    except Exception:
        return None


def _valid_letter_grade(g: Any) -> bool:
    """A real course carries a letter mark (A/B/C/D/F±, P, CR, ...). GPA numbers,
    credit totals and summary labels do NOT — that's how we tell the course table
    apart from the Credit-Summary / GPA panel the model sometimes scrapes."""
    s = str(g or "").strip().upper()
    return s in GRADE_WHITELIST or bool(re.fullmatch(r"[A-F][+-]?", s))


def _season_of(term: Any) -> str:
    s = str(term or "").lower()
    for season in ("fall", "spring", "summer", "winter", "intersession"):
        if season in s:
            return season
    return ""


def _year_of(term: Any) -> str:
    s = str(term or "").lower()
    m = re.search(r"\b(\d{2})\s*[-/]\s*(\d{2})\b", s) or re.search(r"\b(20\d{2})\b", s)
    return re.sub(r"\D", "", m.group(0)) if m else ""


def _merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn raw per-band records into the clean course list:
    1. keep only real courses — a valid LETTER grade (drops GPA / credit-summary rows);
    2. de-duplicate overlap between bands, keyed on title + semester + grade + a stable
       term signature (so the same course in different terms stays distinct);
    3. drop a leftover seasonless duplicate when a seasoned sibling exists (the same
       course-term seen in two bands, one of which had its season header cut off)."""
    best: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []

    def score(x: dict[str, Any]) -> tuple:
        return (1 if str(x.get("grade") or "").strip() else 0, _num(x.get("confidence")) or 0.0)

    def ident(r: dict[str, Any]) -> str:
        # course_id is spelling-stable across bands; fall back to the title.
        return _norm(r.get("course_id")) or _norm(r.get("title"))

    for r in records:
        if _is_header_row(r) or not _valid_letter_grade(r.get("grade")):
            continue
        ident_v = ident(r)
        if not ident_v:
            continue
        # Key on course id (or title) + semester + grade + a stable term signature.
        # The id keeps the same course in different terms distinct while collapsing
        # band-overlap duplicates even when the title is transcribed differently.
        key = (ident_v, _norm(r.get("semester")), _norm(r.get("grade")), _term_sig(r.get("term")))
        if key not in best:
            best[key] = r
            order.append(key)
        elif score(r) > score(best[key]):
            best[key] = r

    result = [best[k] for k in order]
    # Drop a leftover seasonless duplicate when a seasoned sibling exists (same
    # course-term seen in two bands, one with its season header cut off).
    seasoned = {
        (ident(r), _norm(r.get("grade")), _year_of(r.get("term")))
        for r in result if _season_of(r.get("term"))
    }
    return [
        r for r in result
        if _season_of(r.get("term"))
        or (ident(r), _norm(r.get("grade")), _year_of(r.get("term"))) not in seasoned
    ]


def verify(parsed: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any]:
    anchor_norm = _norm(anchor["full_text"])
    anchor_lines_norm = [_norm(l) for l in anchor["full_text"].splitlines() if l.strip()]
    has_text = anchor["has_text_layer"]

    courses = parsed.get("courses") or []
    verified_rows = 0
    sum_credits = 0.0
    checked_courses: list[dict[str, Any]] = []

    for c in courses:
        flags: list[str] = []
        title = str(c.get("title") or "").strip()
        grade = str(c.get("grade") or "").strip()
        if has_text and title and not _in_anchor(title, anchor_norm, anchor_lines_norm):
            flags.append("title_not_in_ocr")
        gU = grade.upper()
        if gU and gU not in GRADE_WHITELIST and not re.fullmatch(r"\d{1,3}(\.\d+)?%?", gU):
            flags.append("grade_not_recognized")
        conf = _num(c.get("confidence"))
        if conf is not None and conf < 0.6:
            flags.append("low_confidence")
        if c.get("uncertain_fields"):
            flags.append("model_uncertain")
        if not title:
            flags.append("missing_title")
        if not grade:
            flags.append("missing_grade")

        cr = _num(c.get("credits"))
        if cr is not None:
            sum_credits += cr

        needs_review = bool(flags)
        if not needs_review:
            verified_rows += 1
        checked_courses.append({
            "term": c.get("term"),
            "course_id": c.get("course_id") or c.get("semester"),
            "semester": c.get("semester"),
            "title": c.get("title"),
            "grade": c.get("grade"),
            "credit_attempted": cr,
            "credit_completed": cr,
            "confidence": conf,
            "uncertain_fields": c.get("uncertain_fields") or [],
            "flags": flags,
            "needs_review": needs_review,
        })

    printed = (parsed.get("issuer") or {}).get("printed_totals") or {}
    printed_credits = _num(printed.get("total_credits"))
    credits_reconcile: bool | None = None
    credits_delta: float | None = None
    if printed_credits is not None:
        credits_delta = round(sum_credits - printed_credits, 2)
        credits_reconcile = abs(credits_delta) <= 0.5

    doc_flags: list[str] = []
    if credits_reconcile is False:
        doc_flags.append("credits_do_not_reconcile")
    if not has_text:
        doc_flags.append("no_text_layer_anchor")

    total = len(courses)
    doc_verified = (total > 0 and verified_rows == total and credits_reconcile is not False)

    return {
        "courses": checked_courses,
        "summary": {
            "total_rows": total,
            "verified_rows": verified_rows,
            "needs_review_rows": total - verified_rows,
            "expected_row_count": total,
            "row_count_ok": True,
            "sum_credit_completed": round(sum_credits, 2),
            "printed_total_credits": printed_credits,
            "credits_delta": credits_delta,
            "credits_reconcile": credits_reconcile,
            "has_text_layer": has_text,
            "doc_flags": doc_flags,
            "doc_verified": doc_verified,
        },
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def extract(pdf_path: str, run_id: int) -> dict[str, Any]:
    anchor = render_and_anchor(pdf_path, run_id)
    tiles = _band_tiles(pdf_path)

    def run_tile(t: dict[str, Any]) -> dict[str, Any]:
        out = vlm.run_vlm([t["b64"]], TILE_PROMPT)
        parsed = _parse_json(out["text"]) or {}
        # A smaller model sometimes ignores the format and returns a prose
        # description instead of JSON (losing that band's courses). Retry once,
        # demanding JSON only.
        if not out.get("error") and not isinstance(parsed.get("courses"), list):
            strict = "OUTPUT A SINGLE JSON OBJECT ONLY — no prose, no markdown, no explanation.\n\n" + TILE_PROMPT
            out2 = vlm.run_vlm([t["b64"]], strict)
            parsed2 = _parse_json(out2["text"]) or {}
            if isinstance(parsed2.get("courses"), list):
                out, parsed = out2, parsed2
        return {"tile": t, "out": out, "parsed": parsed}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=TILE_WORKERS) as ex:
        results = list(ex.map(run_tile, tiles))
    total_latency = int((time.time() - t0) * 1000)

    all_records: list[dict[str, Any]] = []
    issuer: str | None = None
    student: str | None = None
    cred_candidates: list[float] = []
    gpa_candidates: list[float] = []
    errors: list[str] = []
    tile_debug: list[dict[str, Any]] = []

    for res in results:
        p, out = res["parsed"], res["out"]
        if out.get("error"):
            errors.append(out["error"])
        recs = p.get("courses") or []
        all_records.extend(recs)
        iss = p.get("issuer") or {}
        if iss.get("school_name") and not issuer:
            issuer = iss.get("school_name")
        pt = iss.get("printed_totals") or {}
        tc, gp = _num(pt.get("total_credits")), _num(pt.get("gpa"))
        if tc is not None:
            cred_candidates.append(tc)
        if gp is not None:
            gpa_candidates.append(gp)
        st = p.get("student") or {}
        if st.get("name") and not student:
            student = st.get("name")
        tile_debug.append({"page": res["tile"]["page"], "band": res["tile"]["band"],
                           "records": len(recs), "error": out.get("error")})

    # A total-credits value must be a real total (>= 15); anything smaller is a GPA
    # a band mislabeled. GPA is the small value (<= 6). Take the most plausible.
    creds = [c for c in cred_candidates if c >= 15]
    gpas = [g for g in gpa_candidates if 0 < g <= 6]
    printed = {"total_credits": max(creds) if creds else None,
               "gpa": min(gpas) if gpas else None}

    merged = _merge_records(all_records)
    parsed_merged = {"courses": merged, "issuer": {"school_name": issuer, "printed_totals": printed}}
    verification = verify(parsed_merged, anchor)

    return {
        "page_count": anchor["page_count"],
        "pages": [{"page": p["page"]} for p in anchor["pages"]],
        "has_text_layer": anchor["has_text_layer"],
        "anchor_token_count": len(anchor["tokens"]),
        "model": vlm.model_name(),
        "latency_ms": total_latency,
        "vlm_error": errors[0] if errors else None,
        "issuer": {"school_name": issuer, "printed_totals": printed},
        "student": {"name": student},
        "expected_row_count": len(merged),
        "tiles": tile_debug,
        "courses": verification["courses"],
        "verification": verification["summary"],
        "raw_vlm_text": json.dumps(
            [{"page": r["tile"]["page"], "band": r["tile"]["band"],
              "records": len(r["parsed"].get("courses") or []),
              "raw": (r["out"]["text"] or "")[:3000]} for r in results],
            indent=2),
    }
