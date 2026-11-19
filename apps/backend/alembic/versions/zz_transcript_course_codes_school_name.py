"""Add school_name column to transcript_course_codes

Revision ID: zz_transcript_course_codes_school_name
Revises: zz_transcript_course_codes
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

revision = "zz_transcript_course_codes_school_name"
down_revision = "zz_transcript_course_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transcript_course_codes",
        sa.Column("school_name", sa.String(300), nullable=True),
    )
    op.create_index(
        "ix_transcript_course_codes_school_name",
        "transcript_course_codes",
        ["school_name"],
    )

    # Drop the old (institution_id, code, position) unique constraint
    op.drop_constraint("uq_transcript_course_codes", "transcript_course_codes", type_="unique")

    # Add new unique constraint including school_name.
    # Note: rows with NULL school_name are NOT covered by this constraint (SQL NULL != NULL),
    # so duplicate institution-wide codes are prevented at the application layer.
    op.create_unique_constraint(
        "uq_transcript_course_codes",
        "transcript_course_codes",
        ["institution_id", "school_name", "code", "position"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_transcript_course_codes", "transcript_course_codes", type_="unique")
    op.drop_index("ix_transcript_course_codes_school_name", "transcript_course_codes")
    op.drop_column("transcript_course_codes", "school_name")
    op.create_unique_constraint(
        "uq_transcript_course_codes",
        "transcript_course_codes",
        ["institution_id", "code", "position"],
    )
