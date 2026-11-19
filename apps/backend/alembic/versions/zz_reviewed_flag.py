"""Add reviewed column to student_ag_summary

Revision ID: zz_reviewed_flag
Revises: zz_transcript_course_codes_school_name
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa

revision = "zz_reviewed_flag"
down_revision = "zz_transcript_course_codes_school_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "student_ag_summary",
        sa.Column(
            "reviewed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("student_ag_summary", "reviewed")
