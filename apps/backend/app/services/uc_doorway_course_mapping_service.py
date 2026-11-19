from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from difflib import SequenceMatcher
from threading import Lock, Thread
import asyncio
import logging
import os
import traceback
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import func, select, exists, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db import get_session
from app.models import (
    Course_details,
    CourseDetailMappingUcDoorwayCourses,
    PipelineJob,
    Students,
    UCDoorwayCoursesSearchIndex,
    UCDoorwayCourses,
    UCDoorwaySchools,
)

import re


def _make_thread_engine():
    """
    Create a fresh async engine using NullPool for background-thread use.

    Background threads call asyncio.run() which creates a new event loop;
    the shared asyncpg pool is bound to uvicorn's loop and cannot be reused.
    NullPool means no connection is cached — a fresh TCP connection is made
    for every `async with session_factory() as session:` block, preventing
    both the event-loop mismatch and idle-connection-drop issues on long runs.
    """
    from sqlalchemy.pool import NullPool
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/transcripts",
    )
    engine = create_async_engine(db_url, poolclass=NullPool)
    return engine


@asynccontextmanager
async def _thread_session(factory: async_sessionmaker | None = None):
    """Yield one fresh session from a NullPool engine."""
    engine = None
    if factory is None:
        engine = _make_thread_engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        if engine is not None:
            await engine.dispose()


# --------------------------------------------------
# In-process queue state
# --------------------------------------------------
queue_lock = Lock()

job_queue = deque()
is_running = False
current_job_id = None
last_finished_job_id = None
last_error = None
last_run_status = "idle"   # idle | running | success | failed
started_at = None
finished_at = None
progress_stage = None
progress_percent = 0

# small cache to avoid repeating school lookup for same school name
_school_cache: dict[str, list[int]] = {}


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


# Matches trailing semester/term suffixes like " A,B", " 1-2", " A/B".
# Used to produce a suffix-free fallback title for matching without altering stored data.
_SEMESTER_SUFFIX_RE = re.compile(r'\s+[A-Za-z0-9]{1,3}[,\-/][A-Za-z0-9]{1,3}$')

def strip_semester_suffix(value: str | None) -> str:
    if not value:
        return ''
    return _SEMESTER_SUFFIX_RE.sub('', value.strip())


def normalize_course_title_input(value: str | None) -> str:
    if not value:
        return ""

    text = str(value).lower().strip()

    # normalize & first
    text = text.replace("&", " and ")

    # remove all brackets/parens, but keep text inside
    text = text.replace("(", " ").replace(")", " ")
    text = text.replace("[", " ").replace("]", " ")
    text = text.replace("{", " ").replace("}", " ")

    # convert every non-alphanumeric to space
    text = re.sub(r"[^a-z0-9]+", " ", text)

    # collapse spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text

def canonical_title_key_input(value: str | None) -> str:
    text = normalize_course_title_input(value)
    if not text:
        return ""

    words = [w for w in text.split() if w and w != "and"]
    words.sort()
    return " ".join(words)


def compact_title_key_input(value: str | None) -> str:
    return normalize_course_title_input(value).replace(" ", "")


async def match_by_normalized_title_sql(
    db: AsyncSession,
    course_title: str,
    school_ids: list[int] | None = None,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    canonical_key = canonical_title_key_input(course_title)
    compact_key = compact_title_key_input(course_title)

    if not canonical_key and not compact_key:
        return []

    stmt = select(UCDoorwayCourses)

    if school_ids:
        stmt = stmt.where(UCDoorwayCourses.hs_id.in_(school_ids))

    if academic_years:
        stmt = stmt.where(UCDoorwayCourses.crs_academic_year.in_(academic_years))

    stmt = stmt.where(
        or_(
            func.canonical_title_key(UCDoorwayCourses.crs_description) == canonical_key,
            func.compact_title_key(UCDoorwayCourses.crs_description) == compact_key,
        )
    )

    rows = (await db.execute(stmt)).scalars().all()
    return rows

def normalize_course_code(value: str | None) -> str:
    """
    Extract actual course code:
    Removes prefixes like 'P ', 'HP ', 'N ' and keeps the rest.

    ex:
        "P 1403"      -> "1403"
        "HP 3053"     -> "3053"
        "N 3635"      -> "3635"
        "P 3865APEX"  -> "3865apex"
    """
    if not value:
        return ""

    value = str(value).strip()

    # Remove leading letters + space
    cleaned = re.sub(r"^[A-Za-z]+\s+", "", value)

    return cleaned.lower()



def get_academic_year_candidates(value) -> list[str]:
    """
    Return possible academic-year candidates, current year first.

    For a course labelled year=2022 we try "2022-23" first (fall of that
    calendar year), then fall back to "2021-22" (spring of that year).

    Examples:
        2022      -> ["2022-23", "2021-22"]
        "2022"    -> ["2022-23", "2021-22"]
        "2022-23" -> ["2022-23"]
    """
    if value is None:
        return []

    raw = str(value).strip()
    if not raw:
        return []

    if "-" in raw:
        return [raw]

    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 4:
        year = int(digits)
        current_year_fmt  = f"{year}-{str((year + 1) % 100).zfill(2)}"
        previous_year_fmt = f"{year - 1}-{str(year % 100).zfill(2)}"
        return [current_year_fmt, previous_year_fmt]

    return [raw]


def similarity(a: str | None, b: str | None) -> float:
    a_n = normalize_text(a)
    b_n = normalize_text(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


async def _update_job_status(
    job_id: str,
    status: str,
    error: str | None = None,
    factory: async_sessionmaker | None = None,
) -> None:
    async with _thread_session(factory) as session:
        try:
            job = (
                await session.execute(
                    select(PipelineJob).where(PipelineJob.id == UUID(job_id))
                )
            ).scalar_one_or_none()

            if job:
                job.status = status
                job.error = error
                await session.commit()
            else:
                await session.rollback()

        except Exception:
            await session.rollback()
            raise


async def _get_or_create_mapping_row(
    db: AsyncSession,
    course_details_id: int,
) -> CourseDetailMappingUcDoorwayCourses:
    result = await db.execute(
        select(CourseDetailMappingUcDoorwayCourses).where(
            CourseDetailMappingUcDoorwayCourses.course_details_id == course_details_id
        )
    )
    mapping_row = result.scalar_one_or_none()

    if mapping_row is None:
        mapping_row = CourseDetailMappingUcDoorwayCourses(
            course_details_id=course_details_id,
        )
        db.add(mapping_row)

    return mapping_row


# --------------------------------------------------
# Matching helpers
# --------------------------------------------------

async def match_by_exact_course_description(
    db: AsyncSession,
    school_ids: list[int],
    course_title: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        f"[UC_DOORWAY_MAPPING] match_by_exact_course_description: "
        f"school_ids={school_ids}, title='{course_title}', years={academic_years}"
    )

    stmt = select(UCDoorwayCourses).where(
        UCDoorwayCourses.hs_id.in_(school_ids),
        func.lower(UCDoorwayCourses.crs_description) == normalize_text(course_title),
    )

    if academic_years:
        stmt = stmt.where(UCDoorwayCourses.crs_academic_year.in_(academic_years))

    rows = (await db.execute(stmt)).scalars().all()
    logger.debug(f"[UC_DOORWAY_MAPPING] match_by_exact_course_description results: {len(rows)}")
    return rows

async def match_by_exact_course_description_without_school(
    db: AsyncSession,
    course_title: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        f"[UC_DOORWAY_MAPPING] match_by_exact_course_description_without_school: "
        f"title='{course_title}', years={academic_years}"
    )

    stmt = select(UCDoorwayCourses).where(
        func.lower(UCDoorwayCourses.crs_description) == normalize_text(course_title),
    )

    if academic_years:
        stmt = stmt.where(UCDoorwayCourses.crs_academic_year.in_(academic_years))

    rows = (await db.execute(stmt)).scalars().all()
    logger.debug(
        "[UC_DOORWAY_MAPPING] "
        f"match_by_exact_course_description_without_school results: {len(rows)}"
    )
    return rows


async def match_by_exact_desc_to_transcript_abbrev_without_school(
    db: AsyncSession,
    course_title: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        "[UC_DOORWAY_MAPPING] "
        f"match_by_exact_desc_to_transcript_abbrev_without_school: "
        f"title='{course_title}', years={academic_years}"
    )

    stmt = (
        select(UCDoorwayCourses)
        .join(
            UCDoorwayCoursesSearchIndex,
            UCDoorwayCoursesSearchIndex.crs_id == UCDoorwayCourses.id,
        )
        .where(
            UCDoorwayCoursesSearchIndex.search_type == "crs_transcript_abbrevs",
            func.lower(UCDoorwayCoursesSearchIndex.search_value) == normalize_text(course_title),
        )
    )

    if academic_years:
        stmt = stmt.where(
            UCDoorwayCoursesSearchIndex.crs_academic_year.in_(academic_years)
        )

    rows = (await db.execute(stmt)).scalars().all()
    logger.debug(
        "[UC_DOORWAY_MAPPING] "
        f"match_by_exact_desc_to_transcript_abbrev_without_school results: {len(rows)}"
    )
    return rows

async def get_school_ids(db: AsyncSession, school_name: str) -> list[int]:
    school_name_norm = normalize_text(school_name)

    if not school_name_norm:
        return []

    if school_name_norm in _school_cache:
        logger.debug(
            f"[UC_DOORWAY_MAPPING] School cache hit: "
            f"'{school_name}' -> {_school_cache[school_name_norm]}"
        )
        return _school_cache[school_name_norm]

    exact_ids = (
        await db.execute(
            select(UCDoorwaySchools.id).where(
                func.lower(UCDoorwaySchools.hs_name) == school_name_norm
            )
        )
    ).scalars().all()

    if exact_ids:
        _school_cache[school_name_norm] = exact_ids
        logger.debug(
            f"[UC_DOORWAY_MAPPING] School exact match: "
            f"'{school_name}' -> {exact_ids}"
        )
        return exact_ids

    partial_ids = (
        await db.execute(
            select(UCDoorwaySchools.id).where(
                func.lower(UCDoorwaySchools.hs_name).like(f"%{school_name_norm}%")
            )
        )
    ).scalars().all()

    _school_cache[school_name_norm] = partial_ids
    logger.debug(
        f"[UC_DOORWAY_MAPPING] School partial match: "
        f"'{school_name}' -> {partial_ids}"
    )
    return partial_ids


async def match_by_local_code(
    db: AsyncSession,
    school_ids: list[int],
    course_code: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        f"[UC_DOORWAY_MAPPING] match_by_local_code: "
        f"school_ids={school_ids}, course_code={course_code}, years={academic_years}"
    )

    logger.debug("course codesss")
    logger.debug(normalize_course_code(course_code))

    stmt = (
        select(UCDoorwayCourses)
        .join(
            UCDoorwayCoursesSearchIndex,
            UCDoorwayCoursesSearchIndex.crs_id == UCDoorwayCourses.id,
        )
        .where(
            UCDoorwayCoursesSearchIndex.hs_id.in_(school_ids),
            UCDoorwayCoursesSearchIndex.search_type == "crs_local_codes",
            func.lower(UCDoorwayCoursesSearchIndex.search_value) == normalize_course_code(course_code),
        )
    )

    if academic_years:
        stmt = stmt.where(
            UCDoorwayCoursesSearchIndex.crs_academic_year.in_(academic_years)
        )

    rows = (await db.execute(stmt)).scalars().all()
    logger.debug(f"[UC_DOORWAY_MAPPING] match_by_local_code results: {len(rows)}")
    return rows


async def match_by_abbrev(
    db: AsyncSession,
    school_ids: list[int],
    abbrev_value: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        f"[UC_DOORWAY_MAPPING] match_by_abbrev_exact: "
        f"school_ids={school_ids}, title='{abbrev_value}', years={academic_years}"
    )

    stmt = (
        select(UCDoorwayCourses)
        .join(
            UCDoorwayCoursesSearchIndex,
            UCDoorwayCoursesSearchIndex.crs_id == UCDoorwayCourses.id,
        )
        .where(
            UCDoorwayCoursesSearchIndex.hs_id.in_(school_ids),
            UCDoorwayCoursesSearchIndex.search_type == "crs_transcript_abbrevs",
            func.lower(UCDoorwayCoursesSearchIndex.search_value) == normalize_text(abbrev_value),
        )
    )

    if academic_years:
        stmt = stmt.where(
            UCDoorwayCoursesSearchIndex.crs_academic_year.in_(academic_years)
        )

    rows = (await db.execute(stmt)).scalars().all()
    logger.debug(f"[UC_DOORWAY_MAPPING] match_by_abbrev_exact results: {len(rows)}")
    return rows


async def match_by_fuzzy_title(
    db: AsyncSession,
    school_ids: list[int],
    title: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        f"[UC_DOORWAY_MAPPING] match_by_fuzzy_title: "
        f"school_ids={school_ids}, title='{title}', years={academic_years}"
    )

    title_norm = normalize_text(title)
    if not title_norm:
        return []

    stmt = select(UCDoorwayCourses).where(UCDoorwayCourses.hs_id.in_(school_ids))

    if academic_years:
        stmt = stmt.where(UCDoorwayCourses.crs_academic_year.in_(academic_years))

    candidates = (await db.execute(stmt)).scalars().all()

    # Run CPU-intensive fuzzy scoring in a thread so the event loop stays free
    def _score(candidates):
        scored = []
        for row in candidates:
            score = similarity(title_norm, row.crs_description)
            if score >= 0.65:
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _, row in scored]

    rows = await asyncio.to_thread(_score, candidates)
    logger.debug(f"[UC_DOORWAY_MAPPING] match_by_fuzzy_title results: {len(rows)}")
    return rows


async def match_by_local_code_without_school(
    db: AsyncSession,
    course_code: str,
    academic_years: list[str] | None = None,
) -> list[UCDoorwayCourses]:
    logger.debug(
        f"[UC_DOORWAY_MAPPING] match_by_local_code_without_school: "
        f"course_code={course_code}, years={academic_years}"
    )

    stmt = (
        select(UCDoorwayCourses)
        .join(
            UCDoorwayCoursesSearchIndex,
            UCDoorwayCoursesSearchIndex.crs_id == UCDoorwayCourses.id,
        )
        .where(
            UCDoorwayCoursesSearchIndex.search_type == "crs_local_codes",
            func.lower(UCDoorwayCoursesSearchIndex.search_value) == normalize_course_code(course_code),
        )
    )

    if academic_years:
        stmt = stmt.where(
            UCDoorwayCoursesSearchIndex.crs_academic_year.in_(academic_years)
        )

    rows = (await db.execute(stmt)).scalars().all()
    logger.debug(f"[UC_DOORWAY_MAPPING] match_by_local_code_without_school results: {len(rows)}")
    return rows


async def get_course_abbrev_map(
    db: AsyncSession,
    course_ids: list[int],
    academic_years: list[str] | None = None,
) -> dict[int, list[str]]:
    if not course_ids:
        return {}

    stmt = (
        select(
            UCDoorwayCoursesSearchIndex.crs_id,
            UCDoorwayCoursesSearchIndex.search_value,
        )
        .where(
            UCDoorwayCoursesSearchIndex.crs_id.in_(course_ids),
            UCDoorwayCoursesSearchIndex.search_type == "crs_transcript_abbrevs",
        )
    )

    if academic_years:
        stmt = stmt.where(
            UCDoorwayCoursesSearchIndex.crs_academic_year.in_(academic_years)
        )

    rows = (await db.execute(stmt)).all()
    logger.debug(
        f"[UC_DOORWAY_MAPPING] get_course_abbrev_map: "
        f"course_ids={len(course_ids)}, rows={len(rows)}"
    )

    result: dict[int, list[str]] = {}
    for crs_id, search_value in rows:
        result.setdefault(crs_id, []).append(search_value or "")

    return result



async def choose_best_general_code_match(
    db: AsyncSession,
    matches: list[UCDoorwayCourses],
    course_title: str | None,
    academic_years: list[str] | None = None,
) -> UCDoorwayCourses | None:
    """
    General-code fallback:
    1. local code already matched
    2. validate those candidates by EXACT course title match only
    """
    logger.debug(
        f"[UC_DOORWAY_MAPPING] choose_best_general_code_match: "
        f"matches={len(matches)}, title='{course_title}', years={academic_years}"
    )

    if not matches:
        return None

    if not course_title:
        logger.debug("[UC_DOORWAY_MAPPING] No course title; no exact title validation possible")
        return None

    title_norm = normalize_text(course_title)

    for row in matches:
        if normalize_text(row.crs_description) == title_norm:
            logger.debug(
                f"[UC_DOORWAY_MAPPING] Exact general-code title match found: "
                f"uc_course_id={row.id}"
            )
            return row

    logger.debug("[UC_DOORWAY_MAPPING] No validated exact general-code title match found")
    return None

def choose_best_match(matches: list[UCDoorwayCourses]) -> UCDoorwayCourses | None:
    return matches[0] if matches else None


async def apply_match(
    db: AsyncSession,
    course_row: Course_details,
    uc_row: UCDoorwayCourses,
    status: str,
) -> None:
    mapping_row = await _get_or_create_mapping_row(db, course_row.id)
    mapping_row.uc_doorway_courses_id = uc_row.id
    mapping_row.mapping_status = status

    logger.debug(
        f"[UC_DOORWAY_MAPPING] APPLY MATCH: "
        f"course_id={course_row.id}, uc_course_id={uc_row.id}, status={status}"
    )


async def clear_match(
    db: AsyncSession,
    course_row: Course_details,
    status: str,
) -> None:
    mapping_row = await _get_or_create_mapping_row(db, course_row.id)
    mapping_row.uc_doorway_courses_id = None
    mapping_row.mapping_status = status

    logger.debug(
        f"[UC_DOORWAY_MAPPING] CLEAR MATCH: "
        f"course_id={course_row.id}, status={status}"
    )


# --------------------------------------------------
# Core processing
# --------------------------------------------------
async def process_single_course(db: AsyncSession, course_row: Course_details) -> None:
    school_name = course_row.crs_hs
    course_code = normalize_course_code(course_row.crs_id)
    course_title = course_row.crs_description
    academic_years = get_academic_year_candidates(course_row.crs_year)

    logger.debug(
        f"[UC_DOORWAY_MAPPING] START course_id={course_row.id}, "
        f"school='{school_name}', code='{course_code}', "
        f"title='{course_title}', years={academic_years}"
    )

    school_ids: list[int] = []
    school_found = False

    if school_name:
        school_ids = await get_school_ids(db, school_name)
        school_found = len(school_ids) > 0

    logger.debug(
        f"[UC_DOORWAY_MAPPING] School lookup completed: "
        f"school_found={school_found}, school_ids={school_ids}"
    )


    # --------------------------------------------------
    # 1) LOCAL CODE + SCHOOL + YEAR + EXACT TITLE (DESC OR ABBREV)
    # --------------------------------------------------
    if school_found and course_code and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 1: local code + school + year + exact title")

        local_matches = await match_by_local_code(
            db, school_ids, course_code, academic_years=academic_years
        )

        #  Normalize title once
        title_norm = normalize_text(course_title)

        #  Get abbrev map for all candidate courses
        abbrev_map = await get_course_abbrev_map(
            db,
            [row.id for row in local_matches],
            academic_years=academic_years,
        )

        validated_matches = []

        for row in local_matches:
            # 1. Match with description
            if normalize_text(row.crs_description) == title_norm:
                validated_matches.append(row)
                continue

            #  2. Match with abbreviation
            abbrevs = abbrev_map.get(row.id, [])
            if any(normalize_text(a) == title_norm for a in abbrevs):
                validated_matches.append(row)

        best_local = choose_best_match(validated_matches)

        if best_local:
            await apply_match(
                db,
                course_row,
                best_local,
                "matched_local_code_year_exact_title",
            )
            return

    # --------------------------------------------------
    # 2) LOCAL CODE + SCHOOL + WIHOUT year
    # --------------------------------------------------
    if school_found and course_code:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 2: local code + school + exact title")
        local_matches = await match_by_local_code(
            db, school_ids, course_code, academic_years=None
        )

        local_title_matches = [
            row for row in local_matches
            if normalize_text(row.crs_description) == normalize_text(course_title)
        ]

        best_local = choose_best_match(local_title_matches)
        if best_local:
            await apply_match(
                db,
                course_row,
                best_local,
                "matched_local_code_exact_title",
            )
            return


    # --------------------------------------------------
    # 3)  LOCAL CODE + YEAR - WITHOUT SCHOOL
    # --------------------------------------------------
    if course_code and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 3: general code + year")
        general_local_matches = await match_by_local_code_without_school(
            db, course_code, academic_years=academic_years
        )
        best_general_local = await choose_best_general_code_match(
            db=db,
            matches=general_local_matches,
            course_title=course_title,
            academic_years=academic_years,
        )
        if best_general_local:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_general_local,
                    "school_missing_mapped_with_general_codes_year",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_general_local,
                    "school_not_found_mapped_with_general_codes_year",
                )
                return

            await apply_match(
                db,
                course_row,
                best_general_local,
                "mapped_with_general_codes_year",
            )
            return

    # --------------------------------------------------
    # 4) LOCAL CODE +  without school + WITHOUT year
    # --------------------------------------------------
    if course_code:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 4: general code without year")
        general_local_matches = await match_by_local_code_without_school(
            db, course_code, academic_years=None
        )
        best_general_local = await choose_best_general_code_match(
            db=db,
            matches=general_local_matches,
            course_title=course_title,
            academic_years=None,
        )
        if best_general_local:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_general_local,
                    "school_missing_mapped_with_general_codes",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_general_local,
                    "school_not_found_mapped_with_general_codes",
                )
                return

            await apply_match(
                db,
                course_row,
                best_general_local,
                "mapped_with_general_codes",
            )
            return

    # --------------------------------------------------
    # 5)TITILE = ABBREV  + school + WITH year
    # --------------------------------------------------

    
    if school_found and course_title and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 5: abbrev exact + school + year")
        abbrev_matches = await match_by_abbrev(
            db, school_ids, course_title, academic_years=academic_years
        )
        best_abbrev = choose_best_match(abbrev_matches)
        if best_abbrev:
            await apply_match(db, course_row, best_abbrev, "matched_abbrev_year")
            return

    # --------------------------------------------------
    # 6)TILE = ABBREV  + school + WITHOUT year
    # --------------------------------------------------

    if school_found and course_title:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 6: abbrev exact + school")
        abbrev_matches = await match_by_abbrev(
            db, school_ids, course_title, academic_years=None
        )
        best_abbrev = choose_best_match(abbrev_matches)
        if best_abbrev:
            await apply_match(db, course_row, best_abbrev, "matched_abbrev")
            return


    # --------------------------------------------------
    # 7. TITLE = ABBREV + WITHOUT SCHOOL + YEAR
    # --------------------------------------------------
    if course_title and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 7: abbrev exact without school + year")
        abbrev_matches = await match_by_exact_desc_to_transcript_abbrev_without_school(
            db, course_title, academic_years=academic_years
        )
        best_abbrev = choose_best_match(abbrev_matches)
        if best_abbrev:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_abbrev,
                    "school_missing_matched_abbrev_year",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_abbrev,
                    "school_not_found_matched_abbrev_year",
                )
                return

            await apply_match(
                db,
                course_row,
                best_abbrev,
                "matched_abbrev_year_without_school",
            )
            return

    # --------------------------------------------------
    # 8. TITLE = ABBREV + WITHOUT SCHOOL + WITHOUT YEAR
    # --------------------------------------------------
    if course_title:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 8: abbrev exact without school")
        abbrev_matches = await match_by_exact_desc_to_transcript_abbrev_without_school(
            db, course_title, academic_years=None
        )
        best_abbrev = choose_best_match(abbrev_matches)
        if best_abbrev:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_abbrev,
                    "school_missing_matched_abbrev",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_abbrev,
                    "school_not_found_matched_abbrev",
                )
                return

            await apply_match(
                db,
                course_row,
                best_abbrev,
                "matched_abbrev_without_school",
            )
            return

    # --------------------------------------------------
    # 9) #  TITLE = DESCRIPTION +SCHOOL+YEAR
    # --------------------------------------------------
    
    if school_found and course_title and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 9: exact crs_description + school + year")
        exact_desc_matches = await match_by_exact_course_description(
            db, school_ids, course_title, academic_years=academic_years
        )
        best_exact_desc = choose_best_match(exact_desc_matches)
        if best_exact_desc:
            await apply_match(db, course_row, best_exact_desc, "matched_exact_course_description_year")
            return

    # --------------------------------------------------
    # 10) TITLE = DESCRIPTION +SCHOOL+ WIYHOUT YEAR
     # --------------------------------------------------
    if school_found and course_title:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 10: exact crs_description + school")
        exact_desc_matches = await match_by_exact_course_description(
            db, school_ids, course_title, academic_years=None
        )
        best_exact_desc = choose_best_match(exact_desc_matches)
        if best_exact_desc:
            await apply_match(db, course_row, best_exact_desc, "matched_exact_course_description")
            return

 

    
    # --------------------------------------------------
    # 11) TITLE =  exact course description + without school + YEAR 
    # --------------------------------------------------
    if course_title and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 11: exact crs_description without school + year")
        general_exact_desc_matches = await match_by_exact_course_description_without_school(
            db, course_title, academic_years=academic_years
        )
        best_general_exact_desc = choose_best_match(general_exact_desc_matches)
        if best_general_exact_desc:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_general_exact_desc,
                    "school_missing_matched_exact_course_description_year",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_general_exact_desc,
                    "school_missing_matched_exact_course_description_year",
                )
                return

            await apply_match(
                db,
                course_row,
                best_general_exact_desc,
                "matched_exact_course_description_year_without_school",
            )
            return

    # --------------------------------------------------
    # 12) TITLE =  exact course description + without school + WITHOUT YEAR 
    # --------------------------------------------------
    if course_title:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 12: exact crs_description without school")
        general_exact_desc_matches = await match_by_exact_course_description_without_school(
            db, course_title, academic_years=None
        )
        best_general_exact_desc = choose_best_match(general_exact_desc_matches)
        if best_general_exact_desc:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_general_exact_desc,
                    "school_missing_matched_exact_course_description",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_general_exact_desc,
                    "school_not_found_matched_exact_course_description",
                )
                return

            await apply_match(
                db,
                course_row,
                best_general_exact_desc,
                "matched_exact_course_description_without_school",
            )
            return
    # --------------------------------------------------
    # 13) NORMALIZED TITLE SQL MATCH + SCHOOL + YEAR
    # --------------------------------------------------
    if school_found and course_title and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 13: normalized SQL title match + school + year")

        matches = await match_by_normalized_title_sql(
            db=db,
            course_title=course_title,
            school_ids=school_ids,
            academic_years=academic_years,
        )

        best_match = choose_best_match(matches)
        if best_match:
            await apply_match(
                db,
                course_row,
                best_match,
                "matched_normalized_title_sql_school_year",
            )
            return

    # --------------------------------------------------
    # 14) NORMALIZED TITLE SQL MATCH + SCHOOL + WITHOUT YEAR
    # --------------------------------------------------
    if school_found and course_title:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 14: normalized SQL title match + school")

        matches = await match_by_normalized_title_sql(
            db=db,
            course_title=course_title,
            school_ids=school_ids,
            academic_years=None,
        )

        best_match = choose_best_match(matches)
        if best_match:
            await apply_match(
                db,
                course_row,
                best_match,
                "matched_normalized_title_sql_school",
            )
            return

    # --------------------------------------------------
    # 15) NORMALIZED TITLE SQL MATCH + WITHOUT SCHOOL + YEAR
    # --------------------------------------------------
    if course_title and academic_years:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 15: normalized SQL title match without school + year")

        matches = await match_by_normalized_title_sql(
            db=db,
            course_title=course_title,
            school_ids=None,
            academic_years=academic_years,
        )

        best_match = choose_best_match(matches)
        if best_match:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_match,
                    "school_missing_matched_normalized_title_sql_year",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_match,
                    "school_not_found_matched_normalized_title_sql_year",
                )
                return

            await apply_match(
                db,
                course_row,
                best_match,
                "matched_normalized_title_sql_year_without_school",
            )
            return
    # --------------------------------------------------
    # 16) NORMALIZED TITLE SQL MATCH + WITHOUT SCHOOL + WITHOUT YEAR
    # --------------------------------------------------
    if course_title:
        logger.debug(f"[UC_DOORWAY_MAPPING] course_id={course_row.id} -> Step 16: normalized SQL title match without school")

        matches = await match_by_normalized_title_sql(
            db=db,
            course_title=course_title,
            school_ids=None,
            academic_years=None,
        )

        best_match = choose_best_match(matches)
        if best_match:
            if not school_name:
                await apply_match(
                    db,
                    course_row,
                    best_match,
                    "school_missing_matched_normalized_title_sql",
                )
                return

            if not school_found:
                await apply_match(
                    db,
                    course_row,
                    best_match,
                    "school_not_found_matched_normalized_title_sql",
                )
                return

            await apply_match(
                db,
                course_row,
                best_match,
                "matched_normalized_title_sql_without_school",
            )
            return



    # --------------------------------------------------
    # 5) Final statuses
    # --------------------------------------------------
    if not school_name:
        await clear_match(db, course_row, "school_missing")
        return

    if not school_found:
        await clear_match(db, course_row, "school_not_found")
        return

    await clear_match(db, course_row, "no_match")


async def run_uc_doorway_course_mapping(
    session_factory: async_sessionmaker,
    progress_cb=None,
    batch_size: int = 50,
) -> dict:
    """
    Batched runner — one fresh DB connection per batch.

    Using NullPool means each `async with session_factory()` is a brand-new
    TCP connection, so long-running jobs never hit idle-connection-drop errors.
    """
    total_processed = 0
    total_selected = 0
    last_id = 0

    logger.debug(f"[UC_DOORWAY_MAPPING] Starting batched mapping run with batch_size={batch_size}")

    while True:
        async with session_factory() as db:
            stmt = (
                select(Course_details)
                .where(
                    Course_details.id > last_id,
                    ~exists(
                        select(1).where(
                            CourseDetailMappingUcDoorwayCourses.course_details_id == Course_details.id
                        )
                    ),
                )
                .order_by(Course_details.id)
                .limit(batch_size)
            )

            result = await db.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                logger.debug("[UC_DOORWAY_MAPPING] No more batches to process. Exiting run loop.")
                break

            batch_count = len(rows)
            total_selected += batch_count
            batch_last_id = rows[-1].id

            logger.debug(
                f"[UC_DOORWAY_MAPPING] Loaded batch: size={batch_count}, "
                f"starting_after_id={last_id}"
            )

            with db.no_autoflush:
                for idx, row in enumerate(rows, start=1):
                    logger.debug(
                        f"[UC_DOORWAY_MAPPING] Processing row {idx}/{batch_count} in batch: "
                        f"course_id={row.id}"
                    )
                    await process_single_course(db, row)
                    total_processed += 1

                    if progress_cb and total_selected > 0:
                        progress_cb("processing", int(total_processed / max(total_selected, 1) * 100))

            logger.debug(f"[UC_DOORWAY_MAPPING] Committing batch of {batch_count} courses")
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                logger.warning(
                    "[UC_DOORWAY_MAPPING] Batch commit had duplicate mapping rows "
                    "(concurrent job already mapped these courses) — skipping batch"
                )
            last_id = batch_last_id

        logger.debug(
            f"[UC_DOORWAY_MAPPING] Batch committed successfully: "
            f"processed={batch_count}, total_processed={total_processed}, new_last_id={last_id}"
        )

    if progress_cb:
        progress_cb("done", 100)

    logger.debug(
        f"[UC_DOORWAY_MAPPING] UC doorway mapping completed: "
        f"processed={total_processed}, total={total_selected}"
    )

    return {
        "processed": total_processed,
        "total": total_selected,
    }


# --------------------------------------------------
# Queue / background worker
# --------------------------------------------------
def enqueue_uc_doorway_course_mapping_job(job_id: str) -> None:
    global is_running

    with queue_lock:
        job_queue.append(job_id)
        logger.debug(
            f"[UC_DOORWAY_MAPPING] Job enqueued: job_id={job_id}, "
            f"queue_length={len(job_queue)}"
        )

        if not is_running:
            is_running = True
            Thread(target=_worker_loop, daemon=True).start()


def _worker_loop() -> None:
    global is_running, current_job_id, last_finished_job_id
    global last_error, last_run_status, started_at, finished_at, progress_stage, progress_percent

    while True:
        with queue_lock:
            if not job_queue:
                is_running = False
                current_job_id = None
                progress_stage = None
                progress_percent = 0
                logger.info("[UC_DOORWAY_MAPPING] Worker loop idle; no queued jobs.")
                return

            job_id = job_queue.popleft()

            current_job_id = job_id
            last_run_status = "running"
            last_error = None
            started_at = datetime.utcnow().isoformat()
            finished_at = None
            progress_stage = "queued"
            progress_percent = 0

            logger.debug(
                f"[UC_DOORWAY_MAPPING] Worker picked job: job_id={job_id}, "
                f"remaining_queue={len(job_queue)}"
            )

        asyncio.run(_process_mapping_job(job_id))


async def _process_mapping_job(job_id: str) -> None:
    global last_finished_job_id, last_error, last_run_status
    global finished_at, progress_stage, progress_percent

    # One engine for the entire job; NullPool means each session = new connection.
    engine = _make_thread_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        logger.debug(f"[UC_DOORWAY_MAPPING] Updating job status: job_id={job_id}, status=running")
        await _update_job_status(job_id, "running", factory=factory)

        def _set_progress(stage: str, pct: int) -> None:
            global progress_stage, progress_percent
            with queue_lock:
                progress_stage = stage
                progress_percent = int(pct)
            logger.debug(
                f"[UC_DOORWAY_MAPPING] Progress: "
                f"job_id={job_id}, stage={stage}, percent={pct}"
            )

        result = await run_uc_doorway_course_mapping(
            session_factory=factory,
            progress_cb=_set_progress,
        )

        with queue_lock:
            last_run_status = "success"
            last_finished_job_id = job_id
            finished_at = datetime.utcnow().isoformat()
            progress_stage = "done"
            progress_percent = 100

        await _update_job_status(job_id, "success", factory=factory)
        logger.debug(f"[UC_DOORWAY_MAPPING] Completed job_id={job_id}: {result}")

    except Exception:
        error_text = traceback.format_exc()

        try:
            await _update_job_status(job_id, "failed", error_text, factory=factory)
        except Exception:
            pass

        with queue_lock:
            last_run_status = "failed"
            last_error = error_text
            last_finished_job_id = job_id
            finished_at = datetime.utcnow().isoformat()
            progress_stage = "error"
            progress_percent = 0

        logger.debug(f"[UC_DOORWAY_MAPPING] Failed job_id={job_id}\n{error_text}")

    finally:
        await engine.dispose()



async def _process_mapping_job_in_loop(job_id: str) -> None:
    """
    Run a mapping job as a native asyncio Task in uvicorn's event loop.

    This avoids the thread + asyncio.run() approach that causes
    "attached to a different loop" errors with asyncpg.  Called via
    asyncio.get_running_loop().create_task() from async route handlers.
    """
    global last_finished_job_id, last_error, last_run_status
    global finished_at, progress_stage, progress_percent, current_job_id, started_at, is_running

    from app.db import AsyncSessionLocal  # imported here to avoid circular at module load

    with queue_lock:
        current_job_id = job_id
        is_running = True
        last_run_status = "running"
        last_error = None
        started_at = datetime.utcnow().isoformat()
        finished_at = None
        progress_stage = "queued"
        progress_percent = 0

    try:
        await _update_job_status(job_id, "running", factory=AsyncSessionLocal)

        def _set_progress(stage: str, pct: int) -> None:
            global progress_stage, progress_percent
            with queue_lock:
                progress_stage = stage
                progress_percent = int(pct)

        result = await run_uc_doorway_course_mapping(
            session_factory=AsyncSessionLocal,
            progress_cb=_set_progress,
        )

        with queue_lock:
            last_run_status = "success"
            last_finished_job_id = job_id
            finished_at = datetime.utcnow().isoformat()
            progress_stage = "done"
            progress_percent = 100

        await _update_job_status(job_id, "success", factory=AsyncSessionLocal)
        logger.info(f"[UC_DOORWAY_MAPPING] Completed (in-loop) job_id={job_id}: {result}")

    except Exception:
        error_text = traceback.format_exc()
        try:
            await _update_job_status(job_id, "failed", error_text, factory=AsyncSessionLocal)
        except Exception:
            pass

        with queue_lock:
            last_run_status = "failed"
            last_error = error_text
            last_finished_job_id = job_id
            finished_at = datetime.utcnow().isoformat()
            progress_stage = "error"
            progress_percent = 0

        logger.error(f"[UC_DOORWAY_MAPPING] Failed (in-loop) job_id={job_id}\n{error_text}")

    finally:
        with queue_lock:
            if current_job_id == job_id:
                current_job_id = None
                is_running = False


def schedule_uc_mapping_bg_task(job_id: str) -> None:
    """
    Schedule a UC mapping job as a background task in uvicorn's event loop.

    Call this from async route handlers instead of enqueue_uc_doorway_course_mapping_job.
    Uses asyncio.create_task() so the mapping runs in the SAME event loop as the DB pool,
    eliminating the 'attached to a different loop' error that plagues the thread-based approach.

    Skips if a mapping job is already running — the in-progress job will cover all unmapped
    courses including any newly extracted ones.
    """
    with queue_lock:
        if is_running:
            logger.info(
                f"[UC_DOORWAY_MAPPING] Mapping already running, skipping new job {job_id}"
            )
            return

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_process_mapping_job_in_loop(job_id))
        logger.info(f"[UC_DOORWAY_MAPPING] Scheduled bg task in uvicorn loop: job_id={job_id}")
    except RuntimeError:
        # No running loop (e.g. called from a sync test or CLI context) — fall back to thread
        logger.warning("[UC_DOORWAY_MAPPING] No running loop; falling back to thread-based enqueue")
        enqueue_uc_doorway_course_mapping_job(job_id)


async def run_uc_mapping_for_file(
    session_factory: async_sessionmaker,
    extraction_file_id: int,
) -> dict:
    """
    Batch-mode per-file mapping: ~8 SQL queries total for any number of courses.

    Fetches all potential matches in bulk, resolves priority in Python via dict
    lookups, then writes all results in a single INSERT — replacing the old
    per-course loop that fired 6-16 queries per course.
    """
    from sqlalchemy import text as _text
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    print(f"[UC_MAPPING] run_uc_mapping_for_file BATCH START file_id={extraction_file_id}", flush=True)

    async with session_factory() as db:

        # ── 1. Load all unmapped FINAL (validated) courses for this file ──────
        # Mapping runs on the validated final_course_details rows — the same rows
        # the UI / admission logic use — and links via final_course_details_id.
        # The DB trigger maps these on insert; this batch pass is a backstop for
        # any rows the trigger missed (e.g. re-runs, manual edits, backfill).
        q = await db.execute(_text("""
            SELECT fcd.id, fcd.crs_id, fcd.crs_description, fcd.crs_hs, fcd.crs_year
            FROM final_course_details fcd
            WHERE fcd.source_file = :fid
              AND NOT EXISTS (
                SELECT 1 FROM course_detail_mapping_uc_doorway_courses m
                WHERE m.final_course_details_id = fcd.id
              )
        """), {"fid": extraction_file_id})
        raw_courses = q.fetchall()

        if not raw_courses:
            print(f"[UC_MAPPING] file_id={extraction_file_id}: no unmapped courses", flush=True)
            return {"processed": 0, "total": 0}

        print(f"[UC_MAPPING] file_id={extraction_file_id}: batch-mapping {len(raw_courses)} courses", flush=True)

        # ── 2. Normalize inputs in Python ─────────────────────────────────────
        course_data = []
        all_school_names: set[str] = set()
        all_norm_codes:   set[str] = set()
        all_norm_titles:  set[str] = set()
        all_canon_keys:   set[str] = set()
        all_compact_keys: set[str] = set()

        for cd_id, raw_code, raw_title, raw_school, raw_year in raw_courses:
            norm_code   = normalize_course_code(raw_code)
            norm_title  = normalize_text(raw_title)
            norm_school = normalize_text(raw_school)
            years   = get_academic_year_candidates(raw_year)
            canon   = canonical_title_key_input(raw_title)
            compact = compact_title_key_input(raw_title)

            # Suffix-stripped variants — used as fallback keys so courses like
            # "AP US History A,B" still match abbrevs/descriptions stored as
            # "AP US History". Empty string means no suffix was found.
            stripped_raw   = strip_semester_suffix(raw_title)
            title_base     = normalize_text(stripped_raw) if stripped_raw != (raw_title or '').strip() else ''
            canon_base     = canonical_title_key_input(stripped_raw) if title_base else ''
            compact_base   = compact_title_key_input(stripped_raw)   if title_base else ''

            course_data.append({
                "id": cd_id, "norm_code": norm_code, "norm_title": norm_title,
                "raw_school": raw_school, "norm_school": norm_school,
                "years": years, "canon": canon, "compact": compact,
                "title_base": title_base, "canon_base": canon_base, "compact_base": compact_base,
            })
            if norm_school:  all_school_names.add(norm_school)
            if norm_code:    all_norm_codes.add(norm_code)
            if norm_title:   all_norm_titles.add(norm_title)
            if canon:        all_canon_keys.add(canon)
            if compact:      all_compact_keys.add(compact)
            if title_base:   all_norm_titles.add(title_base)
            if canon_base:   all_canon_keys.add(canon_base)
            if compact_base: all_compact_keys.add(compact_base)

        # ── 3. Batch school lookup (with in-process cache) ────────────────────
        school_map: dict[str, list[int]] = {}
        if all_school_names:
            uncached = [n for n in all_school_names if n not in _school_cache]
            if uncached:
                sq = await db.execute(_text(
                    "SELECT lower(hs_name), id FROM uc_doorway_schools WHERE lower(hs_name) = ANY(:n)"
                ), {"n": uncached})
                for nm, hid in sq.fetchall():
                    _school_cache.setdefault(nm, [])
                    if hid not in _school_cache[nm]:
                        _school_cache[nm].append(hid)
                for nm in uncached:
                    if nm not in _school_cache:
                        pq = await db.execute(_text(
                            "SELECT id FROM uc_doorway_schools WHERE lower(hs_name) LIKE :p"
                        ), {"p": f"%{nm}%"})
                        _school_cache[nm] = [r[0] for r in pq.fetchall()]
            for nm in all_school_names:
                school_map[nm] = _school_cache.get(nm, [])

        all_school_ids = list({hid for ids in school_map.values() for hid in ids})

        # ── 4. Batch fetch all potential matches ──────────────────────────────

        # 4a. Local-code hits
        code_by_c_h_y: dict[tuple, list[tuple[int, str]]] = {}
        code_by_c_h:   dict[tuple, list[tuple[int, str]]] = {}
        code_by_c_y:   dict[tuple, list[tuple[int, str]]] = {}
        code_by_c:     dict[tuple, list[tuple[int, str]]] = {}
        uc_abbrev_map: dict[int, list[str]] = {}

        if all_norm_codes:
            lcq = await db.execute(_text("""
                SELECT lower(si.search_value), si.hs_id, si.crs_academic_year,
                       uc.id, lower(uc.crs_description)
                FROM uc_doorway_courses_search_index si
                JOIN uc_doorway_courses uc ON uc.id = si.crs_id
                WHERE si.search_type = 'crs_local_codes'
                  AND lower(si.search_value) = ANY(:codes)
                ORDER BY si.crs_academic_year DESC NULLS LAST, uc.id DESC
            """), {"codes": list(all_norm_codes)})
            seen_uc_ids: set[int] = set()
            for code, hs_id, yr, uc_id, norm_desc in lcq.fetchall():
                code_by_c_h_y.setdefault((code, hs_id, yr), []).append((uc_id, norm_desc))
                code_by_c_h.setdefault((code, hs_id), []).append((uc_id, norm_desc))
                code_by_c_y.setdefault((code, yr), []).append((uc_id, norm_desc))
                code_by_c.setdefault((code,), []).append((uc_id, norm_desc))
                seen_uc_ids.add(uc_id)
            if seen_uc_ids:
                abq = await db.execute(_text("""
                    SELECT crs_id, lower(search_value)
                    FROM uc_doorway_courses_search_index
                    WHERE search_type = 'crs_transcript_abbrevs'
                      AND crs_id = ANY(:ids)
                """), {"ids": list(seen_uc_ids)})
                for crs_id, ab in abq.fetchall():
                    uc_abbrev_map.setdefault(crs_id, []).append(ab)

        # 4b. Abbrev hits (title == abbreviation)
        ab_by_t_h_y: dict[tuple, list[int]] = {}
        ab_by_t_h:   dict[tuple, list[int]] = {}
        ab_by_t_y:   dict[tuple, list[int]] = {}
        ab_by_t:     dict[tuple, list[int]] = {}

        if all_norm_titles:
            aq = await db.execute(_text("""
                SELECT lower(si.search_value), si.hs_id, si.crs_academic_year, uc.id
                FROM uc_doorway_courses_search_index si
                JOIN uc_doorway_courses uc ON uc.id = si.crs_id
                WHERE si.search_type = 'crs_transcript_abbrevs'
                  AND lower(si.search_value) = ANY(:titles)
                ORDER BY si.crs_academic_year DESC NULLS LAST, uc.id DESC
            """), {"titles": list(all_norm_titles)})
            for ab, hs_id, yr, uc_id in aq.fetchall():
                ab_by_t_h_y.setdefault((ab, hs_id, yr), []).append(uc_id)
                ab_by_t_h.setdefault((ab, hs_id), []).append(uc_id)
                ab_by_t_y.setdefault((ab, yr), []).append(uc_id)
                ab_by_t.setdefault((ab,), []).append(uc_id)

        # 4c. Exact description hits — unscoped (idx_ucd_lower_description makes this fast).
        # Must search all schools so steps 11-12 (without-school fallbacks) work correctly,
        # matching the behaviour of the old per-course process_single_course function.
        desc_by_t_h_y: dict[tuple, list[int]] = {}
        desc_by_t_h:   dict[tuple, list[int]] = {}
        desc_by_t_y:   dict[tuple, list[int]] = {}
        desc_by_t:     dict[tuple, list[int]] = {}

        if all_norm_titles:
            dq = await db.execute(_text("""
                SELECT lower(crs_description), hs_id, crs_academic_year, id
                FROM uc_doorway_courses
                WHERE lower(crs_description) = ANY(:titles)
                ORDER BY crs_academic_year DESC NULLS LAST, id DESC
            """), {"titles": list(all_norm_titles)})
            for desc, hs_id, yr, uc_id in dq.fetchall():
                desc_by_t_h_y.setdefault((desc, hs_id, yr), []).append(uc_id)
                desc_by_t_h.setdefault((desc, hs_id), []).append(uc_id)
                desc_by_t_y.setdefault((desc, yr), []).append(uc_id)
                desc_by_t.setdefault((desc,), []).append(uc_id)

        # 4d. Normalized title (canonical / compact key) hits.
        # School-scoped query (fast, uses idx_ucd_canonical_school_year) feeds the
        # school-specific dicts used by steps 13-14.
        # A second unscoped query feeds norm_by_k_y / norm_by_k for steps 15-16 so that
        # courses whose school was not found still get a normalized-title match, matching
        # the old per-course behaviour.
        norm_by_k_h_y: dict[tuple, list[int]] = {}
        norm_by_k_h:   dict[tuple, list[int]] = {}
        norm_by_k_y:   dict[tuple, list[int]] = {}
        norm_by_k:     dict[tuple, list[int]] = {}

        if (all_canon_keys or all_compact_keys) and all_school_ids:
            nq = await db.execute(_text("""
                SELECT canonical_title_key(crs_description),
                       compact_title_key(crs_description),
                       hs_id, crs_academic_year, id
                FROM uc_doorway_courses
                WHERE hs_id = ANY(:school_ids)
                  AND (canonical_title_key(crs_description) = ANY(:ck)
                       OR compact_title_key(crs_description) = ANY(:pk))
                ORDER BY crs_academic_year DESC NULLS LAST, id DESC
            """), {
                "school_ids": all_school_ids,
                "ck": list(all_canon_keys)   or ["__nomatch__"],
                "pk": list(all_compact_keys) or ["__nomatch__"],
            })
            for ck, pk, hs_id, yr, uc_id in nq.fetchall():
                for k in filter(None, {ck, pk}):
                    norm_by_k_h_y.setdefault((k, hs_id, yr), []).append(uc_id)
                    norm_by_k_h.setdefault((k, hs_id), []).append(uc_id)
                    norm_by_k_y.setdefault((k, yr), []).append(uc_id)
                    norm_by_k.setdefault((k,), []).append(uc_id)

        # 4d-any. Unscoped normalized-title query for steps 15-16 fallbacks.
        # Done once per file so even a full-table scan is far cheaper than the old
        # per-course approach.  Results are merged into norm_by_k_y / norm_by_k only
        # (school-specific dicts are already complete from the scoped query above).
        if all_canon_keys or all_compact_keys:
            nq_any = await db.execute(_text("""
                SELECT canonical_title_key(crs_description),
                       compact_title_key(crs_description),
                       crs_academic_year, id
                FROM uc_doorway_courses
                WHERE canonical_title_key(crs_description) = ANY(:ck)
                   OR compact_title_key(crs_description) = ANY(:pk)
                ORDER BY crs_academic_year DESC NULLS LAST, id DESC
            """), {
                "ck": list(all_canon_keys)   or ["__nomatch__"],
                "pk": list(all_compact_keys) or ["__nomatch__"],
            })
            for ck, pk, yr, uc_id in nq_any.fetchall():
                for k in filter(None, {ck, pk}):
                    if uc_id not in norm_by_k_y.get((k, yr), []):
                        norm_by_k_y.setdefault((k, yr), []).append(uc_id)
                    if uc_id not in norm_by_k.get((k,), []):
                        norm_by_k.setdefault((k,), []).append(uc_id)

        # ── 5. Priority matching — pure Python dict lookups ───────────────────

        def _code_match(d: dict, key: tuple, title: str, title_base: str = '') -> int | None:
            for uc_id, norm_desc in d.get(key, []):
                abbrevs = uc_abbrev_map.get(uc_id, [])
                if (norm_desc == title or norm_desc == title_base
                        or any(a == title or a == title_base for a in abbrevs)):
                    return uc_id
            return None

        def _code_any_match(d: dict, key: tuple, title: str, title_base: str = '') -> int | None:
            for uc_id, norm_desc in d.get(key, []):
                if norm_desc == title or norm_desc == title_base:
                    return uc_id
            return None

        def _first(d: dict, key: tuple) -> int | None:
            v = d.get(key, [])
            return v[0] if v else None

        assignments: list[tuple[int, int | None, str]] = []

        for c in course_data:
            cd_id        = c["id"]
            code         = c["norm_code"]
            title        = c["norm_title"]
            school       = c["raw_school"]
            ns           = c["norm_school"]
            years        = c["years"]
            canon        = c["canon"]
            compact      = c["compact"]
            title_base   = c["title_base"]
            canon_base   = c["canon_base"]
            compact_base = c["compact_base"]

            # Ordered dedup list of title/canon/compact keys: full first, suffix-stripped fallback second.
            title_keys  = list(dict.fromkeys(filter(None, [title, title_base])))
            canon_keys  = list(dict.fromkeys(filter(None, [canon, canon_base])))
            compact_keys = list(dict.fromkeys(filter(None, [compact, compact_base])))

            hids  = school_map.get(ns, []) if ns else []
            found = bool(hids)

            uid: int | None = None
            st:  str | None = None

            def _ss(no_name_st: str, not_found_st: str, default_st: str) -> str:
                return no_name_st if not school else (not_found_st if not found else default_st)

            # 1. code + school + year + exact title/abbrev
            if not uid and code and found and years:
                for h in hids:
                    for y in years:
                        uid = _code_match(code_by_c_h_y, (code, h, y), title, title_base)
                        if uid: st = "matched_local_code_year_exact_title"; break
                    if uid: break

            # 2. code + school + no year + exact title/abbrev
            if not uid and code and found:
                for h in hids:
                    uid = _code_match(code_by_c_h, (code, h), title, title_base)
                    if uid: st = "matched_local_code_exact_title"; break

            # 3. code + any school + year + exact title
            if not uid and code and years:
                for y in years:
                    uid = _code_any_match(code_by_c_y, (code, y), title, title_base)
                    if uid:
                        st = _ss("school_missing_mapped_with_general_codes_year",
                                 "school_not_found_mapped_with_general_codes_year",
                                 "mapped_with_general_codes_year"); break

            # 4. code + any school + no year + exact title
            if not uid and code:
                uid = _code_any_match(code_by_c, (code,), title, title_base)
                if uid:
                    st = _ss("school_missing_mapped_with_general_codes",
                             "school_not_found_mapped_with_general_codes",
                             "mapped_with_general_codes")

            # 5. abbrev + school + year
            if not uid and title_keys and found and years:
                for t in title_keys:
                    for h in hids:
                        for y in years:
                            uid = _first(ab_by_t_h_y, (t, h, y))
                            if uid: st = "matched_abbrev_year"; break
                        if uid: break
                    if uid: break

            # 6. abbrev + school + no year
            if not uid and title_keys and found:
                for t in title_keys:
                    for h in hids:
                        uid = _first(ab_by_t_h, (t, h))
                        if uid: st = "matched_abbrev"; break
                    if uid: break

            # 7. abbrev + any school + year
            if not uid and title_keys and years:
                for t in title_keys:
                    for y in years:
                        uid = _first(ab_by_t_y, (t, y))
                        if uid:
                            st = _ss("school_missing_matched_abbrev_year",
                                     "school_not_found_matched_abbrev_year",
                                     "matched_abbrev_year_without_school"); break
                    if uid: break

            # 8. abbrev + any school + no year
            if not uid and title_keys:
                for t in title_keys:
                    uid = _first(ab_by_t, (t,))
                    if uid:
                        st = _ss("school_missing_matched_abbrev",
                                 "school_not_found_matched_abbrev",
                                 "matched_abbrev_without_school"); break

            # 9. exact desc + school + year
            if not uid and title_keys and found and years:
                for t in title_keys:
                    for h in hids:
                        for y in years:
                            uid = _first(desc_by_t_h_y, (t, h, y))
                            if uid: st = "matched_exact_course_description_year"; break
                        if uid: break
                    if uid: break

            # 10. exact desc + school + no year
            if not uid and title_keys and found:
                for t in title_keys:
                    for h in hids:
                        uid = _first(desc_by_t_h, (t, h))
                        if uid: st = "matched_exact_course_description"; break
                    if uid: break

            # 11. exact desc + any school + year
            if not uid and title_keys and years:
                for t in title_keys:
                    for y in years:
                        uid = _first(desc_by_t_y, (t, y))
                        if uid:
                            st = _ss("school_missing_matched_exact_course_description_year",
                                     "school_missing_matched_exact_course_description_year",
                                     "matched_exact_course_description_year_without_school"); break
                    if uid: break

            # 12. exact desc + any school + no year
            if not uid and title_keys:
                for t in title_keys:
                    uid = _first(desc_by_t, (t,))
                    if uid:
                        st = _ss("school_missing_matched_exact_course_description",
                                 "school_not_found_matched_exact_course_description",
                                 "matched_exact_course_description_without_school"); break

            # 13–16. normalized title (try canon/compact including suffix-stripped variants)
            for k in filter(None, dict.fromkeys(canon_keys + compact_keys)):
                if uid: break
                if found and years:
                    for h in hids:
                        for y in years:
                            uid = _first(norm_by_k_h_y, (k, h, y))
                            if uid: st = "matched_normalized_title_sql_school_year"; break
                        if uid: break
                if uid: break
                if found:
                    for h in hids:
                        uid = _first(norm_by_k_h, (k, h))
                        if uid: st = "matched_normalized_title_sql_school"; break
                if uid: break
                if years:
                    for y in years:
                        uid = _first(norm_by_k_y, (k, y))
                        if uid:
                            st = _ss("school_missing_matched_normalized_title_sql_year",
                                     "school_not_found_matched_normalized_title_sql_year",
                                     "matched_normalized_title_sql_year_without_school"); break
                if uid: break
                uid = _first(norm_by_k, (k,))
                if uid:
                    st = _ss("school_missing_matched_normalized_title_sql",
                             "school_not_found_matched_normalized_title_sql",
                             "matched_normalized_title_sql_without_school")

            # Final: no match
            if not uid:
                st = ("school_missing"   if not school
                      else "school_not_found" if not found
                      else "no_match")

            assignments.append((cd_id, uid, st))

        # ── 6. Single bulk INSERT ─────────────────────────────────────────────
        if assignments:
            rows = [
                {
                    "final_course_details_id": a[0],
                    "uc_doorway_courses_id":   a[1],
                    "mapping_status":          a[2],
                }
                for a in assignments
            ]
            await db.execute(
                pg_insert(CourseDetailMappingUcDoorwayCourses)
                .values(rows)
                .on_conflict_do_nothing()
            )
            try:
                await db.commit()
                matched = sum(1 for a in assignments if a[1] is not None)
                print(
                    f"[UC_MAPPING] file_id={extraction_file_id}: "
                    f"bulk-committed {len(assignments)} rows "
                    f"({matched} matched, {len(assignments) - matched} unmatched) DONE",
                    flush=True,
                )
            except IntegrityError:
                await db.rollback()
                print(f"[UC_MAPPING] file_id={extraction_file_id}: conflict — already mapped", flush=True)

    return {"processed": len(assignments), "total": len(assignments)}


async def _run_mapping_for_file_task(extraction_file_id: int) -> None:
    """Async task wrapper — runs per-file mapping then computes AG summaries."""
    from app.db import AsyncSessionLocal
    try:
        await run_uc_mapping_for_file(AsyncSessionLocal, extraction_file_id)
    except Exception:
        logger.exception(
            f"[UC_DOORWAY_MAPPING] per-file mapping crashed for file_id={extraction_file_id}"
        )
        return
    # After mapping is done, auto-populate student_ag_summary calc columns
    try:
        from app.services.student_ag_computation_service import compute_ag_summaries_for_file
        await compute_ag_summaries_for_file(AsyncSessionLocal, extraction_file_id)
    except Exception:
        logger.exception(
            f"[AG_SUMMARY] auto-compute failed for file_id={extraction_file_id}"
        )


def schedule_mapping_for_file(extraction_file_id: int) -> None:
    """
    Trigger mapping for a single extraction file immediately after extraction.

    Called from async route handlers right after process_bytes_and_persist commits.
    Runs as an asyncio background task in uvicorn's event loop — no threads, no new loops.
    Only maps courses that belong to students from this specific file.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run_mapping_for_file_task(extraction_file_id))
        print(f"[UC_MAPPING] scheduled per-file mapping: file_id={extraction_file_id}", flush=True)
    except RuntimeError:
        print(f"[UC_MAPPING] ERROR: no running loop for file_id={extraction_file_id}", flush=True)


def get_uc_doorway_mapping_runtime_status() -> dict:
    with queue_lock:
        return {
            "last_run_status": last_run_status,
            "is_running": is_running,
            "current_job_id": current_job_id,
            "queued_jobs": list(job_queue),
            "queue_length": len(job_queue),
            "started_at": started_at,
            "finished_at": finished_at,
            "last_error": last_error,
            "last_finished_job_id": last_finished_job_id,
            "progress_stage": progress_stage,
            "progress_percent": progress_percent,
        }