"""Gemini per-student A-G evaluation, grounded in the deterministic calculation.

The deterministic engine runs FIRST and produces the objective facts (per-area
A-G counts + deficits, GPA, indices, a baseline decision). Gemini then applies the
term's approved rules on top to CONFIRM or ADJUST the decision, and must cite the
specific rule(s) and course(s) behind every conclusion. Verdicts are cached by the
caller keyed on the ruleset version, so this only runs when a student is new or the
ruleset changes.
"""
from __future__ import annotations

import json
from typing import Any

from google.genai import types

from app.services.gemini_course_extractor import (
    _make_gemini_client,
    _resolve_gemini_model,
    _safe_json_loads,
)

_VALID_DECISIONS = {"admitted", "denied", "waitlisted"}


def _compact_courses(courses: list[dict]) -> list[dict]:
    from app.services import admission_calculation_service as A

    out = []
    for i, c in enumerate(courses or []):
        out.append({
            "name": A.get_course_name(c),
            "discipline": A.get_uc_discipline(c) or None,
            "area": A.get_original_ag_letter(c) or None,
            "grade": A.get_course_grade(c),
            "year": c.get("year"),
        })
    return out


def _compact_review(review: dict) -> dict:
    ag = review.get("ag_review") or {}
    rows = [
        {
            "area": r.get("key"),
            "required": r.get("required"),
            "actual": r.get("actual"),
            "deficit": r.get("def"),
            "strict_note": r.get("strict_note"),
        }
        for r in (ag.get("rows") or [])
    ]
    score = (review.get("gpa_calculation") or {}).get("score_summary") or {}
    dec = review.get("admission_decision") or {}
    return {
        "ag_rows": rows,
        "ag_totals": ag.get("totals"),
        "gpa": {
            "cumulative": score.get("cumulative_gpa"),
            "english": score.get("english_gpa"),
            "math": score.get("math_gpa"),
            "science": score.get("science_gpa"),
            "csulb_index": score.get("csulb_score"),
            "stem_index": score.get("stem_index"),
        },
        "baseline_decision": dec.get("recommended_decision"),
    }


_EVAL_PROMPT = (
    "You are auditing one student's CSU A-G admission eligibility. You are given "
    "JSON with three parts:\n"
    "1. deterministic_facts — per-area A-G required/actual/deficit counts, GPA, "
    "admission indices, and a baseline_decision already computed by a trusted "
    "engine. Treat these numbers as ground truth; do NOT recompute arithmetic.\n"
    "2. courses — the student's courses (name, UC Doorways discipline, A-G area, grade).\n"
    "3. rules — the institution's approved rules for this term.\n\n"
    "Your job: apply the rules to CONFIRM or ADJUST the baseline_decision. Only "
    "change the decision if a specific rule requires it, and cite that rule.\n\n"
    'Return ONLY JSON:\n'
    "{\n"
    '  "decision": one of "admitted","denied","waitlisted",\n'
    '  "reason": "a short plain-English justification",\n'
    '  "per_area": [ { "area": "a".."g", "satisfied": true/false, '
    '"reason": "...", "cited_rule_ids": ["..."], "cited_courses": ["course name", ...] } ],\n'
    '  "learned_rules": [ { "title": "...", "why_applied": "...", '
    '"source": "which rule text or handbook concept" } ]\n'
    "}\n\n"
    "STYLE (mandatory, for a professional UI):\n"
    "- \"reason\": ONE factual sentence, max 15 words. Never start with the "
    "decision word. No filler ('based on the provided facts', 'upon review').\n"
    "- per_area \"reason\": max 8 words, uniform format — e.g. 'required 8 sem, "
    "has 7' or 'college Chinese covers 2-year requirement'. Never repeat "
    "'satisfied'/'deficient' (the checkmark shows it).\n\n"
    "STRICT:\n"
    "- PRECONDITION RULES: if any approved rule imposes a universal requirement "
    "for admission (a credential, degree, status, or attribute), and the provided "
    "data does not POSITIVELY demonstrate the student meets it, the decision MUST "
    "be 'denied' citing that rule. Absence of evidence = requirement NOT met. "
    "Never dismiss an approved rule as 'not applicable' because the data lacks "
    "that attribute — that is exactly when it applies.\n"
    "- Use ONLY the provided facts and courses; never invent a course, grade, or number.\n"
    "- Cite the rule id(s) and course name(s) behind every area conclusion.\n"
    "- If applying a rule that is NOT in the provided rules list, still apply it but "
    "record it under learned_rules so a human can review and add it.\n"
    "- If the rules don't require any change, return the baseline_decision unchanged.\n"
)


def evaluate_student(review: dict, courses: list[dict], rules: list[dict]) -> dict[str, Any]:
    """Run the grounded Gemini audit. Returns a normalized verdict dict. On any
    failure, falls back to the deterministic baseline so a student is never blocked."""
    compact = _compact_review(review)
    baseline = compact.get("baseline_decision")

    payload = {
        "deterministic_facts": compact,
        "courses": _compact_courses(courses),
        "rules": rules or [],
    }

    data: dict = {}
    failed = True
    for attempt in range(3):  # ride out transient 429/5xx bursts under high concurrency
        try:
            client = _make_gemini_client()
            from app.services.gemini_rate_limit import generate_content_limited

            response = generate_content_limited(
                client,
                model=_resolve_gemini_model(),
                contents=[_EVAL_PROMPT, json.dumps(payload, default=str)],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    # Roomy ceiling: a truncated response fails JSON parsing
                    # DETERMINISTICALLY (temp 0), which no amount of retrying
                    # fixes — that, not rate limits, strands students unaudited.
                    max_output_tokens=16384,
                ),
            )
            data = _safe_json_loads(response.text or "") or {}
            failed = False
            break
        except Exception:
            import time as _t
            _t.sleep(1.5 * (attempt + 1))

    decision = str(data.get("decision") or "").strip().lower()
    if decision not in _VALID_DECISIONS:
        decision = baseline  # fall back to the deterministic baseline

    return {
        "decision": decision,
        "baseline_decision": baseline,
        "reason": str(data.get("reason") or "").strip(),
        "per_area": data.get("per_area") if isinstance(data.get("per_area"), list) else [],
        "learned_rules": data.get("learned_rules") if isinstance(data.get("learned_rules"), list) else [],
        # Callers must NOT cache a failed audit as a verdict — leaving it absent
        # makes the next recalc retry automatically.
        "failed": failed,
    }
