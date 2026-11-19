"""
Transcript row geometry helper.

Purpose:
- Read transcript PDF text positions using PyMuPDF.
- Build a canonical visual row sequence for Mayfair/LBUSD-style 3-column transcripts.
- Detect course_id, course_name, grade, credits, grade/year/month, page, column, row bbox.
- Preserve continued-column term context:
    If a term section continues at the top of the next visual column, those leading
    rows inherit the previous column's active section.
- Prevent next-header leakage:
    A course row may only inherit a header that appears ABOVE it in the same
    visual column, or the previous-column continuation context. A row never
    inherits a header that appears below it.

This file is standalone. It does not change Document AI, Gemini, reconciliation,
or DB rows by itself.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Regex / constants
# ---------------------------------------------------------------------------

VALID_GRADE_RE = re.compile(
    r"^(A\+|A-|A|B\+|B-|B|C\+|C-|C|D\+|D-|D|F|P|NP|CR|NC|I|W|DR)$",
    re.I,
)

CREDIT_RE = re.compile(r"^\d+(?:[\.,]\d+)?$")
CREDIT_PAIR_RE = re.compile(r"^\d+(?:[\.,]\d+)?\s*/\s*\d+(?:[\.,]\d+)?$")
COURSE_NUMBER_RE = re.compile(r"^\d{3,5}[A-Z]?$", re.I)
CC_COURSE_ID_RE = re.compile(r"^CC\d{3,5}$", re.I)

# Non-overlapping transcript columns.
# The old overlap could let right-column headers leak into the middle column
# and corrupt the continuation context.
COLUMN_DEFS = [
    ("left", 0.035, 0.355),
    ("middle", 0.355, 0.655),
    ("right", 0.655, 0.975),
]

COLUMN_INDEX = {
    "left": 1,
    "middle": 2,
    "right": 3,
}

COLUMN_NAMES = ["left", "middle", "right"]

SKIP_LINE_PATTERNS = [
    r"\bCRS[- ]?ID\b",
    r"\bCOURSE\s+TITLE\b",
    r"\bMARK\b.*\bATT\b",
    r"\bCREDIT\s+ATT\b",
    r"\bCREDIT\s+SUMMARY\b",
    r"\bGPA\b",
    r"\bTGPA\b",
    r"\bCOURSE\s+TAGS\b",
    r"\bNON\s+ACADEMIC\b",
    r"\bCOLLEGE\s+PREP\b",
    r"\bHONORS\b",
    r"\bPARENT/GUARDIAN\b",
    r"\bCOMMENTS\b",
    r"\bCONTINUED\s+ON\s+NEXT\b",
    r"\bWEIGHTED\b",
    r"\bUN-?WGTD\b",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class TermContext:
    section_name: str
    grade_level: int | None
    year: int | None
    month: int | None
    term_name: str | None
    school_name: str | None = None
    source: str = "term_header"
    block_index: int | None = None
    page_number: int | None = None
    visual_column: str | None = None
    column_index: int | None = None
    header_y: float | None = None
    raw_header_text: str | None = None


@dataclass(frozen=True)
class ParsedCourseLine:
    course_id: str
    course_name: str
    grade: str
    credit_attempted: float | None
    credit_completed: float | None
    line_text: str
    course_id_token_span: tuple[int, int]
    course_name_token_span: tuple[int, int]
    grade_token_span: tuple[int, int]
    credit_token_span: tuple[int, int]


@dataclass(frozen=True)
class ColumnEntry:
    kind: str
    words: list[Word]
    text: str
    y0: float
    y1: float
    y_mid: float
    term_context: TermContext | None = None
    parsed_course: ParsedCourseLine | None = None
    school_name: str | None = None


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------

def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_upper(value: Any) -> str:
    return _normalize_space(value).upper()


def _coerce_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        text = str(value).strip()
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
        return float(text)
    except Exception:
        match = re.search(r"-?\d+(?:[\.,]\d+)?", str(value))
        if not match:
            return None
        return float(match.group(0).replace(",", "."))


def _normalize_grade(value: Any) -> str:
    grade = re.sub(r"\s+", "", str(value or "").strip().upper())

    # DR is not a real transcript grade in this workflow.
    # Treat OCR/Gemini "DR" as D, not CR.
    if grade == "DR":
        return "D"

    return grade


def _is_grade_token(value: Any) -> bool:
    return bool(VALID_GRADE_RE.fullmatch(str(value or "").strip()))


def _is_credit_token(value: Any) -> bool:
    token = str(value or "").strip()
    return bool(CREDIT_RE.fullmatch(token) or CREDIT_PAIR_RE.fullmatch(token))


def _parse_credit_pair(value: Any) -> tuple[float | None, float | None]:
    text = str(value or "").strip()

    if "/" not in text:
        credit = _coerce_float(text)
        return credit, None

    left, right = text.split("/", 1)
    return _coerce_float(left), _coerce_float(right)


def _academic_start_year_from_text(text: str) -> int | None:
    """
    2021-2022 -> 2021
    2022-2023 -> 2022
    21-22     -> 2021
    """
    text = str(text or "")

    full_match = re.search(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b", text)
    if full_match:
        return int(full_match.group(1))

    short_match = re.search(r"\b(\d{2})\s*[-/]\s*(\d{2})\b", text)
    if short_match:
        start = int(short_match.group(1))
        if 0 <= start <= 50:
            return 2000 + start
        return 1900 + start

    single_match = re.search(r"\b(20\d{2})\b", text)
    if single_match:
        return int(single_match.group(1))

    return None


def _month_from_term_text(text: str) -> int | None:
    upper = _normalize_upper(text)

    if re.search(r"\b(SUMMER\s+INTERSESSION|SUMMER\s+SCHOOL|INTERSESSION|SUMMER|SUMR)\b", upper):
        return 7

    if re.search(r"\bSPRING\b", upper):
        return 6

    if re.search(r"\bFALL\b", upper):
        return 1

    month_match = re.search(r"\bMONTH\s*:?\s*(\d{1,2})\b", upper)
    if month_match:
        month = int(month_match.group(1))
        return month if 1 <= month <= 12 else None

    return None


def _looks_like_skip_line(text: str) -> bool:
    upper = _normalize_upper(text)

    if not upper:
        return True

    return any(re.search(pattern, upper) for pattern in SKIP_LINE_PATTERNS)


def _context_key(context: TermContext | None) -> str:
    if context is None:
        return "missing"

    return (
        f"{context.block_index}:"
        f"{context.grade_level}:"
        f"{context.year}:"
        f"{context.month}:"
        f"{context.visual_column}"
    )


# ---------------------------------------------------------------------------
# Bounding-box helpers
# ---------------------------------------------------------------------------

def _words_to_bbox(
    words: list[Word],
    *,
    page_width: float,
    page_height: float,
) -> list[float]:
    if not words:
        return [0.0, 0.0, 0.0, 0.0]

    return [
        max(0.0, min(1.0, min(w.x0 for w in words) / page_width)),
        max(0.0, min(1.0, min(w.y0 for w in words) / page_height)),
        max(0.0, min(1.0, max(w.x1 for w in words) / page_width)),
        max(0.0, min(1.0, max(w.y1 for w in words) / page_height)),
    ]


def _bbox_for_token_span(
    words: list[Word],
    token_span: tuple[int, int],
    *,
    page_width: float,
    page_height: float,
) -> list[float] | None:
    start, end = token_span
    selected = words[start:end]

    if not selected:
        return None

    return _words_to_bbox(selected, page_width=page_width, page_height=page_height)


def _expanded_row_bbox(
    *,
    column_name: str,
    raw_bbox: list[float],
) -> list[float]:
    _x0, y0, _x1, y1 = raw_bbox

    column_lookup = {
        name: (x0, x1)
        for name, x0, x1 in COLUMN_DEFS
    }

    col_x0, col_x1 = column_lookup.get(column_name, (0.035, 0.975))
    vertical_pad = 0.0035

    return [
        max(0.0, col_x0),
        max(0.0, y0 - vertical_pad),
        min(1.0, col_x1),
        min(1.0, y1 + vertical_pad),
    ]


# ---------------------------------------------------------------------------
# PDF word grouping
# ---------------------------------------------------------------------------

def _group_words_into_lines(words: list[Word], y_tol: float = 2.5) -> list[list[Word]]:
    sorted_words = sorted(words, key=lambda w: (w.y0, w.x0))
    lines: list[list[Word]] = []

    for word in sorted_words:
        matched_line: list[Word] | None = None

        for line in lines:
            avg_y = sum(w.y0 for w in line) / len(line)
            if abs(avg_y - word.y0) <= y_tol:
                matched_line = line
                break

        if matched_line is None:
            lines.append([word])
        else:
            matched_line.append(word)

    for line in lines:
        line.sort(key=lambda w: w.x0)

    lines.sort(key=lambda line: sum(w.y0 for w in line) / len(line))
    return lines


def _column_for_word(word: Word, page_width: float) -> str | None:
    mid_x = ((word.x0 + word.x1) / 2.0) / page_width

    for column_name, x0, x1 in COLUMN_DEFS:
        if x0 <= mid_x < x1:
            return column_name

    if COLUMN_DEFS[-1][1] <= mid_x <= COLUMN_DEFS[-1][2]:
        return COLUMN_DEFS[-1][0]

    return None


def _split_line_by_columns(line: list[Word], page_width: float) -> dict[str, list[Word]]:
    split: dict[str, list[Word]] = {
        "left": [],
        "middle": [],
        "right": [],
    }

    for word in line:
        column_name = _column_for_word(word, page_width)
        if column_name:
            split[column_name].append(word)

    for column_words in split.values():
        column_words.sort(key=lambda w: w.x0)

    return split


def _line_text(words: list[Word]) -> str:
    return _normalize_space(" ".join(w.text for w in words))


# ---------------------------------------------------------------------------
# Term / section parsing
# ---------------------------------------------------------------------------

def _parse_mayfair_term_header(text: str) -> TermContext | None:
    """
    Examples:
      Grade 9 Fall 2021-2022
      Grade 10 Spring 2022-2023
      Grade 10 Summer Intersession 2023-2024
      Grade 11 Summer 2023-2024
    """
    clean = _normalize_space(text)
    upper = clean.upper()

    if "GRADE" not in upper:
        return None

    grade_match = re.search(r"\bGRADE\s+(\d{1,2})\b", upper)
    if not grade_match:
        return None

    term_match = re.search(
        r"\b(FALL|SPRING|SUMMER\s+INTERSESSION|SUMMER\s+SCHOOL|INTERSESSION|SUMMER|SUMR)\b",
        upper,
    )
    if not term_match:
        return None

    year = _academic_start_year_from_text(clean)
    month = _month_from_term_text(clean)
    grade_level = int(grade_match.group(1))

    if year is None or month is None:
        return None

    term_name = term_match.group(1).replace("SUMR", "SUMMER").title()

    return TermContext(
        section_name=f"Grade {grade_level} {term_name} {year}-{year + 1}",
        grade_level=grade_level,
        year=year,
        month=month,
        term_name=term_name,
        source="mayfair_term_header",
        raw_header_text=clean,
    )


def _parse_lbusd_term_header(text: str) -> TermContext | None:
    """
    Examples:
      Yr: 2021 Month: 6 Grade: 10
      Yr 2021 Month 6 Grade 10
    """
    clean = _normalize_space(text)
    upper = clean.upper()

    if "YR" not in upper and "MONTH" not in upper and "GRADE" not in upper:
        return None

    year_match = re.search(r"\bYR\s*:?\s*(20\d{2})\b", upper)
    month_match = re.search(r"\bMONTH\s*:?\s*(\d{1,2})\b", upper)
    grade_match = re.search(r"\bGRADE\s*:?\s*(\d{1,2})\b", upper)

    if not (year_match and month_match and grade_match):
        return None

    year = int(year_match.group(1))
    month = int(month_match.group(1))
    grade_level = int(grade_match.group(1))

    if not (1 <= month <= 12):
        return None

    return TermContext(
        section_name=f"Yr: {year} Month: {month} Grade: {grade_level}",
        grade_level=grade_level,
        year=year,
        month=month,
        term_name=f"Month {month}",
        source="lbusd_term_header",
        raw_header_text=clean,
    )


def _parse_term_header(text: str) -> TermContext | None:
    return _parse_mayfair_term_header(text) or _parse_lbusd_term_header(text)


def _maybe_school_name(text: str) -> str | None:
    clean = _normalize_space(text)

    if not clean:
        return None

    upper = clean.upper()

    school_indicators = [
        "MAYFAIR HIGH SCHOOL",
        "MILLIKAN HIGH SCHOOL",
        "LAKEWOOD HIGH SCHOOL",
        "WOODROW WILSON HIGH SCHOOL",
        "WILSON HIGH SCHOOL",
        "MCBRIDE HIGH SCHOOL",
        "SATO ACADEMY",
        "CABRILLO HIGH SCHOOL",
        "JORDAN HIGH SCHOOL",
        "LONG BEACH CITY COLLEGE",
        "CERRITOS COMMUNITY COLLEGE",
        "LAS FLORES EDUCATION ACADEMY",
        "HOOVER MIDDLE SCHOOL",
        "NEWCOMB MIDDLE SCHOOL",
    ]

    if any(indicator in upper for indicator in school_indicators):
        return clean

    return None


# ---------------------------------------------------------------------------
# Course row parsing
# ---------------------------------------------------------------------------

def _looks_like_course_id_tokens(tokens: list[str]) -> tuple[str | None, int]:
    """
    Return (course_id, token_count_used).

    Supports:
      2986
      P 2986
      N 3635
      HP 1449
      H P 2318   -> HP 2318
      + p 3261
      * 8110
      CC006
      + CC001
      9205 p     -> p 9205 (PyMuPDF sometimes reverses tiny Mayfair tag text)
    """
    clean_tokens = [str(t or "").strip() for t in tokens if str(t or "").strip()]

    if not clean_tokens:
        return None, 0

    if clean_tokens[0] in {"+", "*"}:
        marker = clean_tokens[0]

        if len(clean_tokens) >= 2 and CC_COURSE_ID_RE.fullmatch(clean_tokens[1]):
            return f"{marker} {clean_tokens[1]}", 2

        if len(clean_tokens) >= 2 and COURSE_NUMBER_RE.fullmatch(clean_tokens[1]):
            return f"{marker} {clean_tokens[1]}", 2

        if len(clean_tokens) >= 3:
            prefix = clean_tokens[1].upper()
            number = clean_tokens[2]

            if re.fullmatch(r"[A-Z]{1,3}", prefix) and COURSE_NUMBER_RE.fullmatch(number):
                original_prefix = clean_tokens[1]
                return f"{marker} {original_prefix} {number}", 3

    if CC_COURSE_ID_RE.fullmatch(clean_tokens[0]):
        return clean_tokens[0], 1

    # PyMuPDF sometimes emits Mayfair "p 9205" as "9205 p".
    if len(clean_tokens) >= 2:
        first = clean_tokens[0]
        second = clean_tokens[1]
        if COURSE_NUMBER_RE.fullmatch(first) and re.fullmatch(r"[pPhHnN]", second):
            prefix = second.lower() if second.lower() == "p" else second.upper()
            return f"{prefix} {first}", 2

    if COURSE_NUMBER_RE.fullmatch(clean_tokens[0]):
        return clean_tokens[0], 1

    if len(clean_tokens) >= 3:
        if (
            clean_tokens[0].upper() == "H"
            and clean_tokens[1].upper() == "P"
            and COURSE_NUMBER_RE.fullmatch(clean_tokens[2])
        ):
            return f"HP {clean_tokens[2]}", 3

    if len(clean_tokens) >= 2:
        prefix = clean_tokens[0].upper()
        number = clean_tokens[1]

        if re.fullmatch(r"[A-Z]{1,3}", prefix) and COURSE_NUMBER_RE.fullmatch(number):
            if prefix == "P":
                return f"p {number}", 2
            return f"{prefix} {number}", 2

    return None, 0


def _find_grade_index_after_course_id(tokens: list[str], start_index: int) -> int | None:
    for idx in range(start_index, len(tokens)):
        token = tokens[idx]

        if not _is_grade_token(token):
            continue

        lookahead = tokens[idx + 1 : idx + 5]

        if any(_is_credit_token(t) for t in lookahead):
            return idx

    return None


def _extract_credits_after_grade(tokens: list[str], grade_index: int) -> tuple[float | None, float | None, tuple[int, int]]:
    credit_tokens: list[tuple[int, str]] = []

    for idx in range(grade_index + 1, min(len(tokens), grade_index + 7)):
        token = tokens[idx]

        if _is_credit_token(token):
            credit_tokens.append((idx, token))

        if len(credit_tokens) >= 2:
            break

    if not credit_tokens:
        return None, None, (grade_index + 1, grade_index + 1)

    first_idx, first_token = credit_tokens[0]

    if CREDIT_PAIR_RE.fullmatch(first_token):
        attempted, completed = _parse_credit_pair(first_token)
        return attempted, completed, (first_idx, first_idx + 1)

    attempted = _coerce_float(first_token)
    completed = None

    end_idx = first_idx + 1

    if len(credit_tokens) >= 2:
        second_idx, second_token = credit_tokens[1]
        completed = _coerce_float(second_token)
        end_idx = second_idx + 1

    if completed is None:
        completed = attempted

    return attempted, completed, (first_idx, end_idx)


def _parse_course_line(words: list[Word]) -> ParsedCourseLine | None:
    tokens = [w.text for w in words]
    text = _line_text(words)

    if not text or _looks_like_skip_line(text):
        return None

    course_id, used = _looks_like_course_id_tokens(tokens)

    if not course_id:
        return None

    grade_index = _find_grade_index_after_course_id(tokens, used)

    if grade_index is None:
        return None

    course_name_tokens = tokens[used:grade_index]
    course_name = _normalize_space(" ".join(course_name_tokens))

    if not course_name:
        return None

    if _looks_like_skip_line(course_name):
        return None

    grade = _normalize_grade(tokens[grade_index])
    attempted, completed, credit_span = _extract_credits_after_grade(tokens, grade_index)

    return ParsedCourseLine(
        course_id=_normalize_space(course_id),
        course_name=course_name,
        grade=grade,
        credit_attempted=attempted,
        credit_completed=completed,
        line_text=text,
        course_id_token_span=(0, used),
        course_name_token_span=(used, grade_index),
        grade_token_span=(grade_index, grade_index + 1),
        credit_token_span=credit_span,
    )


# ---------------------------------------------------------------------------
# Column entry building / context assignment
# ---------------------------------------------------------------------------

def _build_column_entries(
    column_words_by_line: list[list[Word]],
    *,
    page_number: int,
    column_name: str,
) -> list[ColumnEntry]:
    entries: list[ColumnEntry] = []

    for words in column_words_by_line:
        if not words:
            continue

        sorted_words = sorted(words, key=lambda word: word.x0)
        text = _line_text(sorted_words)

        if not text:
            continue

        y0 = min(word.y0 for word in sorted_words)
        y1 = max(word.y1 for word in sorted_words)
        y_mid = (y0 + y1) / 2.0

        school_name = _maybe_school_name(text)
        if school_name:
            entries.append(
                ColumnEntry(
                    kind="school",
                    words=sorted_words,
                    text=text,
                    y0=y0,
                    y1=y1,
                    y_mid=y_mid,
                    school_name=school_name,
                )
            )
            continue

        term_context = _parse_term_header(text)
        if term_context:
            term_context.page_number = page_number
            term_context.visual_column = column_name
            term_context.column_index = COLUMN_INDEX[column_name]
            term_context.header_y = y_mid
            entries.append(
                ColumnEntry(
                    kind="term",
                    words=sorted_words,
                    text=text,
                    y0=y0,
                    y1=y1,
                    y_mid=y_mid,
                    term_context=term_context,
                )
            )
            continue

        parsed_course = _parse_course_line(sorted_words)
        if parsed_course:
            entries.append(
                ColumnEntry(
                    kind="course",
                    words=sorted_words,
                    text=text,
                    y0=y0,
                    y1=y1,
                    y_mid=y_mid,
                    parsed_course=parsed_course,
                )
            )
            continue

        entries.append(
            ColumnEntry(
                kind="other",
                words=sorted_words,
                text=text,
                y0=y0,
                y1=y1,
                y_mid=y_mid,
            )
        )

    entries.sort(key=lambda entry: (entry.y_mid, entry.y0))
    return entries


def _first_term_y(entries: list[ColumnEntry]) -> float | None:
    term_ys = [entry.y_mid for entry in entries if entry.kind == "term"]
    return min(term_ys) if term_ys else None


def _last_useful_context(
    *,
    current_context: TermContext | None,
    starting_context: TermContext | None,
) -> TermContext | None:
    return current_context or starting_context


# ---------------------------------------------------------------------------
# Public extractor
# ---------------------------------------------------------------------------

def extract_transcript_row_geometry(
    pdf_path: str | Path | None = None,
    *,
    pdf_bytes: bytes | None = None,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """
    Extract visual course rows from Mayfair/LBUSD-style transcript PDFs.

    The PDF can be supplied either as a path (``pdf_path``) or as in-memory
    bytes (``pdf_bytes``). Passing bytes lets the caller read geometry directly
    from the transcript already held in memory during processing, so no copy is
    written to or kept on disk.

    Key safety rules:
    - A row only uses a section header above it in the same column.
    - If a column begins with course rows before any header, those leading rows
      inherit the previous column/page active section.
    - A row never inherits a section header below it.
    """
    rows: list[dict[str, Any]] = []

    if pdf_bytes is not None:
        # Read straight from memory; nothing touches the filesystem.
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    else:
        if pdf_path is None:
            raise ValueError(
                "extract_transcript_row_geometry requires either pdf_path or pdf_bytes."
            )
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"Transcript PDF not found: {pdf_path}")
        doc = fitz.open(str(pdf_path))

    try:
        carry_context_from_previous_page: TermContext | None = None
        global_block_index = 0
        row_count_by_context: dict[str, int] = {}

        for page_index, page in enumerate(doc, start=1):
            if max_pages is not None and page_index > max_pages:
                break

            page_width = float(page.rect.width)
            page_height = float(page.rect.height)

            raw_words = page.get_text("words")
            words = [
                Word(
                    text=str(item[4]),
                    x0=float(item[0]),
                    y0=float(item[1]),
                    x1=float(item[2]),
                    y1=float(item[3]),
                )
                for item in raw_words
                if len(item) >= 5 and str(item[4]).strip()
            ]

            lines = _group_words_into_lines(words)
            column_lines: dict[str, list[list[Word]]] = {
                "left": [],
                "middle": [],
                "right": [],
            }

            for line in lines:
                split = _split_line_by_columns(line, page_width)
                for column_name, column_words in split.items():
                    if column_words:
                        column_lines[column_name].append(column_words)

            column_entries = {
                column_name: _build_column_entries(
                    column_lines[column_name],
                    page_number=page_index,
                    column_name=column_name,
                )
                for column_name in COLUMN_NAMES
            }

            carry_context_from_previous_column = carry_context_from_previous_page

            for column_name in COLUMN_NAMES:
                column_index = COLUMN_INDEX[column_name]
                entries = column_entries[column_name]
                first_header_y = _first_term_y(entries)

                starting_continuation_context = carry_context_from_previous_column
                current_context = starting_continuation_context
                current_school = current_context.school_name if current_context else None
                saw_same_column_header = False

                for entry in entries:
                    if entry.kind == "school" and entry.school_name:
                        current_school = entry.school_name
                        if current_context is not None:
                            current_context.school_name = current_school
                        continue

                    if entry.kind == "term" and entry.term_context is not None:
                        global_block_index += 1

                        term_context = entry.term_context
                        term_context.school_name = current_school
                        term_context.block_index = global_block_index
                        term_context.page_number = page_index
                        term_context.visual_column = column_name
                        term_context.column_index = column_index
                        term_context.header_y = entry.y_mid

                        current_context = term_context
                        saw_same_column_header = True
                        row_count_by_context.setdefault(_context_key(current_context), 0)
                        continue

                    if entry.kind != "course" or entry.parsed_course is None:
                        continue

                    parsed = entry.parsed_course
                    context = current_context

                    if context is None:
                        section_name = None
                        section_key = None
                        grade_level = None
                        year = None
                        month = None
                        term_name = None
                        section_source = "missing_context"
                        header_y = None
                        continued_column_context = False
                        context_block_index = None
                    else:
                        is_leading_row_before_first_header = (
                            first_header_y is not None
                            and entry.y_mid < first_header_y
                            and not saw_same_column_header
                        )
                        uses_previous_column_context = (
                            is_leading_row_before_first_header
                            or (
                                first_header_y is None
                                and not saw_same_column_header
                                and starting_continuation_context is not None
                                and context is starting_continuation_context
                            )
                        )

                        section_name = context.section_name
                        section_key = f"{context.grade_level}:{context.year}:{context.month}"
                        grade_level = context.grade_level
                        year = context.year
                        month = context.month
                        term_name = context.term_name
                        header_y = context.header_y
                        context_block_index = context.block_index

                        if uses_previous_column_context:
                            section_source = "continued_previous_column"
                            continued_column_context = True
                        else:
                            section_source = context.source or "same_column_header"
                            continued_column_context = False

                    context_counter_key = _context_key(context)
                    row_count_by_context[context_counter_key] = row_count_by_context.get(context_counter_key, 0) + 1
                    row_in_block = row_count_by_context[context_counter_key]

                    raw_bbox = _words_to_bbox(
                        entry.words,
                        page_width=page_width,
                        page_height=page_height,
                    )
                    row_bbox = _expanded_row_bbox(
                        column_name=column_name,
                        raw_bbox=raw_bbox,
                    )

                    field_bboxes = {
                        "course_id": _bbox_for_token_span(
                            entry.words,
                            parsed.course_id_token_span,
                            page_width=page_width,
                            page_height=page_height,
                        ),
                        "course_name": _bbox_for_token_span(
                            entry.words,
                            parsed.course_name_token_span,
                            page_width=page_width,
                            page_height=page_height,
                        ),
                        "grade": _bbox_for_token_span(
                            entry.words,
                            parsed.grade_token_span,
                            page_width=page_width,
                            page_height=page_height,
                        ),
                        "credits": _bbox_for_token_span(
                            entry.words,
                            parsed.credit_token_span,
                            page_width=page_width,
                            page_height=page_height,
                        ),
                    }

                    rows.append(
                        {
                            "geometry_row_index": len(rows) + 1,
                            "page_number": page_index,
                            "visual_column": column_name,
                            "column_index": column_index,
                            "block_index": context_block_index,
                            "row_in_block": row_in_block,
                            "section_name": section_name,
                            "section_key": section_key,
                            "term_name": term_name,
                            "section_source": section_source,
                            "continued_column_context": continued_column_context,
                            "first_header_y_in_column": first_header_y,
                            "header_y": header_y,
                            "row_y": entry.y_mid,
                            "school_name": current_school or (context.school_name if context else None),
                            "grade_level": grade_level,
                            "year": year,
                            "month": month,
                            "course_id": parsed.course_id,
                            "course_name": parsed.course_name,
                            "grade": parsed.grade,
                            "credit_attempted": parsed.credit_attempted,
                            "credit_completed": parsed.credit_completed,
                            "row_bbox": row_bbox,
                            "raw_word_bbox": raw_bbox,
                            "field_bboxes": field_bboxes,
                            "line_text": parsed.line_text,
                            "visual_sort_key": [
                                page_index,
                                column_index,
                                entry.y_mid,
                            ],
                            "geometry_source": "pymupdf_text_words",
                            "context_assignment_rule": (
                                "previous_column_header_above"
                                if section_source == "continued_previous_column"
                                else (
                                    "same_column_header_above"
                                    if context is not None
                                    else "missing_context"
                                )
                            ),
                        }
                    )

                carry_context_from_previous_column = _last_useful_context(
                    current_context=current_context,
                    starting_context=starting_continuation_context,
                )

            carry_context_from_previous_page = carry_context_from_previous_column

    finally:
        doc.close()

    rows.sort(
        key=lambda row: (
            row.get("page_number") or 0,
            row.get("column_index") or 0,
            row.get("row_y") or 0,
            row.get("geometry_row_index") or 0,
        )
    )

    for index, row in enumerate(rows, start=1):
        row["geometry_row_index"] = index
        row["geometry_alignment_key"] = (
            f"p{row.get('page_number')}:"
            f"c{row.get('column_index')}:"
            f"b{row.get('block_index')}:"
            f"r{row.get('row_in_block')}"
        )

    return rows


# Backward-friendly aliases.
def extract_mayfair_lbusd_row_geometry(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    return extract_transcript_row_geometry(pdf_path, max_pages=max_pages)


def extract_lbusd_row_geometry(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    return extract_transcript_row_geometry(pdf_path, max_pages=max_pages)


# ---------------------------------------------------------------------------
# Debug / CLI
# ---------------------------------------------------------------------------

def _print_debug_rows(rows: list[dict[str, Any]], limit: int = 80) -> None:
    for row in rows[:limit]:
        print(
            f"{row.get('geometry_row_index'):>3} | "
            f"p{row.get('page_number')} {row.get('visual_column'):<6} | "
            f"{row.get('section_name') or 'NO SECTION':<35} | "
            f"{row.get('section_source') or '':<27} | "
            f"{row.get('course_id') or '':<12} | "
            f"{row.get('course_name') or '':<35} | "
            f"{row.get('grade') or '':<3} | "
            f"{row.get('credit_attempted')} / {row.get('credit_completed')}"
        )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python transcript_row_geometry.py <transcript.pdf> [limit]")
        return 2

    pdf_path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) >= 3 else 80

    rows = extract_transcript_row_geometry(pdf_path)
    print(f"Detected {len(rows)} visual course rows")
    print()
    _print_debug_rows(rows, limit=limit)
    print()
    print(json.dumps(rows[: min(limit, len(rows))], indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
