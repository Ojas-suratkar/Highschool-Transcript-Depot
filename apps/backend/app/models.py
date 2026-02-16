import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# Column helpers
def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(default=uuid.uuid4, primary_key=True, unique=True, index=True)


def int_pk() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True, index=True)


# ----------------
# Profiles (UUID PK)
# ----------------
class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    institution_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("institution.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    otp_last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


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
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


# ----------------
# Institution (BIGINT PK)
# ----------------
class Institution(Base):
    __tablename__ = "institution"

    id: Mapped[int] = int_pk()
    institution_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    program_criteria: Mapped[list["ProgramCriteria"]] = relationship(
        "ProgramCriteria", back_populates="institution", cascade="all, delete-orphan"
    )
    admission_criteria: Mapped[list["AdmissionCriteria"]] = relationship(
        "AdmissionCriteria", back_populates="institution", cascade="all, delete-orphan"
    )
    overall_gpa_criteria: Mapped[list["OverallGPACriteria"]] = relationship(
        "OverallGPACriteria", back_populates="institution", cascade="all, delete-orphan"
    )
    cloud_locations: Mapped[list["CloudFileLocation"]] = relationship(
        "CloudFileLocation", back_populates="institution", cascade="all, delete-orphan"
    )
    templates: Mapped[list["Templates"]] = relationship(
        "Templates", back_populates="institution", cascade="all, delete-orphan"
    )
    admission_statuses: Mapped[list["AdmissionStatus"]] = relationship(
        "AdmissionStatus", back_populates="institution", cascade="all, delete-orphan"
    )


class ProgramCriteria(Base):
    __tablename__ = "program_criteria"

    id: Mapped[int] = int_pk()
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"), nullable=False, index=True)
    program_name: Mapped[str] = mapped_column(Text, nullable=False)
    prerequisite_course_name: Mapped[str] = mapped_column(Text, nullable=False)
    prerequisite_course_gpa: Mapped[str] = mapped_column(Text, nullable=False)
    year_intake: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # app_user removed; keep updated_by_user_id as bigint nullable to preserve history
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    institution: Mapped["Institution"] = relationship("Institution", back_populates="program_criteria", lazy="joined")

    __table_args__ = (UniqueConstraint("institution_id", "program_name", "year_intake", name="uq_program_criteria"),)


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
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"), nullable=False, index=True)
    a_to_g_course_type: Mapped[AGType] = mapped_column(String(1), nullable=False, index=True)
    min_no_years_a_to_g: Mapped[str | None] = mapped_column(String(5), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    marks: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gpa: Mapped[float | None] = mapped_column(nullable=True)
    year_intake: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    institution: Mapped["Institution"] = relationship("Institution", back_populates="admission_criteria", lazy="joined")

    __table_args__ = (UniqueConstraint("institution_id", "a_to_g_course_type", "year_intake", name="uq_admission_criteria_ag"),)


class OverallGPACriteria(Base):
    __tablename__ = "overall_gpa_criteria"

    id: Mapped[int] = int_pk()
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"), nullable=False, index=True)
    min_gpa: Mapped[float] = mapped_column(nullable=False)
    year_intake: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    institution: Mapped["Institution"] = relationship("Institution", back_populates="overall_gpa_criteria", lazy="joined")

    __table_args__ = (UniqueConstraint("institution_id", "year_intake", name="uq_overall_gpa_criteria"),)


class ClassifierType(Base):
    __tablename__ = "classifier_type"

    id: Mapped[int] = int_pk()
    classifier_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    classifiers: Mapped[list["ExtractionFileDetails"]] = relationship("ExtractionFileDetails", back_populates="classifier_type", passive_deletes=True)


class CloudFileLocation(Base):
    __tablename__ = "cloud_file_location"

    id: Mapped[int] = int_pk()
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"), nullable=False, index=True)
    cloud_folder_location: Mapped[str] = mapped_column(Text, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_configured", index=True)
    year_intake: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # app_user removed; changed to bigint nullable
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_polled: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    institution: Mapped["Institution"] = relationship("Institution", back_populates="cloud_locations", lazy="joined")
    extraction_files: Mapped[list["ExtractionFileDetails"]] = relationship("ExtractionFileDetails", back_populates="cloud_location", passive_deletes=True)

    __table_args__ = (UniqueConstraint("institution_id", "is_active", name="uq_cloud_location_active_per_institution"),)


class ExtractionFileDetails(Base):
    __tablename__ = "extraction_file_details"

    id: Mapped[int] = int_pk()
    file_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    cloud_location_id: Mapped[int | None] = mapped_column(ForeignKey("cloud_file_location.id", ondelete="SET NULL"), nullable=True, index=True)
    process_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    upload_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    processed_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"), nullable=False, index=True)
    year_intake: Mapped[str | None] = mapped_column(String(50), nullable=True)
    classifier_type_id: Mapped[int] = mapped_column(ForeignKey("classifier_type.id", ondelete="RESTRICT"), nullable=False, index=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    classifier_type: Mapped["ClassifierType"] = relationship("ClassifierType", back_populates="classifiers", lazy="joined")
    cloud_location: Mapped["CloudFileLocation | None"] = relationship("CloudFileLocation", back_populates="extraction_files", lazy="joined")

    __table_args__ = (Index("ix_extraction_file_status_upload_date", "process_status", "upload_date"),)


class Templates(Base):
    __tablename__ = "templates"

    id: Mapped[int] = int_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    template_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"), nullable=False, index=True)

    # app_user removed; keep as bigint nullable
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    institution: Mapped["Institution"] = relationship("Institution", back_populates="templates", lazy="joined")

    __table_args__ = (UniqueConstraint("institution_id", "is_active", name="uq_i20_template_active_per_institution"),)


class AdmissionDecision(str, Enum):
    applied = "applied"
    under_review = "under_review"
    admitted = "admitted"
    waitlisted = "waitlisted"
    rejected = "rejected"


class AdmissionStatus(Base):
    __tablename__ = "admission_status"

    id: Mapped[int] = int_pk()
    student_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    student_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    intake_year: Mapped[str] = mapped_column(Text, nullable=False)
    application_number: Mapped[str] = mapped_column(Text, nullable=False)
    applicationDate: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    transcript_file_name: Mapped[str] = mapped_column(Text, nullable=False)
    program: Mapped[str] = mapped_column(Text, nullable=False)
    gpa: Mapped[str] = mapped_column(Text, nullable=False)
    school_graduated: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AdmissionDecision] = mapped_column(String(50), nullable=False, default=AdmissionDecision.applied)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    i20_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_required")

    institution_id_applied_for: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="RESTRICT"), nullable=False, index=True)

    # app_user removed; keep updated_by as bigint nullable
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    institution: Mapped["Institution"] = relationship("Institution", back_populates="admission_statuses", lazy="joined")

    __table_args__ = (UniqueConstraint("student_id", "institution_id_applied_for", name="uq_student_per_institution"),)


class UCDoorwaySchools(Base):
    __tablename__ = "uc_doorway_schools"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    school_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    district: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    courses: Mapped[list["UCDoorwayCourses"]] = relationship("UCDoorwayCourses", back_populates="school", cascade="all, delete-orphan")
    scrape_statuses: Mapped[list["UCDoorwayScrapeStatus"]] = relationship("UCDoorwayScrapeStatus", back_populates="school", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_uc_doorway_school_name_location", "name", "location"),)


class UCDoorwayCourses(Base):
    __tablename__ = "uc_doorway_courses"

    id: Mapped[int] = int_pk()
    school_id: Mapped[int] = mapped_column(ForeignKey("uc_doorway_schools.id", ondelete="CASCADE"), nullable=False, index=True)
    school_name: Mapped[str] = mapped_column(Text, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    course_name: Mapped[str] = mapped_column(Text, nullable=False)

    school: Mapped["UCDoorwaySchools"] = relationship("UCDoorwaySchools", back_populates="courses", lazy="joined")

    __table_args__ = (Index("ix_uc_course_school_year_ag", "school_id", "academic_year"),)


class UCDoorwayScrapeStatus(Base):
    __tablename__ = "uc_doorway_scrape_status"

    id: Mapped[int] = int_pk()
    school_id: Mapped[int] = mapped_column(ForeignKey("uc_doorway_schools.id", ondelete="CASCADE"), nullable=False, index=True)
    school_type: Mapped[str] = mapped_column(Text, nullable=False)
    school_name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    school: Mapped["UCDoorwaySchools"] = relationship("UCDoorwaySchools", back_populates="scrape_statuses", lazy="joined")

    __table_args__ = (Index("ix_uc_scrape_status_school_status", "school_id", "status"),)
