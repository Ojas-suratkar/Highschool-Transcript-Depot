"""Add transcript_course_codes table

Revision ID: zz_transcript_course_codes
Revises: zz_summary_decision_term
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

revision = "zz_transcript_course_codes"
down_revision = "zz_summary_decision_term"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand alembic_version.version_num — the default varchar(32) is too short
    # for revision IDs like "zz_transcript_course_codes_school_name" (40 chars).
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64)")

    op.create_table(
        "transcript_course_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institution.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("position", sa.String(10), nullable=False, server_default="prefix"),
        sa.Column("meaning", sa.String(30), nullable=False, server_default="other"),
        sa.Column("label", sa.String(100), nullable=False, server_default=""),
        sa.Column("affects_ag", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("strip_for_matching", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_transcript_course_codes_institution_id", "transcript_course_codes", ["institution_id"])
    op.create_unique_constraint(
        "uq_transcript_course_codes",
        "transcript_course_codes",
        ["institution_id", "code", "position"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_transcript_course_codes", "transcript_course_codes", type_="unique")
    op.drop_index("ix_transcript_course_codes_institution_id", "transcript_course_codes")
    op.drop_table("transcript_course_codes")
