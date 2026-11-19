"""Add institution_ag_criteria and student_ag_summary tables

Revision ID: zz_add_ag_and_summary
Revises: zz_create_program_versions
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "zz_add_ag_and_summary"
down_revision = ("zz_add_microsoft_oid_to_profiles", "zz_course_mapping_trigger")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institution_ag_criteria",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("year_intake", sa.String(20), nullable=False),
        sa.Column("a_required", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("b_required", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("c_required", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("d1_required", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("d2_required", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("d_required", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("e_required", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("f_required", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("g_required", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("min_gpa_cumulative", sa.Float(), nullable=True),
        sa.Column("min_gpa_english", sa.Float(), nullable=True),
        sa.Column("min_gpa_math", sa.Float(), nullable=True),
        sa.Column("min_gpa_science", sa.Float(), nullable=True),
        sa.Column("min_csulb_score", sa.Float(), nullable=True),
        sa.Column("min_stem_score", sa.Float(), nullable=True),
        sa.Column("california_resident_min_gpa", sa.Float(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"], ["institution.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution_id", "year_intake", name="uq_institution_ag_criteria"
        ),
    )
    op.create_index(
        "ix_institution_ag_criteria_institution_id",
        "institution_ag_criteria",
        ["institution_id"],
    )
    op.create_index(
        "ix_institution_ag_criteria_year_intake",
        "institution_ag_criteria",
        ["year_intake"],
    )

    op.create_table(
        "student_ag_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("a_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("b_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("c_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("d1_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("d2_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("d_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("e_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("f_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("g_calc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("a_override", sa.Float(), nullable=True),
        sa.Column("b_override", sa.Float(), nullable=True),
        sa.Column("c_override", sa.Float(), nullable=True),
        sa.Column("d1_override", sa.Float(), nullable=True),
        sa.Column("d2_override", sa.Float(), nullable=True),
        sa.Column("d_override", sa.Float(), nullable=True),
        sa.Column("e_override", sa.Float(), nullable=True),
        sa.Column("f_override", sa.Float(), nullable=True),
        sa.Column("g_override", sa.Float(), nullable=True),
        sa.Column("gpa_extracted", sa.Float(), nullable=True),
        sa.Column("gpa_cumulative", sa.Float(), nullable=True),
        sa.Column("gpa_english", sa.Float(), nullable=True),
        sa.Column("gpa_math", sa.Float(), nullable=True),
        sa.Column("gpa_science", sa.Float(), nullable=True),
        sa.Column("stem_score", sa.Float(), nullable=True),
        sa.Column("csulb_score", sa.Float(), nullable=True),
        sa.Column("course_overrides", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["student_details.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", name="uq_student_ag_summary"),
    )
    op.create_index(
        "ix_student_ag_summary_student_id",
        "student_ag_summary",
        ["student_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("student_ag_summary")
    op.drop_table("institution_ag_criteria")
