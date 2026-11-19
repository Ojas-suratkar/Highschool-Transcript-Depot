"""Add admission_decision and year_intake to student_ag_summary

Revision ID: zz_summary_decision_term
Revises: zz_add_ag_and_summary
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision = "zz_summary_decision_term"
down_revision = "zz_add_ag_and_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("student_ag_summary", sa.Column("admission_decision", sa.String(20), nullable=True))
    op.add_column("student_ag_summary", sa.Column("year_intake", sa.String(20), nullable=True))
    op.create_index("ix_student_ag_summary_year_intake", "student_ag_summary", ["year_intake"])


def downgrade() -> None:
    op.drop_index("ix_student_ag_summary_year_intake", "student_ag_summary")
    op.drop_column("student_ag_summary", "year_intake")
    op.drop_column("student_ag_summary", "admission_decision")
