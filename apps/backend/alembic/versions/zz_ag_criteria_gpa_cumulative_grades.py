"""Add gpa_cumulative_hs_grades to institution_ag_criteria

Splits the single GPA grade-level selection into two: gpa_hs_grades now governs
the subject GPAs (English/Math/Science, default 9-12) and the new
gpa_cumulative_hs_grades governs the cumulative GPA / CSULB Index (default 10-12).
Idempotent so it is safe regardless of the branched migration history.

Revision ID: zz_ag_criteria_gpa_cumulative_grades
Revises: zz_ag_criteria_non_resident
Create Date: 2026-06-27
"""

from alembic import op

revision = "zz_ag_criteria_gpa_cumulative_grades"
down_revision = "zz_ag_criteria_non_resident"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE institution_ag_criteria "
        "ADD COLUMN IF NOT EXISTS gpa_cumulative_hs_grades INTEGER[]"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE institution_ag_criteria DROP COLUMN IF EXISTS gpa_cumulative_hs_grades"
    )
