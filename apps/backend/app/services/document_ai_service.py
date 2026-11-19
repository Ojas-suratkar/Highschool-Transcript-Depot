"""
Document AI integration service.

This service wraps Google Document AI calls and normalizes outputs into
header (student-level) and course rows (course-level) suitable for insertion
into unified tables: student_details and course_details.

Excel export is intentionally removed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
import multiprocessing
import re
import time
import random

try:
    from google.cloud import documentai_v1 as documentai
    from google.api_core.exceptions import (
        InternalServerError,
        ServiceUnavailable,
        DeadlineExceeded,
        ResourceExhausted,
        TooManyRequests,
    )
    import grpc
except Exception:
    documentai = None  # Allow import even if SDK not installed
    InternalServerError = ServiceUnavailable = DeadlineExceeded = Exception
    ResourceExhausted = TooManyRequests = Exception
    grpc = None

_TRANSIENT_GRPC_CODES = None


def _get_transient_grpc_codes():
    global _TRANSIENT_GRPC_CODES
    if _TRANSIENT_GRPC_CODES is None and grpc is not None:
        _TRANSIENT_GRPC_CODES = {
            grpc.StatusCode.INTERNAL,
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.RESOURCE_EXHAUSTED,
        }
    return _TRANSIENT_GRPC_CODES or set()


def _process_with_retry(client, request, max_retries: int = 6, base_delay: float = 1.0, timeout: float = 120):
    last_err = None
    for attempt in range(1, max_retries + 1):
        is_quota = False
        try:
            return client.process_document(request=request, timeout=timeout)
        except (ResourceExhausted, TooManyRequests) as e:
            last_err = e
            is_quota = True  # 429 quota — retry with longer backoff instead of failing
        except (InternalServerError, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
        except Exception as e:
            if grpc is not None and isinstance(e, grpc.RpcError) and e.code() in _get_transient_grpc_codes():
                last_err = e
                is_quota = e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
            else:
                raise
        # 429 quota recovers per-minute, so wait longer for it than other transients.
        sleep_s = base_delay * (4.0 if is_quota else 1.0) * (2 ** (attempt - 1)) + random.uniform(0, 0.6)
        sleep_s = min(sleep_s, 90.0)
        print(f"[DocumentAI] {'quota 429' if is_quota else 'transient'} error on attempt "
              f"{attempt}/{max_retries}, retrying in {sleep_s:.1f}s: {last_err}")
        time.sleep(sleep_s)
    raise RuntimeError(f"Document AI failed after {max_retries} retries. Last error: {last_err}")


def _extract_grade_only(value: str) -> str:
    """Extract alphabetic grade from combined value like 'A 5.00' → 'A'."""
    if not value:
        return ""
    txt = str(value).strip().upper().replace(",", ".")
    m = re.search(r"\b(?:A|B|C|D|F|P|NP|CR|NC|NM|I|W)(?:[+-])?\b", txt)
    return m.group(0) if m else ""


def _extract_credit_only(value: str) -> float | None:
    """Extract first numeric credit from combined value like 'A 5.00' → 5.0."""
    if not value:
        return None
    txt = str(value).strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", txt)
    return float(m.group(0)) if m else None


def _extract_all_grades(value: str) -> list[str]:
    """Extract all alphabetic grade tokens from a field (e.g. 'A B' → ['A', 'B'])."""
    if not value:
        return []
    txt = str(value).strip().upper()
    return re.findall(r"\b(?:A|B|C|D|F|P|NP|CR|NC|NM|I|W)(?:[+-])?\b", txt)


def _extract_all_credits(value: str) -> list[float]:
    """Extract all numeric credit values from a field (e.g. '5.00 5.00' → [5.0, 5.0])."""
    if not value:
        return []
    txt = str(value).strip().replace(",", ".")
    return [float(m) for m in re.findall(r"-?\d+(?:\.\d+)?", txt)]


def _normalize_scalar_number(val: str | None) -> float | None:
    if val is None:
        return None
    txt = str(val).strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", txt)
    return float(m.group(0)) if m else None


def _normalize_ratio(val: str | None) -> tuple[float | None, float | None, str | None]:
    """Return (attempted, completed, raw) from inputs like "5,00/5,00"."""
    if val is None:
        return None, None, None
    raw = str(val).strip().replace(",", ".")
    nums = re.findall(r"\d+(?:\.\d+)?", raw)
    if len(nums) >= 2:
        a, b = float(nums[0]), float(nums[1])
    elif len(nums) == 1:
        a = b = float(nums[0])
    else:
        return None, None, raw
    return a, b, raw


def _get_text(ent: Any) -> str:
    return (getattr(ent, "mention_text", "") or "").strip()


def _enhance_page_image(img: "Image.Image") -> "Image.Image":
    """Apply a gamma+contrast enhancement to a PIL image using only PIL
    (no numpy) so memory stays in uint8 throughout — safe for concurrent use."""
    from PIL import ImageEnhance

    # Gamma darkening via a 256-entry lookup table — ~3KB overhead, no copies.
    gamma = 2.2
    lut = [min(255, int(255 * (i / 255.0) ** gamma)) for i in range(256)]
    lut_rgb = lut * 3  # replicate for R, G, B channels
    img = img.point(lut_rgb)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img


# PDF enhancement subprocess script.
# Renderer chain: pypdfium2 (fast) → pymupdf/fitz (robust fallback).
# Every page is tried with both renderers independently so we always
# produce a fully enhanced image regardless of PDF type or corruption.
_ENHANCE_SCRIPT = r"""
import sys, io, struct

def read_exact(n):
    buf = b''
    while len(buf) < n:
        chunk = sys.stdin.buffer.read(n - len(buf))
        if not chunk:
            raise EOFError()
        buf += chunk
    return buf

raw = read_exact(8)
pdf_bytes = read_exact(struct.unpack('>Q', raw)[0])

def write_result(data, mime_str):
    mime = mime_str.encode()
    sys.stdout.buffer.write(struct.pack('>I', len(mime)))
    sys.stdout.buffer.write(mime)
    sys.stdout.buffer.write(struct.pack('>Q', len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

from PIL import Image, ImageEnhance

gamma = 2.2
lut = [min(255, int(255 * (i / 255.0) ** gamma)) for i in range(256)] * 3

def enhance(img):
    img = img.convert('RGB')
    img = img.point(lut)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img

def to_enhanced_png(pil_img):
    buf = io.BytesIO()
    enhance(pil_img).save(buf, format='PNG')
    return buf.getvalue()

# --- Renderer A: pypdfium2 ---
def render_page_pdfium(pdf_bytes, page_index, scale=4.0):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n = len(doc)
        if n == 0 or page_index >= n:
            return None
        page = doc[page_index]
        w, h = page.get_width(), page.get_height()
        if w <= 0 or h <= 0:
            return None
        bmp = page.render(scale=scale)
        img = bmp.to_pil()
        del bmp
        return to_enhanced_png(img)
    finally:
        try: doc.close()
        except: pass

def get_page_count_pdfium(pdf_bytes):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(doc)
    finally:
        try: doc.close()
        except: pass

# --- Renderer B: pymupdf (fitz) — handles PDFs pdfium crashes on ---
def render_page_mupdf(pdf_bytes, page_index, dpi=288):
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        if page_index >= doc.page_count:
            return None
        page = doc[page_index]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        return to_enhanced_png(img)
    finally:
        try: doc.close()
        except: pass

def get_page_count_mupdf(pdf_bytes):
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        return doc.page_count
    finally:
        try: doc.close()
        except: pass

def render_page_best(pdf_bytes, page_index):
    # Try pdfium first (faster); fall back to mupdf on any failure.
    try:
        result = render_page_pdfium(pdf_bytes, page_index)
        if result:
            return result
    except Exception:
        pass
    try:
        return render_page_mupdf(pdf_bytes, page_index)
    except Exception:
        return None

def get_page_count(pdf_bytes):
    try:
        n = get_page_count_pdfium(pdf_bytes)
        if n > 0:
            return n
    except Exception:
        pass
    try:
        return get_page_count_mupdf(pdf_bytes)
    except Exception:
        return 0

# --- Main ---
page_count = get_page_count(pdf_bytes)

if page_count == 0:
    # Cannot open with either renderer — very rare, truly unrenderable PDF
    write_result(pdf_bytes, 'application/pdf')
    sys.exit(0)

if page_count == 1:
    png = render_page_best(pdf_bytes, 0)
    if png:
        write_result(png, 'image/png')
    else:
        write_result(pdf_bytes, 'application/pdf')
    sys.exit(0)

# Multi-page: render each page; build an enhanced PDF
from fpdf import FPDF
pdf_out = FPDF()
any_rendered = False
for i in range(page_count):
    png = render_page_best(pdf_bytes, i)
    if png:
        img = Image.open(io.BytesIO(png))
        w, h = img.size
        img.close()
        pdf_out.add_page(format=(w * 0.264583, h * 0.264583))
        pdf_out.image(io.BytesIO(png), 0, 0, w * 0.264583, h * 0.264583)
        any_rendered = True

if any_rendered:
    out = io.BytesIO()
    pdf_out.output(out)
    write_result(out.getvalue(), 'application/pdf')
else:
    write_result(pdf_bytes, 'application/pdf')
"""


def _enhance_pdf_for_ocr(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Render PDF pages to contrast-enhanced images so faint glyphs (e.g. the
    far-left '*'/'+ ' course markers) are dark enough for Doc AI's OCR.

    Uses subprocess.run so that:
    - The child imports only pypdfium2+PIL (fast, ~2-4 s startup).
    - A native crash (SIGTRAP/null-deref on malformed PDFs) kills only the
      child — the main server keeps running.
    Falls back to the original PDF bytes silently on any failure or timeout.
    """
    import subprocess
    import struct
    import sys

    try:
        # Length-prefix the PDF so the child knows how many bytes to read.
        payload = struct.pack('>Q', len(pdf_bytes)) + pdf_bytes

        r = subprocess.run(
            [sys.executable, "-c", _ENHANCE_SCRIPT],
            input=payload,
            capture_output=True,
            timeout=60,
        )

        if r.returncode != 0 or not r.stdout:
            return pdf_bytes, "application/pdf"

        out = r.stdout
        mime_len = struct.unpack('>I', out[:4])[0]
        mime = out[4:4 + mime_len].decode()
        result_len = struct.unpack('>Q', out[4 + mime_len:12 + mime_len])[0]
        result = out[12 + mime_len:12 + mime_len + result_len]

        if len(result) != result_len:
            return pdf_bytes, "application/pdf"

        return result, mime

    except Exception:
        return pdf_bytes, "application/pdf"


# ---------------------------------------------------------------------------
# Visual row geometry helpers (Document AI page layout -> OCR visual rows).
# Additive: these produce evidence/metadata consumed by reconciliation only.
# They never mutate course IDs, titles, grades, credits, terms, or row counts.
# ---------------------------------------------------------------------------

def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _bbox_from_normalized_vertices(vertices: Any) -> list[float] | None:
    xs: list[float] = []
    ys: list[float] = []

    for vertex in vertices or []:
        x = getattr(vertex, "x", None)
        y = getattr(vertex, "y", None)

        if x is None or y is None:
            continue

        xs.append(float(x))
        ys.append(float(y))

    if not xs or not ys:
        return None

    return [
        _clip01(min(xs)),
        _clip01(min(ys)),
        _clip01(max(xs)),
        _clip01(max(ys)),
    ]


def _column_from_bbox(
    bbox: list[float] | tuple[float, float, float, float] | None,
) -> str | None:
    if not bbox or len(bbox) != 4:
        return None

    x_mid = (float(bbox[0]) + float(bbox[2])) / 2.0

    # Shared 3-column transcript layout for Mayfair + LBUSD-style transcripts.
    if 0.08 <= x_mid < 0.37:
        return "left"

    if 0.37 <= x_mid < 0.63:
        return "middle"

    if 0.63 <= x_mid <= 0.92:
        return "right"

    # Safe fallback by visual position.
    if x_mid < 0.37:
        return "left"

    if x_mid < 0.63:
        return "middle"

    return "right"


def _expand_bbox_to_transcript_column(
    bbox: list[float] | tuple[float, float, float, float],
    column: str | None,
) -> list[float]:
    _x0, y0, _x1, y1 = [float(v) for v in bbox]
    col = (column or "").lower()

    if col == "left":
        return [0.08, y0, 0.37, y1]

    if col == "middle":
        return [0.37, y0, 0.63, y1]

    if col == "right":
        return [0.63, y0, 0.92, y1]

    return [0.08, y0, 0.92, y1]


def _geometry_from_page_anchor(ent: Any) -> dict[str, Any] | None:
    """
    Extract a normalized bbox from a Document AI entity/page anchor.

    Document AI page_ref.page is usually 0-based, so we convert it to 1-based
    page_number for PyMuPDF crop usage.
    """
    page_anchor = getattr(ent, "page_anchor", None)

    if not page_anchor:
        return None

    page_refs = getattr(page_anchor, "page_refs", None) or []

    for page_ref in page_refs:
        bounding_poly = getattr(page_ref, "bounding_poly", None)

        if not bounding_poly:
            continue

        vertices = getattr(bounding_poly, "normalized_vertices", None) or []
        raw_bbox = _bbox_from_normalized_vertices(vertices)

        if not raw_bbox:
            continue

        page_index = getattr(page_ref, "page", 0) or 0

        try:
            page_number = int(page_index) + 1
        except Exception:
            page_number = 1

        column = _column_from_bbox(raw_bbox)
        row_bbox = _expand_bbox_to_transcript_column(raw_bbox, column)

        return {
            "page_number": page_number,
            "column": column,
            "row_bbox": row_bbox,
            "raw_word_bbox": raw_bbox,
            "geometry_source": "document_ai_page_anchor",
        }

    return None


def _combine_child_geometries(
    geometries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Combine child field geometry into one row-level geometry.

    This is useful when the course entity itself does not have a bounding box,
    but its child properties such as course_id/title/mark/credits do.
    """
    valid = [
        geo
        for geo in geometries
        if isinstance(geo, dict)
        and geo.get("page_number")
        and geo.get("raw_word_bbox")
    ]

    if not valid:
        return None

    # Use the first page represented by child fields.
    page_number = valid[0]["page_number"]
    same_page = [geo for geo in valid if geo.get("page_number") == page_number]

    if not same_page:
        return valid[0]

    x0 = min(float(geo["raw_word_bbox"][0]) for geo in same_page)
    y0 = min(float(geo["raw_word_bbox"][1]) for geo in same_page)
    x1 = max(float(geo["raw_word_bbox"][2]) for geo in same_page)
    y1 = max(float(geo["raw_word_bbox"][3]) for geo in same_page)

    raw_bbox = [_clip01(x0), _clip01(y0), _clip01(x1), _clip01(y1)]
    column = _column_from_bbox(raw_bbox)
    row_bbox = _expand_bbox_to_transcript_column(raw_bbox, column)

    return {
        "page_number": page_number,
        "column": column,
        "row_bbox": row_bbox,
        "raw_word_bbox": raw_bbox,
        "geometry_source": "document_ai_child_page_anchors",
    }


def _extract_entity_geometry(ent: Any) -> dict[str, Any] | None:
    """
    Extract row geometry for a Document AI entity.

    Prefer the entity's own page_anchor. If that is missing, combine geometry
    from child properties. We only need vertical row position plus column;
    row_crop_verifier expands the crop to the full transcript column.
    """
    direct = _geometry_from_page_anchor(ent)

    if direct:
        return direct

    child_geometries: list[dict[str, Any]] = []

    for prop in getattr(ent, "properties", []) or []:
        child_geo = _geometry_from_page_anchor(prop)

        if child_geo:
            child_geometries.append(child_geo)

    return _combine_child_geometries(child_geometries)


def _extract_first_int(value: Any) -> str:
    txt = _normalize_spaces(value)
    m = re.search(r"\b(\d{1,2})\b", txt)
    return m.group(1) if m else ""


def _normalize_spaces(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_academic_year(value: Any) -> str:
    """Return the academic start year.

    Examples:
      2021-2022 -> 2021
      21-22     -> 2021
      2023      -> 2023
    """
    txt = _normalize_spaces(value)
    if not txt:
        return ""

    m = re.search(r"\b(20\d{2})\s*[-–—/]\s*(?:20)?\d{2}\b", txt)
    if m:
        return m.group(1)

    m = re.search(r"\b(\d{2})\s*[-–—/]\s*(\d{2})\b", txt)
    if m:
        return str(2000 + int(m.group(1)))

    m = re.search(r"\b(20\d{2})\b", txt)
    if m:
        return m.group(1)

    return txt


def _normalize_term_month(value: Any) -> str:
    """Normalize term words to your pipeline month convention.

    Fall   -> 1
    Spring -> 6
    Summer/Intersession -> 7

    Numeric months are preserved.
    """
    txt = _normalize_spaces(value)
    low = txt.lower()

    if not txt:
        return ""

    if "fall" in low or "semester 1" in low or "sem 1" in low:
        return "1"

    if "spring" in low or "semester 2" in low or "sem 2" in low:
        return "6"

    if "summer" in low or "intersession" in low:
        return "7"

    m = re.search(r"\bMonth\s*:?\s*(\d{1,2})\b", txt, re.I)
    if m:
        return m.group(1)

    m = re.fullmatch(r"\d{1,2}", txt)
    if m:
        return txt

    return txt


def _normalize_term_grade(value: Any) -> str:
    """Extract grade level from values like 'Grade 9 Spring 2021-2022'."""
    txt = _normalize_spaces(value)
    if not txt:
        return ""

    m = re.search(r"\bGrade\s*:?\s*(\d{1,2})\b", txt, re.I)
    if m:
        return m.group(1)

    # Avoid taking years as grade levels.
    nums = [n for n in re.findall(r"\b\d{1,2}\b", txt) if 1 <= int(n) <= 12]
    return nums[0] if nums else txt


def _normalize_term_context(term_grade: Any, term_month: Any, term_year: Any) -> dict[str, str]:
    """Normalize term context without changing course values.

    This is intentionally conservative: it repairs common Mayfair/LBUSD term
    strings but does not invent a value when no signal exists.
    """
    joined = " ".join(
        part
        for part in [
            _normalize_spaces(term_grade),
            _normalize_spaces(term_month),
            _normalize_spaces(term_year),
        ]
        if part
    )

    grade = _normalize_term_grade(term_grade) or _normalize_term_grade(joined)
    month = _normalize_term_month(term_month) or _normalize_term_month(joined)
    year = _normalize_academic_year(term_year) or _normalize_academic_year(joined)

    return {
        "term_grade": grade,
        "term_month": month,
        "term_year": year,
    }


def _section_name_from_row(row: dict[str, Any]) -> str:
    grade = _normalize_spaces(row.get("term_grade"))
    year = _normalize_spaces(row.get("term_year"))
    month = _normalize_spaces(row.get("term_month"))
    school = _normalize_spaces(row.get("term_school_name"))

    pieces = []
    if school:
        pieces.append(school)
    if grade:
        pieces.append(f"Grade {grade}")
    if year:
        pieces.append(f"Year {year}")
    if month:
        pieces.append(f"Month {month}")

    return " | ".join(pieces)


def _row_bbox_y0(row: dict[str, Any]) -> float:
    bbox = row.get("document_ai_raw_word_bbox") or row.get("document_ai_row_bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return float(bbox[1])
        except Exception:
            pass
    return 999.0


def _row_bbox_x0(row: dict[str, Any]) -> float:
    bbox = row.get("document_ai_raw_word_bbox") or row.get("document_ai_row_bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return float(bbox[0])
        except Exception:
            pass
    return 999.0


def _document_ai_visual_sort_key(row: dict[str, Any], fallback_index: int) -> tuple[Any, ...]:
    page = row.get("document_ai_page_number") or 999
    try:
        page = int(page)
    except Exception:
        page = 999

    column = str(row.get("document_ai_column") or "").lower()
    column_order = {"left": 0, "middle": 1, "right": 2}.get(column, 9)

    return (
        page,
        column_order,
        _row_bbox_y0(row),
        _row_bbox_x0(row),
        fallback_index,
    )


def _should_visual_sort_document_ai_rows(rows: list[dict[str, Any]], header: dict[str, Any]) -> bool:
    """Sort only when geometry is present enough to be useful.

    We avoid visual sorting St. Anthony rows because those are semester-summary
    style rows and the old semantic order is safer there.
    """
    if not rows:
        return False

    school_text = " ".join(
        _normalize_spaces(v)
        for v in [
            header.get("student_school"),
            rows[0].get("term_school_name"),
            rows[0].get("student_school"),
        ]
        if v
    ).lower()

    if "anthony" in school_text:
        return False

    geometry_count = sum(1 for row in rows if row.get("document_ai_raw_word_bbox") or row.get("document_ai_row_bbox"))
    return geometry_count >= max(3, int(len(rows) * 0.50))


def _attach_document_ai_sequence_metadata(rows: list[dict[str, Any]], header: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach visual row/column/block metadata to Document AI course rows.

    This does not change extracted course values. It only adds evidence that
    downstream reconciliation can use to avoid matching fields from the wrong
    nearby row or wrong continued column.
    """
    if not rows:
        return rows

    working_rows = list(rows)

    for original_index, row in enumerate(working_rows, start=1):
        row["document_ai_original_row_index"] = original_index
        row["document_ai_has_geometry"] = bool(row.get("document_ai_raw_word_bbox") or row.get("document_ai_row_bbox"))
        row["document_ai_section_name"] = _section_name_from_row(row)
        row["document_ai_section_key"] = "|".join(
            [
                _normalize_spaces(row.get("term_school_name")).lower(),
                _normalize_spaces(row.get("term_grade")),
                _normalize_spaces(row.get("term_year")),
                _normalize_spaces(row.get("term_month")),
            ]
        )
        row["document_ai_visual_sort_key"] = list(_document_ai_visual_sort_key(row, original_index))

    if _should_visual_sort_document_ai_rows(working_rows, header):
        working_rows.sort(
            key=lambda item: _document_ai_visual_sort_key(
                item,
                int(item.get("document_ai_original_row_index") or 999999),
            )
        )

    page_counts: dict[int, int] = {}
    column_counts: dict[tuple[int, str], int] = {}
    block_index = 0
    last_section_key: str | None = None
    row_in_block = 0

    for visual_index, row in enumerate(working_rows, start=1):
        page_value = row.get("document_ai_page_number") or 1
        try:
            page_number = int(page_value)
        except Exception:
            page_number = 1

        column = str(row.get("document_ai_column") or "unknown").lower()
        section_key = str(row.get("document_ai_section_key") or "")

        page_counts[page_number] = page_counts.get(page_number, 0) + 1
        column_key = (page_number, column)
        column_counts[column_key] = column_counts.get(column_key, 0) + 1

        if section_key != last_section_key:
            block_index += 1
            row_in_block = 1
            last_section_key = section_key
        else:
            row_in_block += 1

        row["document_ai_row_index"] = visual_index
        row["document_ai_visual_row_index"] = visual_index
        row["document_ai_page_row_index"] = page_counts[page_number]
        row["document_ai_column_row_index"] = column_counts[column_key]
        row["document_ai_block_index"] = block_index
        row["document_ai_row_in_block"] = row_in_block
        row["document_ai_alignment_key"] = f"p{page_number}:{column}:b{block_index}:r{row_in_block}"
        row["document_ai_sequence_source"] = "document_ai_geometry" if row.get("document_ai_has_geometry") else "document_ai_entity_order"


    return working_rows


def _text_from_text_anchor(doc_text: str, text_anchor: Any) -> str:
    """Return Document AI text for a layout text_anchor.

    This is OCR/layout evidence only. It does not alter the extracted course
    values coming from Document AI entities.
    """
    if not doc_text or not text_anchor:
        return ""

    pieces: list[str] = []
    for segment in getattr(text_anchor, "text_segments", []) or []:
        try:
            start = int(getattr(segment, "start_index", 0) or 0)
            end = int(getattr(segment, "end_index", 0) or 0)
        except Exception:
            continue

        if end <= start:
            continue

        pieces.append(doc_text[start:end])

    return _normalize_spaces(" ".join(pieces))


def _bbox_from_layout(layout: Any) -> list[float] | None:
    if not layout:
        return None

    bounding_poly = getattr(layout, "bounding_poly", None)
    if not bounding_poly:
        return None

    vertices = getattr(bounding_poly, "normalized_vertices", None) or []
    return _bbox_from_normalized_vertices(vertices)


def _ocr_row_sort_key(row: dict[str, Any], fallback_index: int = 0) -> tuple[Any, ...]:
    page = row.get("page_number") or 999
    try:
        page = int(page)
    except Exception:
        page = 999

    column = str(row.get("column") or "").lower()
    column_order = {"left": 0, "middle": 1, "right": 2}.get(column, 9)

    return (
        page,
        column_order,
        float(row.get("y0") or 999.0),
        float(row.get("x0") or 999.0),
        fallback_index,
    )


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_spaces(value).lower())


def _token_set(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_spaces(value).lower())
        if len(token) >= 2 and token not in {"and", "the", "of", "in", "to", "a"}
    }


def _base_grade(value: Any) -> str:
    grade = _extract_grade_only(str(value or ""))
    if not grade:
        return ""
    grade = grade.upper()
    if grade in {"A+", "A-"}:
        return "A"
    if grade in {"B+", "B-"}:
        return "B"
    if grade in {"C+", "C-"}:
        return "C"
    if grade in {"D+", "D-"}:
        return "D"
    return grade


def _normalize_ocr_course_id(value: Any) -> str:
    txt = _normalize_spaces(value)
    if not txt:
        return ""

    # Safe evidence-only repair for OCR/Gemini variants like "9205 p".
    m = re.fullmatch(r"(\d{3,5})\s+([pPhHnNrR])", txt)
    if m:
        return f"{m.group(2)} {m.group(1)}"

    return txt


def _parse_ocr_section_header(text: Any) -> dict[str, str] | None:
    """Parse a visual term/header line from OCR text.

    Supported examples:
      Grade 9 Spring 2021-2022
      Grade 11 Fall 2023-2024
      Yr: 2021 Month: 6 Grade: 10

    Returns normalized pipeline values: Fall=1, Spring=6, Summer=7, and
    academic year=start year.
    """
    txt = _normalize_spaces(text)
    if not txt:
        return None

    mayfair = re.search(
        r"\bGrade\s*:?[\s]*(\d{1,2})\b.*?\b(Fall|Spring|Summer|Intersession)\b.*?\b((?:20)?\d{2}\s*[-–—/]\s*(?:20)?\d{2}|20\d{2})\b",
        txt,
        re.I,
    )
    if mayfair:
        return {
            "term_grade": mayfair.group(1),
            "term_month": _normalize_term_month(mayfair.group(2)),
            "term_year": _normalize_academic_year(mayfair.group(3)),
            "section_label": txt,
        }

    # LBUSD-style header can have the three values in one line.
    year_match = re.search(r"\b(?:Yr|Year)\s*:?[\s]*(20\d{2}|\d{2})\b", txt, re.I)
    month_match = re.search(r"\bMonth\s*:?[\s]*(\d{1,2})\b", txt, re.I)
    grade_match = re.search(r"\bGrade\s*:?[\s]*(\d{1,2})\b", txt, re.I)

    if year_match and month_match and grade_match:
        return {
            "term_grade": _normalize_term_grade(grade_match.group(1)),
            "term_month": _normalize_term_month(month_match.group(1)),
            "term_year": _normalize_academic_year(year_match.group(1)),
            "section_label": txt,
        }

    return None


def _parse_ocr_course_like_row(text: Any) -> dict[str, Any]:
    """Best-effort OCR visual-row parser used only as evidence.

    It never changes Document AI extracted course values. It helps later code
    see whether a course id/title/grade/credit appear on the same visual line.
    """
    txt = _normalize_spaces(text)
    if not txt:
        return {}

    low = txt.lower()
    if any(
        marker in low
        for marker in [
            "crs id",
            "course title",
            "credit att",
            "credit cmp",
            "tgpa",
            "gpa:",
            "parent/guardian",
            "continued on next column",
        ]
    ):
        return {}

    course_id_re = re.compile(
        r"^\s*(?P<course_id>(?:(?:\+|\*)\s*)?(?:(?:HP|H|N|P|R)\s+)?(?:p\s*)?\d{3,5}|CC\d{3})\s+(?P<rest>.+)$",
        re.I,
    )
    m = course_id_re.match(txt)
    if not m:
        return {}

    course_id = _normalize_ocr_course_id(m.group("course_id"))
    rest = _normalize_spaces(m.group("rest"))

    grade_matches = list(
        re.finditer(r"\b(A[+-]?|B[+-]?|C[+-]?|D[+-]?|F|P|NP|CR|NC|NM|I|W)\b", rest, re.I)
    )
    if not grade_matches:
        return {
            "ocr_course_id": course_id,
            "ocr_course_name": rest,
        }

    # Use the first grade token that is followed by a credit-like number, otherwise the last grade token.
    selected = grade_matches[-1]
    for candidate in grade_matches:
        tail = rest[candidate.end():]
        if re.search(r"\d+(?:[\.,]\d+)?", tail):
            selected = candidate
            break

    course_name = _normalize_spaces(rest[: selected.start()])
    grade = selected.group(1).upper()
    credits = _extract_all_credits(rest[selected.end():])

    return {
        "ocr_course_id": course_id,
        "ocr_course_name": course_name,
        "ocr_grade": grade,
        "ocr_credit_attempted": credits[0] if credits else None,
        "ocr_credit_completed": credits[1] if len(credits) > 1 else (credits[0] if credits else None),
    }


def _make_ocr_row(
    *,
    text: str,
    raw_bbox: list[float],
    page_number: int,
    line_index: int,
    source: str,
) -> dict[str, Any] | None:
    text = _normalize_spaces(text)
    if not text or not raw_bbox:
        return None

    column = _column_from_bbox(raw_bbox)
    row_bbox = _expand_bbox_to_transcript_column(raw_bbox, column)
    parsed_course = _parse_ocr_course_like_row(text)
    parsed_section = _parse_ocr_section_header(text) or {}

    x0, y0, x1, y1 = [float(v) for v in raw_bbox]
    row: dict[str, Any] = {
        "page_number": page_number,
        "line_index": line_index,
        "text": text,
        "column": column,
        "row_bbox": row_bbox,
        "raw_word_bbox": raw_bbox,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "ocr_source": source,
        "is_section_header": bool(parsed_section),
    }
    row.update(parsed_course)
    row.update(parsed_section)
    return row


def _extract_document_ai_line_rows(doc: Any) -> list[dict[str, Any]]:
    """Extract OCR line geometry from Document AI page layout.

    This reads page.lines when available. It is safe for scanned PDFs because it
    uses Document AI OCR layout, not PyMuPDF embedded text.
    """
    doc_text = getattr(doc, "text", "") or ""
    rows: list[dict[str, Any]] = []

    for page_index, page in enumerate(getattr(doc, "pages", []) or [], start=1):
        for line_index, line in enumerate(getattr(page, "lines", []) or [], start=1):
            layout = getattr(line, "layout", None)
            text = _text_from_text_anchor(doc_text, getattr(layout, "text_anchor", None))
            raw_bbox = _bbox_from_layout(layout)
            if not text or not raw_bbox:
                continue
            row = _make_ocr_row(
                text=text,
                raw_bbox=raw_bbox,
                page_number=page_index,
                line_index=line_index,
                source="document_ai_page_line",
            )
            if row:
                rows.append(row)

    return rows


def _extract_document_ai_token_group_rows(doc: Any) -> list[dict[str, Any]]:
    """Fallback OCR row construction from tokens when page.lines is unavailable."""
    doc_text = getattr(doc, "text", "") or ""
    rows: list[dict[str, Any]] = []

    for page_index, page in enumerate(getattr(doc, "pages", []) or [], start=1):
        token_items: list[dict[str, Any]] = []
        for token in getattr(page, "tokens", []) or []:
            layout = getattr(token, "layout", None)
            token_text = _text_from_text_anchor(doc_text, getattr(layout, "text_anchor", None))
            raw_bbox = _bbox_from_layout(layout)
            if not token_text or not raw_bbox:
                continue
            x0, y0, x1, y1 = [float(v) for v in raw_bbox]
            token_items.append(
                {
                    "text": token_text,
                    "bbox": raw_bbox,
                    "column": _column_from_bbox(raw_bbox),
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1,
                    "ymid": (y0 + y1) / 2.0,
                }
            )

        token_items.sort(key=lambda item: ({"left": 0, "middle": 1, "right": 2}.get(item["column"], 9), item["ymid"], item["x0"]))

        current: list[dict[str, Any]] = []
        current_column: str | None = None
        current_y: float | None = None
        line_index = 0

        def flush() -> None:
            nonlocal line_index, current
            if not current:
                return
            current.sort(key=lambda item: item["x0"])
            x0 = min(item["x0"] for item in current)
            y0 = min(item["y0"] for item in current)
            x1 = max(item["x1"] for item in current)
            y1 = max(item["y1"] for item in current)
            text = " ".join(item["text"] for item in current)
            line_index += 1
            row = _make_ocr_row(
                text=text,
                raw_bbox=[_clip01(x0), _clip01(y0), _clip01(x1), _clip01(y1)],
                page_number=page_index,
                line_index=line_index,
                source="document_ai_token_group",
            )
            if row:
                rows.append(row)
            current = []

        for token_item in token_items:
            token_col = token_item["column"]
            token_y = float(token_item["ymid"])
            same_line = (
                current
                and token_col == current_column
                and current_y is not None
                and abs(token_y - current_y) <= 0.0065
            )
            if not current or same_line:
                current.append(token_item)
                current_column = token_col
                current_y = token_y if current_y is None else ((current_y * (len(current) - 1)) + token_y) / len(current)
            else:
                flush()
                current = [token_item]
                current_column = token_col
                current_y = token_y

        flush()

    return rows


def _attach_section_context_to_ocr_rows(ocr_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach visual term context to OCR rows.

    Course rows inherit only a header that appears above them in the same column,
    or the previous column's active section when the current column starts as a
    continuation. A row never inherits a header below it.
    """
    if not ocr_rows:
        return ocr_rows

    by_page: dict[int, list[dict[str, Any]]] = {}
    for row in ocr_rows:
        try:
            page_number = int(row.get("page_number") or 1)
        except Exception:
            page_number = 1
        by_page.setdefault(page_number, []).append(row)

    output: list[dict[str, Any]] = []
    column_order = ["left", "middle", "right"]

    for page_number in sorted(by_page):
        page_rows = by_page[page_number]
        previous_column_section: dict[str, Any] | None = None

        for column in column_order:
            column_rows = [row for row in page_rows if str(row.get("column") or "").lower() == column]
            column_rows.sort(key=lambda item: (float(item.get("y0") or 999.0), float(item.get("x0") or 999.0)))

            active_section = previous_column_section.copy() if previous_column_section else None
            active_source = "continued_previous_column" if active_section else "unknown"
            saw_header_in_column = False

            for row in column_rows:
                if row.get("is_section_header"):
                    active_section = {
                        "term_grade": row.get("term_grade") or "",
                        "term_month": row.get("term_month") or "",
                        "term_year": row.get("term_year") or "",
                        "section_label": row.get("section_label") or row.get("text") or "",
                    }
                    active_source = "same_column_header"
                    saw_header_in_column = True

                if active_section:
                    row["ocr_section_grade"] = active_section.get("term_grade", "")
                    row["ocr_section_month"] = active_section.get("term_month", "")
                    row["ocr_section_year"] = active_section.get("term_year", "")
                    row["ocr_section_label"] = active_section.get("section_label", "")
                    row["ocr_section_source"] = active_source
                else:
                    row["ocr_section_grade"] = ""
                    row["ocr_section_month"] = ""
                    row["ocr_section_year"] = ""
                    row["ocr_section_label"] = ""
                    row["ocr_section_source"] = "unknown"

                # If the first real header in this column has appeared, rows after it
                # should be same-column; rows above it keep continued_previous_column.
                if saw_header_in_column and not row.get("is_section_header"):
                    active_source = "same_column_header"

            if active_section:
                previous_column_section = active_section.copy()

            output.extend(column_rows)

        # Preserve rows outside the known three transcript columns, if any.
        known_ids = {id(row) for row in output}
        for row in page_rows:
            if id(row) not in known_ids:
                output.append(row)

    output.sort(key=lambda item: _ocr_row_sort_key(item, int(item.get("line_index") or 0)))

    for idx, row in enumerate(output, start=1):
        row["ocr_visual_row_index"] = idx
        row["ocr_alignment_key"] = f"p{row.get('page_number')}:c{row.get('column')}:r{idx}"

    return output


def _dedupe_ocr_visual_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate OCR rows created from page.lines + token grouping.

    This is evidence-only dedupe. It does not affect extracted course rows.
    """
    if not rows:
        return []

    kept: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for idx, row in enumerate(rows):
        text_key = _normalize_match_text(row.get("text"))
        page = row.get("page_number") or 0
        column = str(row.get("column") or "").lower()
        y_bucket = round(float(row.get("y0") or 0.0), 3)
        x_bucket = round(float(row.get("x0") or 0.0), 3)
        key = (page, column, y_bucket, x_bucket, text_key)

        if key in seen:
            continue

        seen.add(key)
        row.setdefault("ocr_combined_index", idx + 1)
        kept.append(row)

    return kept


def _extract_document_ai_ocr_visual_rows(doc: Any) -> list[dict[str, Any]]:
    """Build full OCR visual rows from Document AI page layout.

    Safe behavior:
    - Uses Document AI OCR layout, so scanned/image PDFs are supported.
    - Combines page.lines and token-grouped rows because page.lines can split
      transcript tables into partial cell fragments.
    - This only creates evidence rows. It does not change extracted courses,
      counts, grades, credits, course IDs, or status.
    """
    line_rows = _extract_document_ai_line_rows(doc)
    token_rows = _extract_document_ai_token_group_rows(doc)

    # Keep both sources when available. Page lines are often cleaner for normal
    # text, while token grouping is better for scanned transcript tables where
    # one visual course row may be split into many line fragments.
    rows = _dedupe_ocr_visual_rows([*line_rows, *token_rows])

    if not rows:
        return []

    return _attach_section_context_to_ocr_rows(rows)


def _bbox_y_overlap_ratio(a: Any, b: Any) -> float:
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != 4 or len(b) != 4:
        return 0.0
    try:
        ay0, ay1 = float(a[1]), float(a[3])
        by0, by1 = float(b[1]), float(b[3])
    except Exception:
        return 0.0

    inter = max(0.0, min(ay1, by1) - max(ay0, by0))
    denom = max(0.0001, min(ay1 - ay0, by1 - by0))
    return inter / denom


def _bbox_x_overlap_ratio(a: Any, b: Any) -> float:
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != 4 or len(b) != 4:
        return 0.0
    try:
        ax0, ax1 = float(a[0]), float(a[2])
        bx0, bx1 = float(b[0]), float(b[2])
    except Exception:
        return 0.0

    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    denom = max(0.0001, min(ax1 - ax0, bx1 - bx0))
    return inter / denom


def _bbox_center_y(bbox: Any) -> float | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return (float(bbox[1]) + float(bbox[3])) / 2.0
    except Exception:
        return None


def _same_page_and_column(course_row: dict[str, Any], ocr_row: dict[str, Any]) -> bool:
    try:
        course_page = int(course_row.get("document_ai_page_number") or 0)
        ocr_page = int(ocr_row.get("page_number") or 0)
    except Exception:
        course_page = 0
        ocr_page = 0

    if course_page and ocr_page and course_page != ocr_page:
        return False

    course_column = str(course_row.get("document_ai_column") or "").lower()
    ocr_column = str(ocr_row.get("column") or "").lower()

    if course_column and ocr_column and course_column != ocr_column:
        return False

    return True


def _best_ocr_visual_row_for_course(course_row: dict[str, Any], ocr_rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    """Find OCR visual row evidence for one Document AI course row.

    This is intentionally tolerant because Document AI page.lines may split a
    scanned table row into cells. The returned OCR row is only metadata; it does
    not change the raw Document AI course values.
    """
    if not course_row or not ocr_rows:
        return None, 0.0

    course_id = _normalize_match_text(course_row.get("course_id"))
    course_title = _normalize_spaces(course_row.get("course_title"))
    title_tokens = _token_set(course_title)
    course_grade = _base_grade(course_row.get("course_mark"))
    course_credit = _normalize_scalar_number(course_row.get("credit_attempted"))

    row_page = course_row.get("document_ai_page_number")
    try:
        row_page_int = int(row_page) if row_page else None
    except Exception:
        row_page_int = None

    row_column = str(course_row.get("document_ai_column") or "").lower()
    row_bbox = course_row.get("document_ai_raw_word_bbox") or course_row.get("document_ai_row_bbox")
    row_y = _bbox_center_y(row_bbox)

    best: dict[str, Any] | None = None
    best_score = 0.0

    for ocr_row in ocr_rows:
        if not _same_page_and_column(course_row, ocr_row):
            continue

        # Avoid selecting section/header rows as the course-row evidence.
        # Their section context will still be inherited by nearby course rows.
        if ocr_row.get("is_section_header"):
            continue

        score = 0.0

        if row_page_int and int(ocr_row.get("page_number") or 0) == row_page_int:
            score += 0.12
        elif row_page_int:
            continue

        if row_column and str(ocr_row.get("column") or "").lower() == row_column:
            score += 0.12

        ocr_bbox = ocr_row.get("raw_word_bbox") or ocr_row.get("row_bbox")
        y_overlap = _bbox_y_overlap_ratio(row_bbox, ocr_bbox)
        x_overlap = _bbox_x_overlap_ratio(row_bbox, ocr_bbox)
        if y_overlap > 0:
            score += min(0.38, y_overlap * 0.38)
        if x_overlap > 0:
            score += min(0.08, x_overlap * 0.08)

        # If Document AI line segmentation splits row cells, center distance is
        # often more stable than overlap.
        ocr_y = _bbox_center_y(ocr_bbox)
        if row_y is not None and ocr_y is not None:
            distance = abs(row_y - ocr_y)
            if distance <= 0.0035:
                score += 0.18
            elif distance <= 0.0075:
                score += 0.10
            elif distance <= 0.015:
                score += 0.04
            else:
                score -= min(0.18, distance * 6.0)

        ocr_id = _normalize_match_text(ocr_row.get("ocr_course_id"))
        ocr_text_norm = _normalize_match_text(ocr_row.get("text"))

        if course_id and ocr_id and course_id == ocr_id:
            score += 0.34
        elif course_id and course_id in ocr_text_norm:
            score += 0.24

        ocr_title_tokens = _token_set(ocr_row.get("ocr_course_name") or ocr_row.get("text"))
        if title_tokens and ocr_title_tokens:
            overlap_count = len(title_tokens & ocr_title_tokens)
            token_ratio = overlap_count / max(1, len(title_tokens))
            score += min(0.26, token_ratio * 0.26)
            if token_ratio >= 0.75:
                score += 0.08

        ocr_grade = _base_grade(ocr_row.get("ocr_grade"))
        if course_grade and ocr_grade and course_grade == ocr_grade:
            score += 0.08

        ocr_credit = _normalize_scalar_number(ocr_row.get("ocr_credit_attempted"))
        if course_credit is not None and ocr_credit is not None and abs(course_credit - ocr_credit) <= 0.01:
            score += 0.04

        if score > best_score:
            best = ocr_row
            best_score = score

    return best, round(best_score, 4)


def _should_attach_ocr_visual_row(
    course_row: dict[str, Any],
    ocr_row: dict[str, Any] | None,
    score: float,
) -> bool:
    """Conservative gate for adding OCR evidence.

    This only controls metadata attachment. It does not approve or modify any
    course value. We allow geometry-only attachment when the visual row overlap
    is strong enough because scanned PDFs often split text into cells.
    """
    if not ocr_row:
        return False

    if score >= 0.45:
        return True

    if not _same_page_and_column(course_row, ocr_row):
        return False

    row_bbox = course_row.get("document_ai_raw_word_bbox") or course_row.get("document_ai_row_bbox")
    ocr_bbox = ocr_row.get("raw_word_bbox") or ocr_row.get("row_bbox")

    y_overlap = _bbox_y_overlap_ratio(row_bbox, ocr_bbox)
    row_y = _bbox_center_y(row_bbox)
    ocr_y = _bbox_center_y(ocr_bbox)
    center_close = (
        row_y is not None
        and ocr_y is not None
        and abs(row_y - ocr_y) <= 0.006
    )

    # Strong same-line geometry is enough for evidence-only attachment.
    if y_overlap >= 0.45 or (center_close and score >= 0.28):
        return True

    # Text agreement can also justify attachment.
    course_id = _normalize_match_text(course_row.get("course_id"))
    ocr_text = _normalize_match_text(ocr_row.get("text"))
    title_tokens = _token_set(course_row.get("course_title"))
    ocr_tokens = _token_set(ocr_row.get("ocr_course_name") or ocr_row.get("text"))

    if course_id and course_id in ocr_text and score >= 0.30:
        return True

    if title_tokens and ocr_tokens and len(title_tokens & ocr_tokens) >= 2 and score >= 0.32:
        return True

    return False


def _attach_ocr_visual_evidence_to_course_rows(
    rows: list[dict[str, Any]],
    ocr_visual_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach OCR visual-row evidence to existing Document AI course rows.

    This is additive only. It does not alter course_id, course_title, course_mark,
    credits, term values, counts, or row inclusion.
    """
    if not rows or not ocr_visual_rows:
        return rows

    attached = 0

    for row in rows:
        best, score = _best_ocr_visual_row_for_course(row, ocr_visual_rows)
        if not _should_attach_ocr_visual_row(row, best, score):
            continue

        row["document_ai_ocr_page_number"] = best.get("page_number")
        row["document_ai_ocr_column"] = best.get("column")
        row["document_ai_ocr_row_bbox"] = best.get("row_bbox")
        row["document_ai_ocr_raw_word_bbox"] = best.get("raw_word_bbox")
        row["document_ai_ocr_row_text"] = best.get("text")
        row["document_ai_ocr_course_id"] = best.get("ocr_course_id")
        row["document_ai_ocr_course_title"] = best.get("ocr_course_name")
        row["document_ai_ocr_grade"] = best.get("ocr_grade")
        row["document_ai_ocr_credit_attempted"] = best.get("ocr_credit_attempted")
        row["document_ai_ocr_credit_completed"] = best.get("ocr_credit_completed")
        row["document_ai_ocr_section_grade"] = best.get("ocr_section_grade")
        row["document_ai_ocr_section_month"] = best.get("ocr_section_month")
        row["document_ai_ocr_section_year"] = best.get("ocr_section_year")
        row["document_ai_ocr_section_label"] = best.get("ocr_section_label")
        row["document_ai_ocr_section_source"] = best.get("ocr_section_source")
        row["document_ai_ocr_visual_row_index"] = best.get("ocr_visual_row_index")
        row["document_ai_ocr_alignment_key"] = best.get("ocr_alignment_key")
        row["document_ai_ocr_match_score"] = score
        row["document_ai_ocr_source"] = best.get("ocr_source")
        attached += 1

    if ocr_visual_rows:
        print(
            "[DocumentAI OCR VISUAL EVIDENCE] "
            f"course_rows={len(rows)}, "
            f"ocr_visual_rows={len(ocr_visual_rows)}, "
            f"attached={attached}"
        )

    return rows


def _drop_prefix_variant_duplicates(course_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Drop a course read as a BARE number when the SAME number also appears WITH
    a letter prefix in the same term.

    The OCR sometimes loses a course's letter prefix (e.g. "N 3651" -> "3651"),
    producing a phantom duplicate row and an over-count. A real course keeps its
    prefix, so a bare-number twin of an already-prefixed course in the same term
    is an OCR artifact, not a second enrollment. Numeric-only course ids with no
    prefixed twin are left untouched.
    """
    def _number(cid: str) -> str | None:
        m = re.search(r"\d+", cid)
        return m.group(0) if m else None

    def _has_prefix(cid: str) -> bool:
        return bool(re.match(r"^[A-Za-z]", cid.strip()))

    def _term(row: Dict[str, str]) -> tuple:
        return (
            str(row.get("term_year") or ""),
            str(row.get("term_month") or ""),
            str(row.get("term_grade") or ""),
        )

    prefixed_numbers_by_term: dict[tuple, set] = {}
    for row in course_rows:
        cid = str(row.get("course_id") or "").strip()
        if cid and _has_prefix(cid):
            n = _number(cid)
            if n:
                prefixed_numbers_by_term.setdefault(_term(row), set()).add(n)

    out: List[Dict[str, str]] = []
    for row in course_rows:
        cid = str(row.get("course_id") or "").strip()
        if cid and not _has_prefix(cid):
            n = _number(cid)
            if n and n in prefixed_numbers_by_term.get(_term(row), set()):
                continue  # bare-number OCR duplicate of a prefixed course
        out.append(row)
    return out


class DocumentAIService:
    def __init__(self, project_id: str, location: str, processor_id: str):
        if documentai is None:
            raise RuntimeError("google-cloud-documentai is not installed.")
        self._client = documentai.DocumentProcessorServiceClient()
        self._name = self._client.processor_path(project_id, location, processor_id)

    def process_pdf(self, content: bytes) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        content, mime_type = _enhance_pdf_for_ocr(content)
        raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
        request = documentai.ProcessRequest(name=self._name, raw_document=raw_document)
        result = _process_with_retry(self._client, request)
        return self._parse_result(result)

    def process_gcs_document(self, gcs_uri: str) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        # Download the PDF so we can apply contrast enhancement before processing
        try:
            from google.cloud import storage as gcs_storage
            bucket_name, _, blob_name = gcs_uri[len("gs://"):].partition("/")
            content = gcs_storage.Client().bucket(bucket_name).blob(blob_name).download_as_bytes()
            return self.process_pdf(content)
        except Exception:
            pass
        gcs_doc = documentai.GcsDocument(gcs_uri=gcs_uri, mime_type="application/pdf")
        request = documentai.ProcessRequest(name=self._name, gcs_document=gcs_doc)
        result = _process_with_retry(self._client, request)
        return self._parse_result(result)

    def _parse_result(self, result) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        doc = result.document

        header = self._collect_header(doc)
        course_rows: List[Dict[str, str]] = []
        for ent in doc.entities:
            ent_type = getattr(ent, "type_", "") or ""
            et = ent_type.lower()
            # treat any entity with 'term' or 'sem' in its type as a term-like container
            if "term" in et or "sem" in et or "semester" in et:
                course_rows.extend(self._flatten_term_or_sem(ent, doc, header))
        # If entity-based extraction produced few or no courses, try a text-based fallback
        try:
            doc_text = getattr(doc, 'text', '') or ''
        except Exception:
            doc_text = ''
        if (not course_rows or len(course_rows) < 5) and doc_text:
            fb = self._fallback_extract_courses_from_text(doc_text, header)
            # only use fallback when it produces something useful
            if fb:
                course_rows = fb

        # Extract GPAs from raw text (LBUSD GPA SUMMARY section)
        if doc_text:
            self._extract_gpas_from_text(doc_text, header)

        # Build full OCR visual-row evidence from the Document AI page layout.
        # This is additive only: it does not change course IDs, titles, grades,
        # credits, term values, row counts, or status decisions.
        ocr_visual_rows = _extract_document_ai_ocr_visual_rows(doc)
        if ocr_visual_rows:
            # Private in-memory metadata for downstream services. Persistence ignores
            # unknown/underscore keys, so no DB migration is required.
            header["_document_ai_ocr_visual_rows"] = ocr_visual_rows
            header["_document_ai_ocr_visual_rows_count"] = str(len(ocr_visual_rows))
            course_rows = _attach_ocr_visual_evidence_to_course_rows(course_rows, ocr_visual_rows)

        # Remove OCR prefix-drop duplicates (e.g. a phantom bare "3651" when the
        # real "N 3651" is already present in the same term). This is the one
        # safe, unambiguous Doc AI over-count to fix here.
        course_rows = _drop_prefix_variant_duplicates(course_rows)

        # Add Document AI row/column/block sequence metadata after all rows are
        # collected. Keeps extraction values intact while giving reconciliation a
        # stable visual order/alignment signal.
        course_rows = _attach_document_ai_sequence_metadata(course_rows, header)

        return header, course_rows

    def _extract_gpas_from_text(self, doc_text: str, header: Dict[str, str]) -> None:
        """Parse GPA values from raw document text (e.g., LBUSD GPA SUMMARY section)."""
        lines = doc_text.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Pattern: "4.00 University GPA" - value followed by label
            m = re.match(r'^([\d,\.]+)\s+University\s+GPA', stripped, re.IGNORECASE)
            if m and not header.get('university_gpa'):
                header['university_gpa'] = m.group(1).replace(',', '.')
                continue
            # Look for "ACA GPA Course" label, value is typically 2 lines after
            if re.search(r'ACA\s+GPA\s+Course', stripped, re.IGNORECASE):
                # scan next few lines for a numeric value
                for j in range(i + 1, min(i + 4, len(lines))):
                    nline = lines[j].strip()
                    nm = re.match(r'^([\d,\.]+)$', nline)
                    if nm and not header.get('aca_gpa_course'):
                        header['aca_gpa_course'] = nm.group(1).replace(',', '.')
                        break
            # Look for "Total GPA Course" label, value after
            if re.search(r'Total\s+GPA\s+Course', stripped, re.IGNORECASE):
                for j in range(i + 1, min(i + 4, len(lines))):
                    nline = lines[j].strip()
                    # skip lines that are labels
                    if re.search(r'[a-zA-Z]{3,}', nline) and not re.match(r'^[\d,\.]+$', nline):
                        continue
                    nm = re.match(r'^([\d,\.]+)', nline)
                    if nm and not header.get('total_gpa'):
                        header['total_gpa'] = nm.group(1).replace(',', '.')
                        break

    def _fallback_extract_courses_from_text(self, doc_text: str, header: Dict[str, str]) -> List[Dict[str, str]]:
        """Very tolerant fallback: scan document text lines for course-like rows.

        This is used only when structured course entities are missing or sparse.
        It uses heuristics: look for lines containing a letter grade token and numeric credits
        and try to split code/title/credits/grade out of the line.
        """
        rows: List[Dict[str, str]] = []
        grade_re = re.compile(r"\b([A-F][+-]?|P|Pass|Fail|NP)\b", re.IGNORECASE)
        credit_ratio_re = re.compile(r"(\d+[\.,]?\d*\s*[\-/\\]\s*\d+[\.,]?\d*)")
        credit_single_re = re.compile(r"\b(\d+[\.,]?\d*)\b")
        lines = [l.strip() for l in doc_text.splitlines() if l.strip()]
        # Limit window to avoid grabbing header lines: look for lines with grade tokens
        for i, line in enumerate(lines):
            # skip lines that look like headers
            if len(line) < 3:
                continue
            gm = grade_re.search(line)
            if not gm:
                continue
            grade = gm.group(1).upper()
            left = line[: gm.start()].strip()
            right = line[gm.end():].strip()
            # try to find credit ratio in left or right
            raw_ratio = None
            attempted = None
            completed = None
            mratio = credit_ratio_re.search(left) or credit_ratio_re.search(right)
            if mratio:
                raw_ratio = mratio.group(1)
                a, b, _ = _normalize_ratio(raw_ratio)
                attempted, completed = a, b
                # remove ratio from left text
                left = left.replace(mratio.group(1), "").strip()
            else:
                # try single numeric credits near the grade
                mnum = credit_single_re.findall(left)
                if mnum:
                    # take last numeric token as credit
                    val = mnum[-1]
                    attempted = completed = _normalize_scalar_number(val)
                    left = left[: left.rfind(val)].strip() if left.rfind(val) != -1 else left

            # try to find a leading course code
            course_id = None
            mcode = re.match(r"^([A-Za-z]?\s*\d{1,6})\b[\s\-:\.]*(.*)$", left)
            if mcode:
                course_id = mcode.group(1).replace('\n', ' ').strip()
                title = (mcode.group(2) or '').strip()
            else:
                # if no clear code, try to split by double spaces (common column gap) or multiple spaces
                parts = re.split(r"\s{2,}|\t", left)
                if len(parts) >= 2:
                    # assume first part is code or short title
                    course_id = parts[0].strip()
                    title = " ".join(p.strip() for p in parts[1:]).strip()
                else:
                    title = left

            # fallback title from right side if title is empty
            if not title:
                title = right or title

            # normalize credits to numeric when possible
            if attempted is None and completed is None and raw_ratio is None:
                # look for immediate numbers in the line
                nums = credit_single_re.findall(line)
                if nums:
                    val = nums[-1]
                    attempted = completed = _normalize_scalar_number(val)

            row = {
                'course_id': course_id or '',
                'course_title': title or '',
                'course_mark': grade or '',
                'credit_attempted': attempted,
                'credit_completed': completed,
                'raw_credit_ratio': raw_ratio,
                'term_school_name': header.get('student_school') or header.get('school') or '',
                'term_grade': header.get('student_Grade') or header.get('grade') or '',
                'term_month': '',
                'term_year': '',
                'total_credit_attempted': None,
                'total_credit_completed': None,
                'total_gpa': None,
                'term_gpa': None,
                'student_external_id': header.get('student_id', ''),
                'student_name': header.get('student_name', ''),
                'student_school': header.get('student_school', ''),
            }
            rows.append(row)
        return rows

    # ----------------------
    # Parsing helpers
    # ----------------------
    def _collect_header(self, doc: Any) -> Dict[str, str]:
        header: Dict[str, str] = {}
        for ent in doc.entities:
            t = getattr(ent, "type_", "") or ""
            t_lower = t.lower()
            # skip term/course entities from header
            if any(x in t_lower for x in ("term", "course", "sem", "semester")):
                continue
            txt = _get_text(ent)
            if not txt:
                continue
            # Normalize known aliases to canonical header keys
            alias_map = {
                'studentName': 'student_name',
                'student_name': 'student_name',
                'studentID': 'student_id',
                'student_id': 'student_id',
                'student_school': 'student_school',
                'school': 'student_school',
                'school_name': 'student_school',
                'SchoolName': 'student_school',
                'schoolName': 'student_school',
                'school_Name': 'student_school',
                'student_cumulative_GPA': 'student_cumulative_GPA',
                'student_dob': 'student_dob',
                'student_enter_date': 'student_enter_date',
                'student_graduation_date': 'student_graduation_date',
                'student_Grade': 'student_Grade',
                # extra aliases
                'state': 'state',
                'student_state': 'state',
                'state_id': 'state_id',
                'student_state_id': 'state_id',
                'gender': 'gender',
                'student_gender': 'gender',
                'total_units': 'total_units_earned',
                'total_units_earned': 'total_units_earned',
            }
            # additional header aliases likely to appear in Document AI outputs
            extra = {
                'cumulative_gpa': 'student_cumulative_GPA',
                'cumulativeGPA': 'student_cumulative_GPA',
                'overall_gpa': 'student_cumulative_GPA',
                'total_gpa': 'student_cumulative_GPA',
                'totalGPA': 'student_cumulative_GPA',
                'Student_total_GPA': 'total_gpa',
                'student_total_gpa': 'total_gpa',
                'StudentTotalGPA': 'total_gpa',
                'TotalUnitsEarned': 'total_units_earned',
                'totalunitsearned': 'total_units_earned',
                'student_Home_address': 'home_address',
                'student_home_address': 'home_address',
                'home_address': 'home_address',
                'university_gpa': 'university_gpa',
                'universityGPA': 'university_gpa',
                'University_GPA': 'university_gpa',
                'aca_gpa_course': 'aca_gpa_course',
                'aca_gpa': 'aca_gpa_course',
                'academic_gpa': 'aca_gpa_course',
                'gpa': 'student_cumulative_GPA',
                'id': 'student_id',
                'student_number': 'student_id',
                'student_external_id': 'student_id',
                'external_id': 'student_id',
                'sex': 'gender',
                'birth_date': 'student_dob',
                'birthdate': 'student_dob',
                'date_of_birth': 'student_dob',
                # GPA variants
                'aca_gpa': 'aca_gpa_course',
                'academic_gpa': 'aca_gpa_course',
                'academicGPA': 'aca_gpa_course',
                'universityGPA': 'university_gpa',
                'total_gpa': 'total_gpa',
                'totalGPA': 'total_gpa',
                'overall_gpa': 'total_gpa',
                # LBUSD-specific variants (sometimes different labels are used)
                'lbusd_total_gpa': 'total_gpa',
                'lbusd_academic_gpa': 'aca_gpa_course',
                'lbusd_university_gpa': 'university_gpa',
                'lbusd_gpa': 'student_cumulative_GPA',
                # date/int variants
                'intake_date': 'student_enter_date',
                'admission_date': 'student_enter_date',
                'admit_date': 'student_enter_date',
                'grad_date': 'student_graduation_date',
                'graduationDate': 'student_graduation_date',
                # units/credits
                'total_units': 'total_units_earned',
                'totalCredits': 'total_units_earned',
                'units': 'total_units_earned',
                'units_earned': 'total_units_earned',
                # additional total units variants
                'total_credits': 'total_units_earned',
                'credits_total': 'total_units_earned',
                # state id variants
                'statecode': 'state_id',
                'state_id': 'state_id',
                'state id': 'state_id',
                'state-code': 'state_id',
                'st_id': 'state_id',
                # gender variants
                'm/f': 'gender',
                'sex': 'gender',
                'student_sex': 'gender',
            }
            alias_map.update(extra)
            # Case-insensitive alias lookup: try exact key, then lowercase
            t_norm = alias_map.get(t) or alias_map.get(t_lower) or alias_map.get(t.lower()) or t
            # If the entity text contains a label like 'Total GPA: 3.5', split and remap
            if t_norm == t:
                m = re.match(r"^\s*([A-Za-z0-9 _\-/]+)[:\-–]\s*(.+)$", txt)
                if m:
                    label = m.group(1).strip().lower().replace(" ", "_")
                    value = m.group(2).strip()
                    mapped_label = alias_map.get(label) or alias_map.get(label.lower())
                    if mapped_label:
                        t_norm = mapped_label
                        txt = value
            # additional tolerant mappings
            if t_norm == 'total_units_earned' and not header.get('total_units_earned'):
                # also accept 'student_total_units' or 'total_credits'
                header.setdefault('total_units_earned', header.get('total_units_earned') or header.get('student_total_units') or header.get('total_credits') or header.get('totalCredits'))
            header.setdefault(t_norm, txt)
            header.setdefault(t_norm, txt)
        # Common canonical keys presence
        for k in [
            "student_id",
            "student_name",
            "student_school",
            "student_cumulative_GPA",
            "student_dob",
            "student_enter_date",
            "student_graduation_date",
            "student_Grade",
        ]:
            header.setdefault(k, header.get(k) or "")
        return header

    def _parse_sem_grade_credits(self, val: str) -> tuple:
        """Parse St. Anthony sem values like 'A 5.00' or 'B 5,00' into (grade, credits)."""
        if not val:
            return None, None
        val = val.strip()
        # Pattern: "GRADE CREDITS" e.g. "A 5.00", "A+ 5,00", "B- 5.00"
        m = re.match(r"^([A-F][+-]?)\s+([\d,\.]+)$", val, re.IGNORECASE)
        if m:
            grade = m.group(1).upper()
            credits = _normalize_scalar_number(m.group(2))
            return grade, credits
        # Try just a grade letter
        m = re.match(r"^([A-F][+-]?)$", val, re.IGNORECASE)
        if m:
            return m.group(1).upper(), None
        return None, None

    def _flatten_term_or_sem(
        self,
        term_ent: Any,
        doc: Any,
        header: Dict[str, str],
    ) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []

        # Collect term-level fields into a dict
        term_data: Dict[str, str] = {}
        for prop in getattr(term_ent, "properties", []) or []:
            t = getattr(prop, "type_", "")
            txt = _get_text(prop)
            if not txt:
                continue
            term_data[t] = txt

        # ---- St. Anthony style: term -> sem (with sub-properties sem_1, sem_2, sem_Subjects) ----
        has_sem_children = any(
            getattr(p, "type_", "") == "sem"
            for p in getattr(term_ent, "properties", []) or []
        )
        if has_sem_children:
            return self._flatten_st_anthony_sems(term_ent, header, term_data)

        # ---- LBUSD / Mayfair style: term -> course ----
        for prop in getattr(term_ent, "properties", []) or []:
            if getattr(prop, "type_", "") != "course":
                continue
            course_ent = prop
            course_geometry = _extract_entity_geometry(course_ent)
            course: Dict[str, str] = {}
            for cprop in getattr(course_ent, "properties", []) or []:
                ctype = getattr(cprop, "type_", "")
                ctext = _get_text(cprop)
                if ctext:
                    # normalize common course property aliases
                    c_alias = {
                        # titles
                        'courseTitle': 'course_title',
                        'title': 'course_title',
                        'course_title': 'course_title',
                        'course_name': 'course_title',
                        'subject': 'course_title',
                        # ids
                        'course_id': 'course_id',
                        'courseCode': 'course_id',
                        'course_code': 'course_id',
                        'courseNumber': 'course_id',
                        'course_number': 'course_id',
                        'courseNo': 'course_id',
                        'course_no': 'course_id',
                        'crs_id': 'course_id',
                        'crs_code': 'course_id',
                        'crs_number': 'course_id',
                        'code': 'course_id',
                        'st_course_id': 'course_id',
                        'st_course_number': 'course_id',
                        # marks / grades
                        'course_mark': 'course_mark',
                        'mark': 'course_mark',
                        'grade': 'course_mark',
                        'letter': 'course_mark',
                        'letter_grade': 'course_mark',
                        'lg': 'course_mark',
                        'ltr_grade': 'course_mark',
                        'final': 'course_mark',
                        'final_mark': 'course_mark',
                        'course_grade': 'course_mark',
                        # semester marks
                        'sem_1': 'sem_1',
                        'sem1': 'sem_1',
                        'semester1': 'sem_1',
                        'sem_2': 'sem_2',
                        'sem2': 'sem_2',
                        'semester2': 'sem_2',
                        'sem_S_SCH': 'sem_S_SCH',
                        'credits': 'credits',
                        'marks': 'course_mark',
                        'score': 'course_mark',
                        'percent': 'course_mark',
                        'percentage': 'course_mark',
                        'mark_percentage': 'course_mark',
                        'course_transcript_abbrevs': 'course_title',
                        'course_title_short': 'course_title',
                        'course_credit_attempted_completed': 'course_credit_attempted_completed',
                        'credit_attempted': 'credit_attempted',
                        'credit_completed': 'credit_completed',
                        # school where course was taken (maps to crs_hs/term_school_name)
                        'school': 'term_school_name',
                        'course_school': 'term_school_name',
                        'crs_hs': 'term_school_name',
                        'taken_at': 'term_school_name',
                        # term / date / year aliases
                        'term': 'term_grade',
                        'term_grade': 'term_grade',
                        'term_year': 'term_year',
                        'year': 'term_year',
                        'term_month': 'term_month',
                        'month': 'term_month',
                        # term GPA alias
                        'term_gpa': 'term_gpa',
                        'semester_gpa': 'term_gpa',
                        'termGPA': 'term_gpa',
                    }
                    course[c_alias.get(ctype, ctype)] = ctext

            # Heuristic fallback: if core fields missing, try to extract from raw course text
            raw_bits = []
            # include course entity mention_text if available
            try:
                raw_bits.append(_get_text(course_ent))
            except Exception:
                pass
            for p in getattr(course_ent, 'properties', []) or []:
                raw_bits.append(_get_text(p))
            raw_text = ' '.join([b for b in raw_bits if b])
            if raw_text:
                if not course.get('course_title'):
                    # try to strip leading course code and trailing grade/credit tokens
                    rt = re.sub(r"\d+[\.,]?\d*\s*/\s*\d+[\.,]?\d*", "", raw_text)
                    rt = re.sub(r"\b\d+(?:\.\d+)?\b", "", rt)
                    rt = re.sub(r"[\|\-\–\:]{1,}", " ", rt)
                    rt = re.sub(r"\s+", " ", rt).strip()
                    mcode = re.match(r"^([A-Za-z]?\s*\d{1,5})\s+(.+)$", rt)
                    if mcode:
                        course['course_id'] = course.get('course_id') or mcode.group(1).replace('\n', ' ').strip()
                        course['course_title'] = mcode.group(2).strip()
                    else:
                        course['course_title'] = raw_text.strip()
                if not course.get('course_id') and not course.get('course_credit_attempted_completed') and not course.get('credit_attempted'):
                    # Only extract course_id from raw text if no credit data exists
                    # (to avoid misidentifying credit values like '5.00' as course codes)
                    m = re.search(r"([A-Za-z]?\s*\d{1,5})", raw_text)
                    if m:
                        course['course_id'] = m.group(1).replace('\n', ' ').strip()
                if not course.get('course_mark'):
                    gm = re.search(r"\b([A-F][\+\-]?|P|Pass|Fail|NP)\b", raw_text, re.IGNORECASE)
                    if gm:
                        course['course_mark'] = gm.group(1).upper()

            # parse credits: explicit fields preferred, fallback to combined ratio
            attempted = None
            completed = None
            raw_ratio = None
            if course.get("credit_attempted") or course.get("credit_completed"):
                attempted = _normalize_scalar_number(course.get("credit_attempted")) if course.get("credit_attempted") else None
                completed = _normalize_scalar_number(course.get("credit_completed")) if course.get("credit_completed") else None
            else:
                attempted, completed, raw_ratio = _normalize_ratio(course.get("course_credit_attempted_completed") or course.get("credits") or course.get("credits_ratio"))

            # Normalize the term context (grade level / month / year) so the Document AI
            # rows line up with Gemini's term context during reconciliation matching.
            # The raw_* values are kept so nothing is lost.
            raw_term_grade = term_data.get("term_grade", "") or term_data.get("grade", "") or term_data.get("term", "")
            raw_term_month = term_data.get("term_month", "") or term_data.get("month", "")
            raw_term_year = term_data.get("term_year", "") or term_data.get("sem_year", "") or term_data.get("year", "")
            normalized_term = _normalize_term_context(raw_term_grade, raw_term_month, raw_term_year)

            row: Dict[str, str] = {
                # course-level
                "course_id": (course.get("course_id", "") or "").replace("\n", " ").strip(),
                "course_title": (course.get("course_title", "") or "").replace("\n", " ").strip(),
                "course_mark": course.get("course_mark", ""),
                "mark_sem1": course.get("sem_1", ""),
                "mark_sem2": course.get("sem_2", ""),
                # credits
                "credits": course.get("sem_S_SCH", ""),
                "credit_attempted": attempted if attempted is not None else None,
                "credit_completed": completed if completed is not None else None,
                "raw_credit_ratio": raw_ratio,
                # term-level
                "term_school_name": term_data.get("term_SchoolName") or term_data.get("SchoolName", "") or term_data.get("school") or term_data.get("term_school") or term_data.get("termSchool"),
                "term_grade": normalized_term.get("term_grade") or raw_term_grade,
                "term_month": normalized_term.get("term_month") or raw_term_month,
                "term_year": normalized_term.get("term_year") or raw_term_year,
                "raw_term_grade": raw_term_grade,
                "raw_term_month": raw_term_month,
                "raw_term_year": raw_term_year,
                "total_credit_attempted": _normalize_scalar_number(term_data.get("total_creditAttempted") or term_data.get("total_credit_attempted") or term_data.get("totalAttempted")),
                "total_credit_completed": _normalize_scalar_number(term_data.get("total_credit_completed") or term_data.get("totalCreditCompleted") or term_data.get("total_completed")),
                # term/semester GPA
                "total_gpa": _normalize_scalar_number(term_data.get("total_GPA") or term_data.get("total_gpa") or term_data.get("term_gpa") or term_data.get("semester_gpa") or term_data.get("termGPA")),
                "term_gpa": _normalize_scalar_number(term_data.get("term_gpa") or term_data.get("total_GPA") or term_data.get("termGPA") or term_data.get("semester_gpa")),
            }

            # Split combined marks like "A A" or "B A" into sem1/sem2
            mark_str = row.get("course_mark", "")
            if mark_str and not row.get("mark_sem1") and not row.get("mark_sem2"):
                parts = re.findall(r"[A-F][+-]?", mark_str, re.IGNORECASE)
                if len(parts) == 2:
                    row["mark_sem1"] = parts[0].upper()
                    row["mark_sem2"] = parts[1].upper()
                    row["course_mark"] = parts[0].upper()  # use first as primary mark

            # Normalize term_year (e.g. "24-25" -> "2024") so it matches Gemini's
            # academic-year handling during reconciliation.
            ty = row.get("term_year", "")
            normalized_year = _normalize_academic_year(ty)
            if normalized_year:
                row["term_year"] = normalized_year

            # attach student-level reference info
            row["student_external_id"] = header.get("student_id", "")
            row["student_name"] = header.get("student_name", "")
            row["student_school"] = header.get("student_school", "")

            # attach Document AI visual geometry (additive; consumed only by
            # downstream reconciliation — does not alter any extraction values)
            if course_geometry:
                row["_geometry"] = course_geometry
                row["document_ai_page_number"] = course_geometry.get("page_number")
                row["document_ai_column"] = course_geometry.get("column")
                row["document_ai_row_bbox"] = course_geometry.get("row_bbox")
                row["document_ai_raw_word_bbox"] = course_geometry.get("raw_word_bbox")
                row["document_ai_geometry_source"] = course_geometry.get("geometry_source")

            rows.append(row)

        return rows

    def _flatten_st_anthony_sems(
        self,
        term_ent: Any,
        header: Dict[str, str],
        term_data: Dict[str, str],
    ) -> List[Dict[str, str]]:
        """Handle St. Anthony structure: term -> sem -> (sem_Subjects, sem_Grade, sem_Credit).
        Also supports legacy structure with sem_1/sem_2 fields as fallback.
        """
        rows: List[Dict[str, str]] = []
        term_school = term_data.get("SchoolName") or term_data.get("term_SchoolName") or ""
        term_year = term_data.get("sem_year") or term_data.get("term_year") or ""

        # Normalize term_year: "24-25" → "2024"
        if term_year and re.match(r"^\d{2}-\d{2}$", term_year):
            start_yr = int(term_year.split("-")[0])
            term_year = str(2000 + start_yr)

        # Track how many times each course title has appeared in this term so that
        # the second sem entry for the same course gets a different term_month,
        # making the dedup key unique and preventing the second row from being dropped.
        course_occurrence: Dict[str, int] = {}

        for prop in getattr(term_ent, "properties", []) or []:
            if getattr(prop, "type_", "") != "sem":
                continue

            sem_data: Dict[str, str] = {}
            for sp in getattr(prop, "properties", []) or []:
                stype = getattr(sp, "type_", "")
                stxt = _get_text(sp)
                if stxt:
                    sem_data[stype] = stxt

            course_title = sem_data.get("sem_Subjects") or sem_data.get("subject") or ""
            if not course_title:
                continue

            # Assign a unique sem number per occurrence of this course in the term
            course_occurrence[course_title] = course_occurrence.get(course_title, 0) + 1
            sem_number = course_occurrence[course_title]

            raw_grade_field = sem_data.get("sem_Grade", "")
            raw_credit_field = sem_data.get("sem_Credit", "")

            if raw_grade_field or raw_credit_field:
                grade = _extract_grade_only(raw_grade_field)
                credit_val = _extract_credit_only(raw_credit_field)
                if not grade:
                    # No parseable grade — skip this sem row entirely (in-progress or unrecognised format)
                    continue
                row: Dict[str, str] = {
                    "course_id": "",
                    "course_title": course_title,
                    "course_mark": grade,
                    "mark_sem1": grade,
                    "mark_sem2": "",
                    "credit_sem1": credit_val,
                    "credit_sem2": None,
                    "credits": "",
                    "credit_attempted": credit_val,
                    "credit_completed": credit_val,
                    "raw_credit_ratio": None,
                    "term_school_name": term_school,
                    "term_grade": "",
                    "term_month": sem_number,
                    "term_year": term_year,
                    "total_credit_attempted": None,
                    "total_credit_completed": None,
                    "total_gpa": None,
                    "term_gpa": None,
                    "student_external_id": header.get("student_id", ""),
                    "student_name": header.get("student_name", ""),
                    "student_school": header.get("student_school", ""),
                }
                rows.append(row)
            else:
                # Legacy fallback: sem_1 / sem_2 each contain "GRADE CREDITS"
                sem1_grade, sem1_credits = self._parse_sem_grade_credits(sem_data.get("sem_1"))
                sem2_grade, sem2_credits = self._parse_sem_grade_credits(sem_data.get("sem_2"))
                course_mark = sem1_grade or sem2_grade or ""
                if not course_mark:
                    continue
                credits_val = sem1_credits or sem2_credits
                row = {
                    "course_id": "",
                    "course_title": course_title,
                    "course_mark": course_mark,
                    "mark_sem1": sem_data.get("sem_1", ""),
                    "mark_sem2": sem_data.get("sem_2", ""),
                    "credit_sem1": sem1_credits,
                    "credit_sem2": sem2_credits,
                    "credits": "",
                    "credit_attempted": credits_val,
                    "credit_completed": credits_val,
                    "raw_credit_ratio": None,
                    "term_school_name": term_school,
                    "term_grade": "",
                    "term_month": sem_number,
                    "term_year": term_year,
                    "total_credit_attempted": None,
                    "total_credit_completed": None,
                    "total_gpa": None,
                    "term_gpa": None,
                    "student_external_id": header.get("student_id", ""),
                    "student_name": header.get("student_name", ""),
                    "student_school": header.get("student_school", ""),
                }
                rows.append(row)

        return rows
