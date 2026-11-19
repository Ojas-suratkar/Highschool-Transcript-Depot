"""Compile an uploaded admissions handbook (PDF) into a STRUCTURED, cited A-G
rule set using the project's existing Gemini client.

Built for documents of ANY size and layout (plain text, tables, lists, scanned
pages):
- The PDF is split into overlapping page windows; each window gets its own
  bounded Gemini call, so the response can never exceed the output limit no
  matter how long the document is.
- A window that fails (truncated/unparseable JSON, transient API error) is
  bisected and retried on its halves, so one bad stretch of pages can't sink
  the whole document; a window that still fails is reported, never silently
  skipped.
- Rules from overlapping windows are merged and deduped.
- The prompt explicitly covers tables (each requirement row -> rules),
  footnotes, and bullet lists; Gemini's native PDF understanding OCRs scanned
  pages.

Design guardrails (unchanged):
- Gemini only *translates the document into structured rules* here — it never
  decides a student's admission.
- Every rule is grounded in an exact source quote for human review.
- Rules that do not fit a supported type are flagged as "unsupported" rather
  than invented.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional

import fitz  # PyMuPDF — already a project dependency
from google.genai import types

from app.services.gemini_course_extractor import (
    _make_gemini_client,
    _resolve_gemini_model,
    _safe_json_loads,
)

# Rule types the deterministic engine can (or will) execute. Gemini maps the
# document onto these; anything else goes to "unsupported".
SUPPORTED_RULE_TYPES = [
    "subject_requirement",  # per-area required years / accepted disciplines / slots
    "grade_rule",           # min grade, pass/credit windows, D-disqualifies
    "validation_rule",      # 2nd-sem-validates-year, advanced-validates-N, level-threshold
    "substitution_rule",    # G-surplus fills A/D, college course = 1 year, etc.
    "discipline_map",       # discipline -> area / extra-science
    "gpa_rule",             # grade points, honors caps, grade-level windows, weighting
    "index_formula",        # CSULB / STEM index terms + weights + thresholds
    "final_audit",          # outcome logic + required inputs
]

# Only these types can ever be "A-G relevant" (they change WHICH courses count
# toward an A-G area or HOW MANY units count). GPA math, index formulas, and
# audit-outcome logic are configured on the Criteria page, not from the handbook
# rule list — they are auto-excluded deterministically (no LLM judgement).
AG_RELEVANT_TYPES = {
    "subject_requirement",
    "grade_rule",
    "validation_rule",
    "substitution_rule",
    "discipline_map",
}

# Pages per Gemini call. SMALL on purpose: a narrow window forces fine-grained
# extraction (every statement becomes its own rule instead of being consolidated
# into compound rules), which maximizes recall on rule-dense handbooks. Windows
# run in parallel, so smaller windows cost no extra wall-time.
WINDOW_PAGES = 4
WINDOW_OVERLAP = 1  # pages shared between consecutive windows (rules that span a page break)


def _extraction_prompt(window_start: int, window_end: int, total_pages: int) -> str:
    return (
        "You are compiling a university admissions handbook into a STRUCTURED, "
        "MACHINE-READABLE rule set. You must NOT decide any student's admission — only "
        "translate the document's rules into JSON.\n\n"
        f"This PDF excerpt covers pages {window_start + 1}-{window_end} of a "
        f"{total_pages}-page document. Extract every rule that appears in THIS excerpt.\n\n"
        'Return ONLY JSON of the form: {"rules": [...], "unsupported": [...]}.\n\n'
        "Each element of \"rules\":\n"
        "{\n"
        '  "id": "short-kebab-slug",\n'
        '  "type": one of ' + ", ".join(SUPPORTED_RULE_TYPES) + ",\n"
        '  "area": one of "a","b","c","d1","d2","d","e","f","g" or null,\n'
        '  "title": "one-line plain-English summary of the rule",\n'
        '  "params": { rule-specific parameters as precise values (numbers, area '
        'letters, discipline names, thresholds) },\n'
        '  "source_quote": "the exact sentence(s) or table cell text this rule is based on",\n'
        '  "source_page": integer page number WITHIN THIS EXCERPT (1-based) or null,\n'
        '  "confidence": number 0.0-1.0\n'
        "}\n\n"
        "Each element of \"unsupported\" (a real rule that does not fit a supported type):\n"
        '{ "title": "...", "source_quote": "...", "source_page": int|null, "reason": '
        '"why it does not map to a supported type" }\n\n'
        "STRICT RULES:\n"
        "- Ground EVERY rule in an exact source_quote copied from the document. Never "
        "invent a rule that is not written in the document.\n"
        "- TABLES: read every table carefully. Each row of a requirements table is one "
        "or more rules — e.g. a row 'C. Mathematics | 3 years required ... | AP exams "
        "in Calculus AB/BC, Statistics | GE Area 2 course' yields a subject_requirement "
        "for the high-school pathway PLUS substitution_rules for the exam and college "
        "pathways. Do the same for bullet lists and footnotes (footnotes often carry "
        "unit thresholds and exceptions).\n"
        "- Every subject-area requirement, grade rule, validation, substitution, GPA "
        "rule, index formula, and final-audit rule that maps to a supported type MUST "
        "go in \"rules\" — even partial ones. Use your best params with a lower "
        "confidence when the wording is incomplete.\n"
        "- \"unsupported\" is ONLY for a real rule whose TYPE is not in the supported "
        "list. Do NOT put subject requirements, grade rules, or validations there just "
        "because they are brief or you are unsure of exact params.\n"
        "- Ignore (do not emit) non-rule text such as titles, headers, page numbers, "
        "and marketing copy.\n"
        "- If a page is a scanned image, read the text from the image.\n\n"
        "EXAMPLE — document text:\n"
        '"A. History/Social Science: 2 years required. One year of U.S. History or one '
        'semester of U.S. History and one semester of American Government."\n'
        "->\n"
        '{"id":"a-history-2yr","type":"subject_requirement","area":"a","title":"History: '
        '2 years incl. a U.S. History year","params":{"required_years":2,'
        '"must_include":"US History (2 sems) OR US History + American Government"},'
        '"source_quote":"A. History/Social Science: 2 years required. One year of U.S. '
        'History or one semester of U.S. History and one semester of American '
        'Government.","source_page":1,"confidence":0.95}\n'
    )


def document_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


_TRIAGE_PROMPT = (
    "This is a university admissions handbook. Find the pages whose PRIMARY "
    "content is FIRST-TIME-FRESHMAN A-G subject completion rules: the A-G "
    "subject requirements list/table (areas A-G: history, English, math, "
    "science, language, arts, elective — required years, qualifying grades, "
    "AP/IB or college-course substitution options), and any page detailing "
    "course validation rules for those areas. Include every continuation page "
    "of such a table.\n"
    "Do NOT include: transfer-student requirements, GE/breadth requirements, "
    "applications/deadlines/fees, immunization/health, residency, financial "
    "aid, EOP, impaction, appeals, campus life, or pages that merely MENTION "
    "A-G in passing.\n"
    "A typical handbook has 2-8 such pages.\n"
    'Return ONLY JSON: {"pages": [1-based page numbers, ranked most relevant '
    "first]}."
)

# Hard cap on pages sent to deep extraction — keeps the run fast even if the
# triage over-selects.
TRIAGE_MAX_PAGES = 12


def triage_ag_pages(pdf_bytes: bytes, total_pages: int) -> list[int]:
    """One fast pass over the whole PDF to find the A-G pages (0-based, ranked,
    capped). Fail-open: on any failure, return all pages so nothing is missed."""
    try:
        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        data = _call_gemini(pdf_part, _TRIAGE_PROMPT)
        raw = data.get("pages") if isinstance(data, dict) else None
        ranked: list[int] = []
        for p in raw or []:
            try:
                idx = int(p) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < total_pages and idx not in ranked:
                ranked.append(idx)
        if not ranked:
            return list(range(total_pages))
        return sorted(ranked[:TRIAGE_MAX_PAGES])
    except Exception:  # noqa: BLE001 — fail-open: scan everything
        return list(range(total_pages))


def extract_pages(pdf_bytes: bytes, pages: list[int]) -> bytes:
    """Sub-PDF containing exactly the given 0-based pages, in order."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as src:
        out = fitz.open()
        for p in pages:
            out.insert_pdf(src, from_page=p, to_page=p)
        data = out.tobytes()
        out.close()
        return data


def count_pages(pdf_bytes: bytes) -> int:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


def _slice_pdf(pdf_bytes: bytes, start: int, end: int) -> bytes:
    """Sub-PDF containing pages [start, end) (0-based)."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as src:
        out = fitz.open()
        out.insert_pdf(src, from_page=start, to_page=end - 1)
        data = out.tobytes()
        out.close()
        return data


def plan_windows(total_pages: int) -> list[tuple[int, int]]:
    """Overlapping [start, end) page windows covering the whole document."""
    if total_pages <= WINDOW_PAGES:
        return [(0, total_pages)]
    windows: list[tuple[int, int]] = []
    start = 0
    while start < total_pages:
        end = min(start + WINDOW_PAGES, total_pages)
        windows.append((start, end))
        if end >= total_pages:
            break
        start = end - WINDOW_OVERLAP
    return windows


def _normalize_rule(raw: dict, idx: int, page_offset: int = 0) -> dict[str, Any]:
    rid = str(raw.get("id") or f"rule-{idx+1}").strip()[:80]
    rtype = str(raw.get("type") or "").strip().lower()
    if rtype not in SUPPORTED_RULE_TYPES:
        rtype = "other"
    area = raw.get("area")
    area = str(area).strip().lower() if area else None
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.5
    # Gemini reports pages relative to the excerpt; convert to absolute.
    page = raw.get("source_page")
    try:
        page = int(page) + page_offset if page is not None else None
    except (TypeError, ValueError):
        page = None
    return {
        "id": rid,
        "type": rtype,
        "area": area,
        "title": str(raw.get("title") or "").strip(),
        "params": raw.get("params") if isinstance(raw.get("params"), dict) else {},
        "source_quote": str(raw.get("source_quote") or "").strip(),
        "source_page": page,
        "confidence": max(0.0, min(1.0, confidence)),
        "approved": False,
    }


def _call_gemini(pdf_part: types.Part, prompt: str) -> dict:
    client = _make_gemini_client()
    from app.services.gemini_rate_limit import generate_content_limited

    response = generate_content_limited(
        client,
        model=_resolve_gemini_model(),
        contents=[pdf_part, prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            max_output_tokens=32768,
        ),
    )
    return _safe_json_loads(response.text or "") or {}


def extract_rules_from_window(
    pdf_bytes: bytes,
    start: int,
    end: int,
    total_pages: int,
    _depth: int = 0,
) -> dict[str, Any]:
    """Extract rules from pages [start, end). On failure, bisect and retry each
    half (up to 3 levels); a stretch that still fails is reported in
    "unsupported" so nothing disappears silently."""
    try:
        window_bytes = _slice_pdf(pdf_bytes, start, end)
        pdf_part = types.Part.from_bytes(data=window_bytes, mime_type="application/pdf")
        data = _call_gemini(pdf_part, _extraction_prompt(start, end, total_pages))
        raw_rules = data.get("rules") if isinstance(data, dict) else None
        raw_unsupported = data.get("unsupported") if isinstance(data, dict) else None
        rules = [
            _normalize_rule(r, i, page_offset=start)
            for i, r in enumerate(raw_rules or [])
            if isinstance(r, dict)
        ]
        unsupported = [u for u in (raw_unsupported or []) if isinstance(u, dict)]
        return {"rules": rules, "unsupported": unsupported}
    except Exception as exc:  # noqa: BLE001 — bisect and retry
        if end - start > 1 and _depth < 3:
            mid = (start + end) // 2
            left = extract_rules_from_window(pdf_bytes, start, mid, total_pages, _depth + 1)
            right = extract_rules_from_window(pdf_bytes, mid, end, total_pages, _depth + 1)
            return {
                "rules": left["rules"] + right["rules"],
                "unsupported": left["unsupported"] + right["unsupported"],
            }
        return {
            "rules": [],
            "unsupported": [{
                "title": f"Pages {start + 1}-{end} could not be processed",
                "reason": f"Extraction failed after retries: {str(exc)[:200]}",
                "source_quote": "",
                "source_page": start + 1,
            }],
        }


def _rule_dedupe_key(rule: dict) -> str:
    quote = (rule.get("source_quote") or "").lower().strip()
    if len(quote) >= 25:
        return f"q:{quote[:120]}"
    return f"t:{rule.get('type')}|{rule.get('area')}|{(rule.get('title') or '').lower().strip()[:80]}"


def merge_extractions(parts: list[dict]) -> dict[str, Any]:
    """Merge windows: dedupe rules (overlap pages produce duplicates), keeping the
    highest-confidence copy; dedupe unsupported by title."""
    best: dict[str, dict] = {}
    order: list[str] = []
    for part in parts:
        for rule in part.get("rules", []):
            key = _rule_dedupe_key(rule)
            if key not in best:
                best[key] = rule
                order.append(key)
            elif rule.get("confidence", 0) > best[key].get("confidence", 0):
                best[key] = rule
    seen_u: set[str] = set()
    unsupported: list[dict] = []
    for part in parts:
        for u in part.get("unsupported", []):
            k = (u.get("title") or "").lower().strip()
            if k and k in seen_u:
                continue
            seen_u.add(k)
            unsupported.append(u)
    # Re-slug ids to be unique after the merge.
    rules = []
    used_ids: set[str] = set()
    for key in order:
        rule = best[key]
        rid = rule["id"]
        n = 2
        while rid in used_ids:
            rid = f"{rule['id']}-{n}"
            n += 1
        used_ids.add(rid)
        rule["id"] = rid
        rules.append(rule)
    return {"rules": rules, "unsupported": unsupported}


_RELEVANCE_PROMPT = (
    "You are auditing a list of rules extracted from a university admissions "
    "handbook. For EACH rule decide: is it directly relevant to CSU A-G subject "
    "completion — i.e. does it change WHICH courses count toward an A-G area "
    "(a, b, c, d1, d2, d, e, f, g) or HOW MANY units/years/semesters are counted "
    "as complete?\n\n"
    "RELEVANT examples: required years per area; what a year must include (e.g. "
    "U.S. History); minimum grade for a course to count (C-, D disqualifies, "
    "pass/credit windows); validations (a later course/semester validating earlier "
    "ones, LOTE level thresholds); substitutions and makeup options (AP/IB exams, "
    "college courses, ESL, area-to-area moves); which disciplines belong to which "
    "area.\n\n"
    "NOT RELEVANT examples: GPA point values or honors weighting; eligibility "
    "index formulas or thresholds; application deadlines, fees, residency, "
    "impaction, campus policies; anything that does not change A-G course "
    "counting.\n\n"
    "Input: a JSON list of rules, each with \"id\", \"type\", \"area\", \"title\", "
    "\"source_quote\".\n"
    'Return ONLY JSON: {"verdicts": [{"id": "...", "relevant": true/false, '
    '"reason": "one short sentence"}]} — exactly one verdict per input rule, '
    "same ids.\n"
    "If genuinely unsure, mark relevant=true (a human reviews this list; missing "
    "a real A-G rule is worse than including a borderline one)."
)


def classify_relevance(rules: list[dict]) -> list[dict]:
    """Mark each rule with relevant=True/False + relevance_reason.

    Two layers:
    1. Deterministic type gate — types outside AG_RELEVANT_TYPES are excluded in
       code (no LLM involved, cannot misfire).
    2. Batched Gemini check (temp 0) for the eligible ones.

    FAIL-OPEN: if the Gemini check fails or misses a rule, that rule stays
    relevant=True. A rule can therefore never be hidden by a classifier error —
    the UI keeps excluded rules visible for one-click rescue anyway."""
    eligible: list[dict] = []
    for rule in rules:
        if rule.get("type") in AG_RELEVANT_TYPES:
            rule["relevant"] = True  # fail-open default; LLM may flip to False
            rule["relevance_reason"] = ""
            eligible.append(rule)
        else:
            rule["relevant"] = False
            rule["relevance_reason"] = (
                "Rule type is not about A-G unit counting (configured on the "
                "Criteria page instead)."
            )

    if not eligible:
        return rules

    import json as _json

    # Judge in bounded batches so a big handbook (hundreds of eligible rules)
    # can never truncate the verdict JSON. Batches run in PARALLEL threads —
    # total time is ~one batch's latency. Each batch fails open independently.
    BATCH = 100
    from concurrent.futures import ThreadPoolExecutor

    def _judge(batch: list[dict]) -> None:
        payload = [
            {
                "id": r["id"],
                "type": r["type"],
                "area": r.get("area"),
                "title": r.get("title"),
                "source_quote": (r.get("source_quote") or "")[:300],
            }
            for r in batch
        ]
        try:
            client = _make_gemini_client()
            from app.services.gemini_rate_limit import generate_content_limited

            response = generate_content_limited(
                client,
                model=_resolve_gemini_model(),
                contents=[_RELEVANCE_PROMPT, _json.dumps(payload)],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    max_output_tokens=16384,
                ),
            )
            data = _safe_json_loads(response.text or "") or {}
            verdicts = {
                str(v.get("id")): v
                for v in (data.get("verdicts") or [])
                if isinstance(v, dict)
            }
            for rule in batch:
                v = verdicts.get(rule["id"])
                if v is None:
                    continue  # fail-open: unjudged rules stay relevant
                rule["relevant"] = bool(v.get("relevant", True))
                rule["relevance_reason"] = str(v.get("reason") or "").strip()
        except Exception:  # noqa: BLE001 — fail-open: never hide rules on error
            return

    batches = [eligible[i:i + BATCH] for i in range(0, len(eligible), BATCH)]
    with ThreadPoolExecutor(max_workers=min(6, len(batches))) as pool:
        list(pool.map(_judge, batches))

    return rules


def bind_rules_to_engine(rules: list[dict]) -> list[dict]:
    """The rule compiler: match each A-G-relevant rule to a deterministic-engine
    capability. A matched rule carries engine_binding = {id, label, patch}; on
    approval the patch auto-configures the term's criteria/strict toggles, so the
    rule is enforced in code (identical every run, no LLM at decision time).
    Unmatched rules stay LLM-audit-layer (binding None, visibly labeled)."""
    for r in rules:
        if r.get("relevant") is False:
            r["engine_binding"] = None
            continue
        text = f"{r.get('title','')} {r.get('source_quote','')} {str(r.get('params',{}))}".lower()
        area = (r.get("area") or "").lower()
        rtype = r.get("type")
        binding = None

        if area == "a" and ("u.s. history" in text or "us history" in text):
            binding = {
                "id": "strict_a_history_anchor",
                "label": "Engine: U.S. History anchor (Area A)",
                "patch": {"rule_config": {"strict_a_history_anchor": True}},
            }
        elif area == "c" and "algebra" in text and "geometr" in text:
            binding = {
                "id": "strict_c_math_slots",
                "label": "Engine: Math slots (Algebra I / Geometry / Algebra II+)",
                "patch": {"rule_config": {"strict_c_math_slots": True}},
            }
        elif area == "f" and ("same discipline" in text or "single discipline" in text or "one discipline" in text):
            binding = {
                "id": "strict_f_same_discipline",
                "label": "Engine: VPA year must be one discipline",
                "patch": {"rule_config": {"strict_f_same_discipline": True}},
            }
        elif area == "e" and rtype == "validation_rule" and ("level 2" in text or "level two" in text):
            binding = {
                "id": "lote_level2",
                "label": "Engine: LOTE level-2 validates (always enforced)",
                "patch": {},
            }
        elif rtype == "validation_rule" and ("chem" in text) and ("second semester" in text or "2nd semester" in text or "full year" in text):
            binding = {
                "id": "chem_year_sequence",
                "label": "Engine: Chemistry 2nd-semester validates the year (always enforced)",
                "patch": {},
            }
        elif rtype == "grade_rule" and ("c-" in text or " d " in text or "grade of d" in text):
            binding = {
                "id": "grade_floor",
                "label": "Engine: C- counts as C; D/F never qualify (always enforced)",
                "patch": {},
            }
        elif rtype == "subject_requirement" and area in ("a", "b", "c", "d", "d1", "d2", "e", "f", "g"):
            years = (r.get("params") or {}).get("required_years")
            try:
                sems = int(float(years)) * 2 if years is not None else None
            except (TypeError, ValueError):
                sems = None
            if sems and 0 < sems <= 12:
                binding = {
                    "id": f"required_semesters_{area}",
                    "label": f"Engine: Area {area.upper()} requires {sems} semesters",
                    "patch": {"ag_required": {area: sems}},
                }

        r["engine_binding"] = binding
    return rules


def extract_rules_from_pdf(
    pdf_bytes: bytes,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> dict[str, Any]:
    """Full-document extraction: window over all pages, merge, dedupe, then
    classify A-G relevance. progress_cb(pages_done, pages_total) per window."""
    total = count_pages(pdf_bytes)
    windows = plan_windows(total)
    parts: list[dict] = []
    for (start, end) in windows:
        parts.append(extract_rules_from_window(pdf_bytes, start, end, total))
        if progress_cb:
            try:
                progress_cb(end, total)
            except Exception:  # noqa: BLE001 — progress must never kill extraction
                pass
    merged = merge_extractions(parts)
    merged["rules"] = classify_relevance(merged["rules"])
    return merged
