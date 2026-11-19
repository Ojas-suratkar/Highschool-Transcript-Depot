from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Students,
    Course_details,
    UCDoorwayCourses,
    CourseDetailMappingUcDoorwayCourses,
)


async def get_student_full_details(db: AsyncSession, student_id: int):
    """
    UI sends external student number like 201104665.
    We first find the student using Students.s_id.

    IMPORTANT:
    Course_details.s_id stores Students.id (internal PK),
    so course lookup must use student.id, not student.s_id.
    """

    # Find student by external student number
    student_result = await db.execute(
        select(Students).where(Students.s_id == student_id)
    )
    student = student_result.scalar_one_or_none()

    if student is None:
        return None

    # Find all courses for this student using internal PK
    # Join through CourseDetailMappingUcDoorwayCourses
    course_result = await db.execute(
        select(
            Course_details,
            CourseDetailMappingUcDoorwayCourses,
            UCDoorwayCourses,
        )
        .outerjoin(
            CourseDetailMappingUcDoorwayCourses,
            CourseDetailMappingUcDoorwayCourses.course_details_id == Course_details.id,
        )
        .outerjoin(
            UCDoorwayCourses,
            CourseDetailMappingUcDoorwayCourses.uc_doorway_courses_id == UCDoorwayCourses.id,
        )
        .where(Course_details.s_id == student.id)
        .order_by(Course_details.id.asc())
    )
    rows = course_result.all()

    courses = []

    for course, course_mapping, mapped_course in rows:
        mapped_data = None

        if mapped_course is not None:
            mapped_data = {
                "id": mapped_course.id,
                "hs_id": mapped_course.hs_id,
                "crs_hs": mapped_course.crs_hs,
                "crs_description": mapped_course.crs_description,
                "crs_discipline": getattr(mapped_course, "crs_discipline", None),
                "crs_environment": getattr(mapped_course, "crs_environment", None),
                "crs_honors": getattr(mapped_course, "crs_honors", None),
                "crs_ag_category_letter": getattr(mapped_course, "crs_ag_category_letter", None),
                "crs_ag_category_description": getattr(mapped_course, "crs_ag_category_description", None),
                "crs_grade": getattr(mapped_course, "crs_grade", None),
                "crs_transcript_abbrevs": getattr(mapped_course, "crs_transcript_abbrevs", None),
                "crs_local_codes": getattr(mapped_course, "crs_local_codes", None),
                "crs_academic_year": getattr(mapped_course, "crs_academic_year", None),
            }

        course_data = {
            "id": course.id,
            "s_id": course.s_id,
            "crs_id": course.crs_id,
            "crs_letter_grade": course.crs_letter_grade,
            "crs_description": course.crs_description,
            "crs_hs": course.crs_hs,
            "crs_grade": course.crs_grade,
            "crs_month": course.crs_month,
            "crs_year": course.crs_year,
            "crs_credit_attempted": course.crs_credit_attempted,
            "crs_credit_completed": course.crs_credit_completed,
            "crs_term_gpa": course.crs_term_gpa,
            "mapping_status": course_mapping.mapping_status if course_mapping else None,
            "uc_doorway_course_id": (
                course_mapping.uc_doorway_courses_id if course_mapping else None
            ),
            "mapped_uc_course": mapped_data,
        }
        courses.append(course_data)

    return {
        "student": {
            "id": student.id,
            "s_id": student.s_id,
            "s_name": student.s_name,
            "s_address": student.s_address,
            "s_phone_number": student.s_phone_number,
            "s_gender": student.s_gender,
            "s_date_of_birth": str(student.s_date_of_birth) if student.s_date_of_birth else None,
            "s_state_id": student.s_state_id,
            "hs_name": student.hs_name,
            "hs_counselor_name": student.hs_counselor_name,
            "hs_grade": student.hs_grade,
            "hs_total_units_earned": student.hs_total_units_earned,
            "hs_total_gpa_course": student.hs_total_gpa_course,
            "hs_aca_gpa_course": student.hs_aca_gpa_course,
            "hs_university_gpa": student.hs_university_gpa,
            "hs_enter_date": str(student.hs_enter_date) if student.hs_enter_date else None,
            "hs_graduation_date": str(student.hs_graduation_date) if student.hs_graduation_date else None,
            "source_file": student.source_file,
        },
        "courses": courses,
    }