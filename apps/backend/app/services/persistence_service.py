"""
Persistence service for transcript extraction payloads.

Clean 4-table pipeline responsibility:

1. Upsert student_details per extraction file and student id.
2. Insert raw Document AI course rows into course_details.
3. Clear stale course_details rows before re-inserting a file, so reprocessing is idempotent.
4. Preserve repeated Document AI course rows during base insertion.
5. Update extraction_file_details.process_status.

Important:
- course_details is treated as the raw Document AI extractor table.
- This service does NOT run Gemini extraction.
- This service does NOT compare Document AI vs Gemini.
- This service does NOT write gemini_course_details.
- This service does NOT write course_extraction_matches.
- This service does NOT write final_course_details.
- This service does NOT use old validation tables.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


TERMINAL_FILE_STATUSES = {
    "completed",
    "needs_review",
    "completed_with_errors",
    "failed",
    "cancelled",
    "unsupported",
    "not_transcript",
    "not_processed",
}


def _first_not_none(*vals):
    for value in vals:
        if value is not None:
            return value
    return None


def _first_non_empty(*vals):
    for value in vals:
        if value not in (None, "", [], {}):
            return value
    return None


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


def _norm_num(value: Any) -> str | None:
    if value is None:
        return None

    return str(value).replace(",", "").strip()


def _coerce_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        match = re.search(r"-?\d+", str(value))
        return int(match.group(0)) if match else None


def _coerce_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    try:
        text = str(value).strip()

        if "," in text and "." not in text:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

        return float(text)
    except Exception:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group(0)) if match else None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    text = str(value).strip()

    for fmt in (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            continue

    return None


def _month_to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip()

    try:
        return int(text)
    except Exception:
        pass

    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
        "fall": 1,
        "spring": 2,
        "semester 1": 1,
        "sem 1": 1,
        "semester 2": 2,
        "sem 2": 2,
    }

    low = text.lower()

    for key, val in months.items():
        if key in low:
            return val

    return None


def _year_to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip()

    try:
        return int(text)
    except Exception:
        pass

    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def _filter_model_values(model_cls: Any, values: dict[str, Any]) -> dict[str, Any]:
    model_columns = set(model_cls.__table__.columns.keys())

    return {
        key: value
        for key, value in values.items()
        if key in model_columns
    }


class PersistenceService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _resolve_source_file_id(self, value: Any) -> int | None:
        if value in (None, ""):
            return None

        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced

        try:
            result = await self.session.execute(
                select(models.ExtractionFileDetails.id)
                .where(models.ExtractionFileDetails.file_name == str(value).strip())
                .order_by(models.ExtractionFileDetails.id.desc())
                .limit(1)
            )

            found = result.scalar_one_or_none()
            return int(found) if found is not None else None
        except Exception:
            return None

    async def mark_file_status(self, extraction_file_id: int, status: str) -> None:
        now = datetime.now(timezone.utc)

        values: dict[str, Any] = {
            "process_status": status,
        }

        if status in TERMINAL_FILE_STATUSES:
            values["processed_date"] = now

        values = _filter_model_values(models.ExtractionFileDetails, values)

        await self.session.execute(
            update(models.ExtractionFileDetails)
            .where(models.ExtractionFileDetails.id == extraction_file_id)
            .values(**values)
        )
        await self.session.commit()

    async def upsert_student_by_classifier(
        self,
        classifier_name: str,
        payload: Dict[str, Any],
    ) -> Any:
        table = models.Students

        source_file = payload.get("source_file")
        source_file = await self._resolve_source_file_id(source_file)

        if source_file is None:
            print("[WARN] Missing source_file for student payload.")
            return None

        payload["source_file"] = source_file

        student_id_raw = (
            payload.get("student_id")
            or payload.get("student_external_id")
            or payload.get("id")
            or payload.get("student_number")
        )

        try:
            student_id = int(_norm_num(student_id_raw))
        except Exception:
            student_id = None

        if student_id is None:
            print(
                f"[WARN] Missing or invalid student_id for source_file={source_file}: "
                f"{student_id_raw}"
            )
            return None

        payload["student_id"] = student_id

        gpa_variants = {
            "total_gpa_course": [
                "Student_total_GPA",
                "StudentTotalGPA",
                "totalGPA",
                "total_gpa",
                "Student_total_gpa",
                "student_total_gpa",
                "overall_gpa",
            ],
            "cumulative_gpa": [
                "student_cumulative_GPA",
                "Student_cumulative_GPA",
                "student_cumulative_gpa",
                "cumulative",
                "student_cumulative",
            ],
            "university_gpa": [
                "University_GPA",
                "universityGPA",
                "university_gpa",
                "univ_gpa",
            ],
            "aca_gpa_course": [
                "ACA_GPA",
                "aca_gpa",
                "ACA_gpa",
                "academic_gpa",
                "aca_gpa_course",
            ],
        }

        for target, variants in gpa_variants.items():
            if payload.get(target) in (None, ""):
                for variant in variants:
                    if payload.get(variant) not in (None, ""):
                        payload[target] = payload.get(variant)
                        break

        for field in (
            "cumulative_gpa",
            "total_gpa_course",
            "aca_gpa_course",
            "university_gpa",
        ):
            payload[field] = _coerce_float(payload.get(field))

        mapped: Dict[str, Any] = {
            "source_file": source_file,
            "s_id": student_id,
            "s_name": (
                payload.get("name")
                or payload.get("student_name")
                or payload.get("Student_Name")
            ),
            "s_address": (
                payload.get("home_address")
                or payload.get("student_Home_address")
                or payload.get("student_home_address")
                or payload.get("homeAddress")
            ),
            "s_phone_number": (
                payload.get("phone_number")
                or payload.get("Student_Phone_number")
                or payload.get("student_phone_number")
            ),
            "s_gender": (
                payload.get("gender")
                or payload.get("student_gender")
                or payload.get("sex")
            ),
            "s_date_of_birth": _parse_date(
                payload.get("date_of_birth")
                or payload.get("dob")
                or payload.get("student_dob")
            ),
            "s_state_id": _coerce_int(
                payload.get("state_id")
                or payload.get("student_state")
                or payload.get("student_state_id")
                or payload.get("state")
            ),
            "hs_name": (
                payload.get("school_name")
                or payload.get("student_school")
                or payload.get("school")
                or ""
            ),
            "hs_counselor_name": (
                payload.get("counselor_name")
                or payload.get("student_counselor_name")
            ),
            "hs_grade": _coerce_int(
                payload.get("grade")
                or payload.get("student_Grade")
                or payload.get("student_grade")
            ),
            "hs_total_units_earned": _coerce_int(
                payload.get("total_units_earned")
                or payload.get("total_units")
                or payload.get("totalCredits")
                or payload.get("total_credits")
                or payload.get("units")
                or payload.get("units_earned")
                or payload.get("student_total_units")
            ),
            "hs_enter_date": _parse_date(
                payload.get("enter_date")
                or payload.get("student_enter_date")
            ),
            "hs_graduation_date": _parse_date(
                payload.get("graduation_date")
                or payload.get("student_graduation_date")
                or payload.get("grad_date")
                or payload.get("graduationDate")
            ),
        }

        total_gpa = payload.get("total_gpa_course") or payload.get("total_gpa")
        cumulative_gpa = (
            payload.get("cumulative_gpa")
            or payload.get("student_cumulative_GPA")
        )
        aca_gpa = payload.get("aca_gpa_course") or payload.get("ACA_GPA")
        university_gpa = (
            payload.get("university_gpa")
            or payload.get("University_GPA")
        )

        cls_lower = (classifier_name or "").lower()

        if "mayfair" in cls_lower:
            mapped["hs_total_gpa_course"] = _coerce_float(
                cumulative_gpa or total_gpa or university_gpa
            )

        elif "lbusd" in cls_lower or cls_lower == "lb":
            mapped["hs_total_gpa_course"] = _coerce_float(
                total_gpa or cumulative_gpa
            )
            mapped["hs_aca_gpa_course"] = _coerce_float(aca_gpa)
            mapped["hs_university_gpa"] = _coerce_float(university_gpa)

            found = {
                "aca": mapped.get("hs_aca_gpa_course"),
                "university": mapped.get("hs_university_gpa"),
                "total": mapped.get("hs_total_gpa_course"),
            }

            for key, value in payload.items():
                if value in (None, ""):
                    continue

                lower_key = str(key).lower()
                numeric_value = _coerce_float(value)

                if numeric_value is None:
                    continue

                if found["aca"] is None and (
                    "aca" in lower_key or "academic" in lower_key
                ):
                    found["aca"] = numeric_value

                if found["university"] is None and (
                    "university" in lower_key
                    or "univ" in lower_key
                    or "college" in lower_key
                    or "uc_gpa" in lower_key
                ):
                    found["university"] = numeric_value

                if found["total"] is None and (
                    "total" in lower_key
                    or "cumul" in lower_key
                    or "overall" in lower_key
                ):
                    found["total"] = numeric_value

            mapped["hs_total_gpa_course"] = found["total"]
            mapped["hs_aca_gpa_course"] = found["aca"]
            mapped["hs_university_gpa"] = found["university"]

        elif "st_anthony" in cls_lower or "anthony" in cls_lower:
            if not mapped.get("hs_name"):
                mapped["hs_name"] = "St. Anthony High School"

            mapped["hs_total_gpa_course"] = _coerce_float(
                cumulative_gpa or total_gpa or university_gpa
            )

        else:
            mapped["hs_total_gpa_course"] = _coerce_float(
                total_gpa or cumulative_gpa
            )
            mapped["hs_aca_gpa_course"] = _coerce_float(aca_gpa)
            mapped["hs_university_gpa"] = _coerce_float(university_gpa)

        if not mapped.get("s_name"):
            print(
                f"[WARN] Missing student name for source_file={source_file}, "
                f"student_id={student_id}. Using placeholder student name."
            )
            mapped["s_name"] = f"Unknown Student {student_id}"

        if not mapped.get("hs_name"):
            mapped["hs_name"] = ""

        mapped = _filter_model_values(table, mapped)

        result = await self.session.execute(
            select(table).where(
                table.source_file == source_file,
                table.s_id == student_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in mapped.items():
                if value is not None and hasattr(existing, key):
                    setattr(existing, key, value)

            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        row = table(**mapped)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)

        return row

    async def _clear_existing_courses_for_source_file_once(
        self,
        *,
        source_file_id: int,
        cleared_source_files: set[int],
    ) -> None:
        if source_file_id in cleared_source_files:
            return

        await self.session.execute(
            delete(models.Course_details).where(
                models.Course_details.source_file == source_file_id
            )
        )

        await self.session.flush()
        cleared_source_files.add(source_file_id)

        print(
            "[DOCUMENT AI COURSES CLEARED BEFORE INSERT] "
            f"source_file={source_file_id}"
        )

    async def insert_courses_by_classifier(
        self,
        classifier_name: str,
        rows: List[Dict[str, Any]],
    ) -> int:
        """
        Insert raw Document AI course rows into course_details.

        Important:
        Do NOT dedupe transcript course rows here.

        Repeated course IDs, names, grades, and credits can be valid transcript rows.
        If Document AI extracted 59 rows, this function should persist 59 rows
        unless a row is missing source_file or student DB id.

        Reconciliation happens later in CourseReconciliationService using:
        - course_details
        - gemini_course_details
        - course_extraction_matches
        - final_course_details
        """

        table = models.Course_details
        valid_fields = set(table.__table__.columns.keys())

        inserted_count = 0
        expanded_candidate_rows = 0
        skipped_without_student_id = 0
        skipped_without_source_file = 0
        cleared_source_files: set[int] = set()

        for row_index, row in enumerate(rows):
            mapped_course: Dict[str, Any] = {
                "s_id": row.get("student_id") or row.get("student_db_id"),
                "source_file": (
                    row.get("source_file")
                    or row.get("extraction_file_id")
                    or row.get("file_id")
                ),
                "crs_id": row.get("course_id") or row.get("crs_id"),
                "crs_description": (
                    row.get("title")
                    or row.get("course_title")
                    or row.get("course_name")
                    or row.get("crs_description")
                    or row.get("course")
                    or row.get("name")
                ),
                "crs_letter_grade": (
                    row.get("mark")
                    or row.get("course_mark")
                    or row.get("crs_letter_grade")
                    or row.get("grade")
                ),
                "crs_hs": (
                    row.get("term_school_name")
                    or row.get("term_schoolname")
                    or row.get("crs_hs")
                    or row.get("taken_at")
                ),
                "crs_grade": (
                    row.get("term_grade")
                    or row.get("crs_grade")
                    or row.get("grade_level")
                ),
                "crs_month": (
                    row.get("term_month")
                    or row.get("crs_month")
                    or row.get("month")
                ),
                "crs_year": (
                    row.get("term_year")
                    or row.get("crs_year")
                    or row.get("year")
                ),
                "crs_credit_attempted": _first_not_none(
                    row.get("credit_attempted"),
                    row.get("credits"),
                    row.get("crs_credit_attempted"),
                ),
                "crs_credit_completed": _first_not_none(
                    row.get("credit_completed"),
                    row.get("credits"),
                    row.get("crs_credit_completed"),
                ),
                "crs_term_gpa": (
                    row.get("total_term_gpa")
                    or row.get("term_gpa")
                    or row.get("total_gpa")
                    or row.get("termGPA")
                ),
            }

            base = {
                key: _blank_to_none(value)
                for key, value in mapped_course.items()
                if key in valid_fields
            }

            sem1 = row.get("sem_1") or row.get("sem1") or row.get("mark_sem1")
            sem2 = row.get("sem_2") or row.get("sem2") or row.get("mark_sem2")
            credit_sem1 = row.get("credit_sem1")
            credit_sem2 = row.get("credit_sem2")

            rows_to_insert: list[dict[str, Any]] = []

            if sem1 not in (None, "", False):
                sem1_row = base.copy()
                sem1_row["crs_month"] = 1
                sem1_row["crs_letter_grade"] = str(sem1).strip()

                if credit_sem1 not in (None, ""):
                    sem1_row["crs_credit_attempted"] = credit_sem1
                    sem1_row["crs_credit_completed"] = credit_sem1

                rows_to_insert.append(sem1_row)

            if sem2 not in (None, "", False):
                sem2_row = base.copy()
                sem2_row["crs_month"] = 2
                sem2_row["crs_letter_grade"] = str(sem2).strip()

                if credit_sem2 not in (None, ""):
                    sem2_row["crs_credit_attempted"] = credit_sem2
                    sem2_row["crs_credit_completed"] = credit_sem2

                rows_to_insert.append(sem2_row)

            if not rows_to_insert:
                rows_to_insert.append(base)

            for insert_row in rows_to_insert:
                expanded_candidate_rows += 1

                insert_row = {
                    key: _blank_to_none(value)
                    for key, value in insert_row.items()
                    if key in valid_fields
                }

                insert_row["s_id"] = _coerce_int(insert_row.get("s_id"))

                source_file_id = await self._resolve_source_file_id(
                    insert_row.get("source_file")
                )

                if "source_file" in insert_row:
                    insert_row["source_file"] = source_file_id

                insert_row["crs_grade"] = _coerce_int(insert_row.get("crs_grade"))
                insert_row["crs_month"] = _month_to_int(insert_row.get("crs_month"))
                insert_row["crs_year"] = _year_to_int(insert_row.get("crs_year"))

                insert_row["crs_credit_attempted"] = _coerce_float(
                    insert_row.get("crs_credit_attempted")
                )
                insert_row["crs_credit_completed"] = _coerce_float(
                    insert_row.get("crs_credit_completed")
                )
                insert_row["crs_term_gpa"] = _coerce_float(
                    insert_row.get("crs_term_gpa")
                )

                student_db_id = insert_row.get("s_id")

                if not student_db_id:
                    skipped_without_student_id += 1
                    print(
                        "[WARN] Skipping Document AI course without student DB id: "
                        f"source_file={source_file_id}, "
                        f"row_index={row_index}, "
                        f"row={insert_row}"
                    )
                    continue

                if not source_file_id:
                    skipped_without_source_file += 1
                    print(
                        "[WARN] Skipping Document AI course without source_file: "
                        f"student_db_id={student_db_id}, "
                        f"row_index={row_index}, "
                        f"row={insert_row}"
                    )
                    continue

                await self._clear_existing_courses_for_source_file_once(
                    source_file_id=int(source_file_id),
                    cleared_source_files=cleared_source_files,
                )

                self.session.add(table(**insert_row))
                inserted_count += 1

        await self.session.commit()

        print(
            "[DOCUMENT AI COURSES INSERTED] "
            f"input_rows={len(rows)}, "
            f"expanded_candidate_rows={expanded_candidate_rows}, "
            f"inserted={inserted_count}, "
            f"skipped_without_student_id={skipped_without_student_id}, "
            f"skipped_without_source_file={skipped_without_source_file}, "
            f"cleared_files={sorted(cleared_source_files)}"
        )

        return inserted_count