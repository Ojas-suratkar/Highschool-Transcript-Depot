"""Add non-resident Final Audit thresholds to institution_ag_criteria

Adds non_resident_min_gpa and non_resident_csulb_score so the non-resident
admission thresholds are configurable from the Institutional Criteria page
instead of being hardcoded. Idempotent (ADD COLUMN IF NOT EXISTS) so it is safe
to run regardless of the branched migration history.

Revision ID: zz_ag_criteria_non_resident
Revises: zz_ag_criteria_defaults_backfill
Create Date: 2026-06-25
"""

from alembic import op

revision = "zz_ag_criteria_non_resident"
down_revision = "zz_ag_criteria_defaults_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE institution_ag_criteria "
        "ADD COLUMN IF NOT EXISTS non_resident_min_gpa DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE institution_ag_criteria "
        "ADD COLUMN IF NOT EXISTS non_resident_csulb_score DOUBLE PRECISION"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE institution_ag_criteria DROP COLUMN IF EXISTS non_resident_csulb_score"
    )
    op.execute(
        "ALTER TABLE institution_ag_criteria DROP COLUMN IF EXISTS non_resident_min_gpa"
    )
