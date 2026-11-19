from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
        unique=True,
        index=True,
    )


def int_pk() -> Mapped[int]:
    return mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        index=True,
    )


# ----------------
# Profiles
# ----------------
class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = uuid_pk()

    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)

    institution_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("institution.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    role: Mapped[str | None] = mapped_column(String, nullable=True)

    microsoft_oid: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    otp_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)

    otp_last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ----------------
# OTP Challenges
# ----------------
class OTPChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[uuid.UUID] = uuid_pk()

    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)

    institution_name: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    zip: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)

    otp_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Institution(Base):
    __tablename__ = "institution"

    id: Mapped[int] = int_pk()

    institution_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    program_criteria: Mapped[list["ProgramCriteria"]] = relationship(
        "ProgramCriteria",
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    admission_criteria: Mapped[list["AdmissionCriteria"]] = relationship(
        "AdmissionCriteria",
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    overall_gpa_criteria: Mapped[list["OverallGPACriteria"]] = relationship(
        "OverallGPACriteria",
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    cloud_locations: Mapped[list["CloudFileLocation"]] = relationship(
        "CloudFileLocation",
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    templates: Mapped[list["Templates"]] = relationship(
        "Templates",
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    admission_statuses: Mapped[list["AdmissionStatus"]] = relationship(
        "AdmissionStatus",
        back_populates="institution",
        cascade="all, delete-orphan",
    )


class ProgramCriteria(Base):
    __tablename__ = "program_criteria"

    id: Mapped[int] = int_pk()

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    program_name: Mapped[str] = mapped_column(Text, nullable=False)
    prerequisite_course_name: Mapped[str] = mapped_column(Text, nullable=False)
    prerequisite_course_gpa: Mapped[str] = mapped_column(Text, nullable=False)

    year_intake: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="program_criteria",
        lazy="joined",
    )


class AGType(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class AdmissionCriteria(Base):
    __tablename__ = "admission_criteria"

    id: Mapped[int] = int_pk()

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    a_to_g_course_type: Mapped[AGType] = mapped_column(
        String(1),
        nullable=False,
        index=True,
    )

    min_no_years_a_to_g: Mapped[str | None] = mapped_column(String(5), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    marks: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gpa: Mapped[float | None] = mapped_column(nullable=True)

    year_intake: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="admission_criteria",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "a_to_g_course_type",
            "year_intake",
            name="uq_admission_criteria_ag",
        ),
    )


class OverallGPACriteria(Base):
    __tablename__ = "overall_gpa_criteria"

    id: Mapped[int] = int_pk()

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    min_gpa: Mapped[float] = mapped_column(nullable=False)

    year_intake: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="overall_gpa_criteria",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "year_intake",
            name="uq_overall_gpa_criteria",
        ),
    )


class CloudFileLocation(Base):
    __tablename__ = "cloud_file_location"

    id: Mapped[int] = int_pk()

    label: Mapped[str] = mapped_column(String(255), nullable=False)

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sync_status: Mapped[str] = mapped_column(Text, nullable=False)

    year_intake: Mapped[str | None] = mapped_column(String(50), nullable=True)

    program_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_polled: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="cloud_locations",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "year_intake",
            "is_active",
            name="uq_cloud_location_active_term",
        ),
    )


class ClassifiersType(Base):
    __tablename__ = "classifier_type"

    id: Mapped[int] = int_pk()

    classifier_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    processor_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )


class ExtractionFileDetails(Base):
    __tablename__ = "extraction_file_details"

    id: Mapped[int] = int_pk()

    file_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    process_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    upload_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    processed_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    year_intake: Mapped[str | None] = mapped_column(String(50), nullable=True)

    classifier_type: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("classifier_type.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("program_criteria.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    students: Mapped[list["Students"]] = relationship(
        "Students",
        back_populates="extraction_file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    courses: Mapped[list["Course_details"]] = relationship(
        "Course_details",
        back_populates="extraction_file",
        lazy="selectin",
    )

    gemini_courses: Mapped[list["GeminiCourseDetails"]] = relationship(
        "GeminiCourseDetails",
        back_populates="extraction_file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    course_extraction_matches: Mapped[list["CourseExtractionMatches"]] = relationship(
        "CourseExtractionMatches",
        back_populates="extraction_file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    final_courses: Mapped[list["FinalCourseDetails"]] = relationship(
        "FinalCourseDetails",
        back_populates="extraction_file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "ix_extraction_file_status_upload_date",
            "process_status",
            "upload_date",
        ),
    )


class Students(Base):
    __tablename__ = "student_details"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    s_name: Mapped[str] = mapped_column(Text, nullable=False)

    s_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    s_phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    s_gender: Mapped[str | None] = mapped_column(String(50), nullable=True)

    s_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    s_state_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    hs_name: Mapped[str] = mapped_column(Text, nullable=False)

    hs_counselor_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    hs_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hs_total_units_earned: Mapped[int | None] = mapped_column(Float, nullable=True)

    hs_total_gpa_course: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_aca_gpa_course: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_university_gpa: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_enter_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    hs_graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    source_file: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    extraction_file: Mapped["ExtractionFileDetails"] = relationship(
        "ExtractionFileDetails",
        back_populates="students",
    )

    courses: Mapped[list["Course_details"]] = relationship(
        "Course_details",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    gemini_courses: Mapped[list["GeminiCourseDetails"]] = relationship(
        "GeminiCourseDetails",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    final_courses: Mapped[list["FinalCourseDetails"]] = relationship(
        "FinalCourseDetails",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    course_extraction_matches: Mapped[list["CourseExtractionMatches"]] = relationship(
        "CourseExtractionMatches",
        back_populates="student",
        lazy="selectin",
    )


class Course_details(Base):
    """
    Raw Document AI extracted course rows.

    Important:
    This table should be treated as the Document AI extractor table.
    Do not write Gemini-corrected/final values here.
    """

    __tablename__ = "course_details"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("student_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    source_file: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    crs_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    crs_letter_grade: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_hs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_grade: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    crs_credit_attempted: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_credit_completed: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_term_gpa: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    student: Mapped["Students | None"] = relationship(
        "Students",
        back_populates="courses",
    )

    extraction_file: Mapped["ExtractionFileDetails | None"] = relationship(
        "ExtractionFileDetails",
        back_populates="courses",
    )

    course_mapping: Mapped["CourseDetailMappingUcDoorwayCourses | None"] = relationship(
        "CourseDetailMappingUcDoorwayCourses",
        back_populates="course_detail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )

    extraction_matches: Mapped[list["CourseExtractionMatches"]] = relationship(
        "CourseExtractionMatches",
        back_populates="document_ai_course_detail",
        foreign_keys="CourseExtractionMatches.document_ai_course_detail_id",
        lazy="selectin",
    )

    final_courses: Mapped[list["FinalCourseDetails"]] = relationship(
        "FinalCourseDetails",
        back_populates="document_ai_course_detail",
        foreign_keys="FinalCourseDetails.document_ai_course_detail_id",
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# Gemini-only new transcript staging tables
# ---------------------------------------------------------------------------
#
# These two tables intentionally contain only the real transcript fields that
# already exist in student_details and course_details. They do not contain
# confidence, model, snapshot, reconciliation, or other Gemini metadata.
#
# Existing transcript models and relationships above remain unchanged.


class NewTranscriptStudents(Base):
    """
    Student fields extracted from transcript types that do not yet have a
    dedicated Document AI extractor.

    This table mirrors the real transcript columns in student_details while
    keeping new transcript-type data isolated from the existing pipeline.
    """

    __tablename__ = "new_transcript_student_details"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    s_name: Mapped[str] = mapped_column(Text, nullable=False)

    s_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    s_phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    s_gender: Mapped[str | None] = mapped_column(String(50), nullable=True)

    s_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    s_state_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    hs_name: Mapped[str] = mapped_column(Text, nullable=False)

    hs_counselor_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    hs_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hs_total_units_earned: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_total_gpa_course: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_aca_gpa_course: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_university_gpa: Mapped[float | None] = mapped_column(Float, nullable=True)

    hs_enter_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    hs_graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    source_file: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    courses: Mapped[list["NewTranscriptCourseDetails"]] = relationship(
        "NewTranscriptCourseDetails",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class NewTranscriptCourseDetails(Base):
    """
    Real course fields extracted from transcript types that do not yet have a
    dedicated Document AI extractor.

    This table mirrors the columns in course_details while keeping the rows
    separate from existing trusted transcript data.
    """

    __tablename__ = "new_transcript_course_details"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("new_transcript_student_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    source_file: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    crs_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    crs_letter_grade: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_hs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_grade: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    crs_credit_attempted: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_credit_completed: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_term_gpa: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    reviewed_by_user: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    student: Mapped["NewTranscriptStudents | None"] = relationship(
        "NewTranscriptStudents",
        back_populates="courses",
    )



class GeminiCourseDetails(Base):
    """
    Raw Gemini extracted course rows.

    Actual table:
    gemini_course_details

    Columns intentionally mirror the core course_details fields, plus Gemini-only
    metadata like row_index, course_index, extraction_confidence, model, and raw_payload.
    """

    __tablename__ = "gemini_course_details"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("student_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    crs_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    crs_letter_grade: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_hs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_grade: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    crs_credit_attempted: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_credit_completed: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_term_gpa: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    source_file: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    row_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    course_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    extraction_confidence: Mapped[float | None] = mapped_column(
        Numeric,
        nullable=True,
    )

    model: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    student: Mapped["Students | None"] = relationship(
        "Students",
        back_populates="gemini_courses",
    )

    extraction_file: Mapped["ExtractionFileDetails | None"] = relationship(
        "ExtractionFileDetails",
        back_populates="gemini_courses",
    )

    extraction_matches: Mapped[list["CourseExtractionMatches"]] = relationship(
        "CourseExtractionMatches",
        back_populates="gemini_course_detail",
        foreign_keys="CourseExtractionMatches.gemini_course_detail_id",
        lazy="selectin",
    )

    final_courses: Mapped[list["FinalCourseDetails"]] = relationship(
        "FinalCourseDetails",
        back_populates="gemini_course_detail",
        foreign_keys="FinalCourseDetails.gemini_course_detail_id",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_gemini_course_file_student", "source_file", "s_id"),
        Index("idx_gemini_course_file_year", "source_file", "crs_year"),
    )


class FinalCourseDetails(Base):
    """
    Final trusted course rows.

    Actual table:
    final_course_details

    Frontend, GPA calculation, admission review, Completed page, and Needs Review page
    should read this table instead of raw course_details.
    """

    __tablename__ = "final_course_details"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("student_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    source_file: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    document_ai_course_detail_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("course_details.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    gemini_course_detail_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("gemini_course_details.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    crs_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    crs_letter_grade: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_hs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_grade: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    crs_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    crs_credit_attempted: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_credit_completed: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    crs_term_gpa: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    final_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="merged",
        server_default=text("'merged'"),
        index=True,
    )

    crs_id_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_description_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_letter_grade_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_hs_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_grade_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_month_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_year_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_credit_attempted_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_credit_completed_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    crs_term_gpa_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    review_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="auto_resolved",
        server_default=text("'auto_resolved'"),
        index=True,
    )

    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
        index=True,
    )

    review_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolution_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    document_ai_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    gemini_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    field_decisions: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    student: Mapped["Students | None"] = relationship(
        "Students",
        back_populates="final_courses",
    )

    extraction_file: Mapped["ExtractionFileDetails | None"] = relationship(
        "ExtractionFileDetails",
        back_populates="final_courses",
    )

    document_ai_course_detail: Mapped["Course_details | None"] = relationship(
        "Course_details",
        back_populates="final_courses",
        foreign_keys=[document_ai_course_detail_id],
    )

    gemini_course_detail: Mapped["GeminiCourseDetails | None"] = relationship(
        "GeminiCourseDetails",
        back_populates="final_courses",
        foreign_keys=[gemini_course_detail_id],
    )

    extraction_matches: Mapped[list["CourseExtractionMatches"]] = relationship(
        "CourseExtractionMatches",
        back_populates="final_course_detail",
        foreign_keys="CourseExtractionMatches.final_course_detail_id",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_final_course_file_student", "source_file", "s_id"),
        Index("idx_final_course_file_review", "source_file", "needs_review"),
        Index("idx_final_course_doc_ai_id", "document_ai_course_detail_id"),
        Index("idx_final_course_gemini_id", "gemini_course_detail_id"),
    )


class CourseExtractionMatches(Base):
    """
    Reconciliation table comparing raw Document AI rows with raw Gemini rows.

    Actual table:
    course_extraction_matches

    This stores match type, per-field agreement flags, selected source decisions,
    snapshots, review state, and the linked final_course_details row.
    """

    __tablename__ = "course_extraction_matches"

    id: Mapped[int] = int_pk()

    extraction_file_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    s_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("student_details.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    document_ai_course_detail_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("course_details.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    gemini_course_detail_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("gemini_course_details.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    final_course_detail_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("final_course_details.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    match_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    match_confidence: Mapped[float | None] = mapped_column(
        Numeric(5, 3),
        nullable=True,
    )

    course_id_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    course_name_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    letter_grade_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    grade_level_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    month_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    year_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    credit_attempted_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    credit_completed_match: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    course_name_score: Mapped[float | None] = mapped_column(
        Numeric(5, 3),
        nullable=True,
    )

    course_id_score: Mapped[float | None] = mapped_column(
        Numeric(5, 3),
        nullable=True,
    )

    overall_match_score: Mapped[float | None] = mapped_column(
        Numeric(5, 3),
        nullable=True,
    )

    selected_course_id_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_course_name_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_letter_grade_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_grade_level_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_month_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_year_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_credit_attempted_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    selected_credit_completed_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
        index=True,
    )

    review_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolution_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    reviewed_by_user: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    document_ai_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    gemini_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    field_differences: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    field_decisions: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    extraction_file: Mapped["ExtractionFileDetails"] = relationship(
        "ExtractionFileDetails",
        back_populates="course_extraction_matches",
    )

    student: Mapped["Students | None"] = relationship(
        "Students",
        back_populates="course_extraction_matches",
    )

    document_ai_course_detail: Mapped["Course_details | None"] = relationship(
        "Course_details",
        back_populates="extraction_matches",
        foreign_keys=[document_ai_course_detail_id],
    )

    gemini_course_detail: Mapped["GeminiCourseDetails | None"] = relationship(
        "GeminiCourseDetails",
        back_populates="extraction_matches",
        foreign_keys=[gemini_course_detail_id],
    )

    final_course_detail: Mapped["FinalCourseDetails | None"] = relationship(
        "FinalCourseDetails",
        back_populates="extraction_matches",
        foreign_keys=[final_course_detail_id],
    )

    __table_args__ = (
        Index("idx_course_matches_file_student", "extraction_file_id", "s_id"),
        Index("idx_course_matches_file_type", "extraction_file_id", "match_type"),
        Index("idx_course_matches_file_review", "extraction_file_id", "needs_review"),
        Index("idx_course_matches_doc_ai_id", "document_ai_course_detail_id"),
        Index("idx_course_matches_gemini_id", "gemini_course_detail_id"),
        Index("idx_course_matches_final_id", "final_course_detail_id"),
    )


class CourseDetailMappingUcDoorwayCourses(Base):
    __tablename__ = "course_detail_mapping_uc_doorway_courses"

    id: Mapped[int] = int_pk()

    course_details_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("course_details.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )

    # Mapping link to the validated final row. The DB column + trigger populate
    # this; the UI / A-G / GPA / Standardization tabs join on it. Re-added after
    # a branch merge dropped it from the model, which silently broke mapping
    # display even though the DB column and data were present.
    final_course_details_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("final_course_details.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )

    uc_doorway_courses_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("uc_doorway_courses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    mapping_status: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    mapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    course_detail: Mapped["Course_details"] = relationship(
        "Course_details",
        back_populates="course_mapping",
    )

    uc_course: Mapped["UCDoorwayCourses | None"] = relationship(
        "UCDoorwayCourses",
        lazy="joined",
    )


class AcademicTerm(Base):
    __tablename__ = "academic_term"

    id: Mapped[int] = int_pk()

    term_name: Mapped[str] = mapped_column(String(100), nullable=False)
    term: Mapped[str] = mapped_column(String(20), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    institution_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "term_name",
            name="uq_academic_term_institution_name",
        ),
    )


class Templates(Base):
    __tablename__ = "templates"

    id: Mapped[int] = int_pk()

    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    template_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    institution_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="templates",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "is_active",
            name="uq_i20_template_active_per_institution",
        ),
    )


class AdmissionStatus(Base):
    __tablename__ = "admission_status"

    id: Mapped[int] = int_pk()

    s_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("student_details.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    year_intake: Mapped[str] = mapped_column(Text, nullable=False)
    program: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    i20_status: Mapped[str] = mapped_column(Text, nullable=False)

    institution_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("institution.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="admission_statuses",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "s_id",
            "institution_id",
            name="uq_student_per_institution",
        ),
    )


class UCDoorwaySchools(Base):
    __tablename__ = "uc_doorway_schools"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    hs_type: Mapped[str] = mapped_column(Text, nullable=False)
    hs_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    hs_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    hs_district: Mapped[str | None] = mapped_column(Text, nullable=True)
    hs_type_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    courses: Mapped[list["UCDoorwayCourses"]] = relationship(
        "UCDoorwayCourses",
        back_populates="school",
        cascade="all, delete-orphan",
    )

    scrape_statuses: Mapped[list["UCDoorwayScrapeStatus"]] = relationship(
        "UCDoorwayScrapeStatus",
        back_populates="school",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "ix_uc_doorway_school_name_location",
            "hs_name",
            "hs_location",
        ),
    )


class UCDoorwayCourses(Base):
    __tablename__ = "uc_doorway_courses"

    id: Mapped[int] = int_pk()

    hs_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("uc_doorway_schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    crs_hs: Mapped[str] = mapped_column(Text, nullable=False)

    crs_academic_year: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    crs_description: Mapped[str] = mapped_column(Text, nullable=False)

    crs_discipline: Mapped[str | None] = mapped_column(Text, nullable=True)
    crs_environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    crs_honors: Mapped[str | None] = mapped_column(Text, nullable=True)

    crs_ag_category_letter: Mapped[str | None] = mapped_column(
        String(5),
        nullable=True,
        index=True,
    )

    crs_ag_category_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    crs_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    crs_transcript_abbrevs: Mapped[str | None] = mapped_column(Text, nullable=True)
    crs_local_codes: Mapped[str | None] = mapped_column(Text, nullable=True)

    school: Mapped["UCDoorwaySchools"] = relationship(
        "UCDoorwaySchools",
        back_populates="courses",
        lazy="joined",
    )

    __table_args__ = (
        Index(
            "ix_uc_course_school_year_ag",
            "hs_id",
            "crs_academic_year",
            "crs_ag_category_letter",
        ),
        Index(
            "idx_ucd_canonical_school_year",
            "hs_id",
            "crs_academic_year",
            text("canonical_title_key(crs_description)"),
        ),
        Index(
            "idx_ucd_compact_school_year",
            "hs_id",
            "crs_academic_year",
            text("compact_title_key(crs_description)"),
        ),
    )


class UCDoorwayScrapeStatus(Base):
    __tablename__ = "uc_doorway_scrape_status"

    id: Mapped[int] = int_pk()

    hs_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("uc_doorway_schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    hs_type: Mapped[str] = mapped_column(Text, nullable=False)
    hs_name: Mapped[str] = mapped_column(Text, nullable=False)
    hs_location: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    school: Mapped["UCDoorwaySchools"] = relationship(
        "UCDoorwaySchools",
        back_populates="scrape_statuses",
        lazy="joined",
    )

    __table_args__ = (
        Index(
            "ix_uc_scrape_status_school_status",
            "hs_id",
            "status",
        ),
    )


class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="classification_pipeline",
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class UCDoorwayCoursesSearchIndex(Base):
    __tablename__ = "uc_doorway_courses_search_index"

    id: Mapped[int] = int_pk()

    crs_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("uc_doorway_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    hs_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    crs_academic_year: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )

    search_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    search_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )

    course: Mapped["UCDoorwayCourses"] = relationship(
        "UCDoorwayCourses",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "crs_id",
            "hs_id",
            "crs_academic_year",
            "search_type",
            "search_value",
            name="uq_uc_course_search_index",
        ),
        Index(
            "ix_search_map_inst_year_value",
            "hs_id",
            "crs_academic_year",
            "search_value",
        ),
        Index(
            "ix_search_map_inst_year_type_value",
            "hs_id",
            "crs_academic_year",
            "search_type",
            "search_value",
        ),
    )


class InstitutionAgCriteria(Base):
    __tablename__ = "institution_ag_criteria"

    id: Mapped[int] = int_pk()

    institution_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    academic_term_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("academic_term.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    year_intake: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    a_required: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    b_required: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    c_required: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    d1_required: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    d2_required: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    d_required: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    e_required: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    f_required: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    g_required: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    min_gpa_cumulative: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_gpa_english: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_gpa_math: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_gpa_science: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_csulb_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_stem_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    california_resident_min_gpa: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    # Non-resident Final Audit minimums (CSU holds non-residents to a higher bar
    # than CA residents). None falls back to the engine defaults (3.0 / 3500).
    non_resident_min_gpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    non_resident_csulb_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # HS grade levels considered for A-G counting and GPA.
    # gpa_hs_grades        -> subject GPAs (English/Math/Science), default 9-12
    # gpa_cumulative_hs_grades -> cumulative GPA / CSULB Index, default 10-12
    ag_hs_grades: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    gpa_hs_grades: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    gpa_cumulative_hs_grades: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)

    # Strict handbook A-G rule toggles (and any future per-rule settings), e.g.
    # {"strict_c_math_slots": true, "strict_a_history_anchor": false, ...}.
    # Null / missing keys => rule off (current behavior).
    rule_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "year_intake",
            name="uq_institution_ag_criteria",
        ),
    )


class InstitutionCourseAgOverride(Base):
    """Per-institution reassignment of a course's A-G category. Overrides UC
    Doorways during the admission calculation; also holds user-added courses."""

    __tablename__ = "institution_course_ag_override"

    id: Mapped[int] = int_pk()
    institution_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    course_name: Mapped[str] = mapped_column(Text, nullable=False)  # normalized (lowercased)
    discipline: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_ag: Mapped[str | None] = mapped_column(String(5), nullable=True)
    target_ag: Mapped[str] = mapped_column(String(10), nullable=False)
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id", "course_name", "discipline", name="uq_course_ag_override"
        ),
    )


class TermRuleSet(Base):
    """Structured A-G rules compiled by Gemini from an uploaded term handbook.
    We store only the extracted rules + a hash of the source document (never the
    PDF). A new approved version invalidates cached LLM verdicts."""

    __tablename__ = "term_rule_set"

    id: Mapped[int] = int_pk()
    institution_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    year_intake: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # processing | draft | approved | error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Page-level extraction progress (windowed map-reduce over the PDF).
    pages_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # GCS location of the stored handbook (per-term handbook/ folder) so the
    # background extractor can re-fetch the bytes reliably / reprocess on retry.
    document_bucket: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_gcs_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured, cited rules and any flagged-but-unsupported rules.
    rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    unsupported: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class StudentLlmVerdict(Base):
    """Cached Gemini evaluation of one student against a term ruleset version.
    Re-computed only when the ruleset version changes or the student is new."""

    __tablename__ = "student_llm_verdict"

    id: Mapped[int] = int_pk()
    student_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    institution_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ruleset_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    ruleset_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    baseline_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    per_area: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # New rules Gemini had to apply that weren't in the ruleset (crystallization).
    learned_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("student_id", "ruleset_version", name="uq_student_llm_verdict"),
    )


class StudentAgSummary(Base):
    __tablename__ = "student_ag_summary"

    id: Mapped[int] = int_pk()

    student_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("student_details.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    a_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    b_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    c_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    d1_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    d2_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    d_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    e_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    f_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    g_calc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    a_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    b_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    c_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    d1_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    d2_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    e_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    f_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    g_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    gpa_extracted: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_cumulative: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_english: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_math: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_science: Mapped[float | None] = mapped_column(Float, nullable=True)
    stem_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    csulb_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    gpa_cumulative_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_english_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_math_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa_science_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    stem_score_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    csulb_score_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    course_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    admission_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Counselor confirmation. False = auto-routed suggestion awaiting review
    # (shows in Pending Review); True = a human confirmed it on Admitted/Denied.
    # (DB column already exists; mapping was missing.)
    reviewed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        default=False,
    )

    year_intake: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

class TranscriptCourseCode(Base):
    """Per-institution course ID prefix/suffix codes (e.g. + = honors, * = non-academic)."""
    __tablename__ = "transcript_course_codes"

    id: Mapped[int] = int_pk()
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[str] = mapped_column(String(10), nullable=False, default="prefix")
    meaning: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    school_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    affects_ag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    strip_for_matching: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Automatic new transcript type / classifier training pipeline
# ---------------------------------------------------------------------------


class TranscriptSchoolType(Base):
    """
    One discovered transcript school/type, for example:
    Cypress High School -> Cypress_High_School.

    UI status mapping:
    needs_setup -> Needs Setup
    in_setup    -> In Setup
    ready       -> Ready
    failed      -> In Setup with error
    """

    __tablename__ = "transcript_school_types"

    id: Mapped[int] = int_pk()

    display_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    classifier_label: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="needs_setup",
        server_default=text("'needs_setup'"),
        index=True,
    )

    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    required_sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default=text("15")
    )

    cluster_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    gcs_raw_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    gcs_training_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)

    document_ai_processor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_ai_processor_version_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    training_operation_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_operation_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    deploy_operation_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    extractor_profile: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="generic_transcript",
        server_default=text("'generic_transcript'"),
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    samples: Mapped[list["TranscriptSchoolTypeSample"]] = relationship(
        "TranscriptSchoolTypeSample",
        back_populates="school_type",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TranscriptSchoolTypeSample(Base):
    """One transcript PDF sample belonging to a discovered school/type."""

    __tablename__ = "transcript_school_type_samples"

    id: Mapped[int] = int_pk()

    school_type_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("transcript_school_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    extraction_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("extraction_file_details.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)

    gcs_uri: Mapped[str] = mapped_column(Text, nullable=False)

    detected_school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cluster_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    school_type: Mapped["TranscriptSchoolType"] = relationship(
        "TranscriptSchoolType",
        back_populates="samples",
    )

    __table_args__ = (
        UniqueConstraint(
            "school_type_id",
            "gcs_uri",
            name="uq_school_type_sample_gcs_uri",
        ),
    )


class TranscriptClassifierRoute(Base):
    """
    Dynamic classifier routing table.

    This lets Cypress_High_School route without hardcoding it beside
    LBUSD / Mayfair / St Anthony.
    """

    __tablename__ = "transcript_classifier_routes"

    id: Mapped[int] = int_pk()

    classifier_label: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    extractor_profile: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="generic_transcript",
        server_default=text("'generic_transcript'"),
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
