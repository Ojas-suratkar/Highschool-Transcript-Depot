"""Backfill default hs_grades and GPA thresholds on institution_ag_criteria

Revision ID: zz_ag_criteria_defaults_backfill
Revises: zz_ag_criteria_hs_grades
Create Date: 2026-05-27
"""

from alembic import op

revision = "zz_ag_criteria_defaults_backfill"
down_revision = "zz_ag_criteria_hs_grades"
branch_labels = None
depends_on = None

DEFAULT_HS_GRADES = "{8,9,10,11,12}"


def upgrade() -> None:
    op.execute(f"""
        UPDATE institution_ag_criteria
        SET
            ag_hs_grades  = '{DEFAULT_HS_GRADES}',
            gpa_hs_grades = '{DEFAULT_HS_GRADES}',
            min_gpa_cumulative          = COALESCE(min_gpa_cumulative,          3.0),
            min_gpa_english             = COALESCE(min_gpa_english,             3.0),
            min_gpa_math                = COALESCE(min_gpa_math,                3.0),
            min_gpa_science             = COALESCE(min_gpa_science,             3.0),
            min_csulb_score             = COALESCE(min_csulb_score,             3200),
            min_stem_score              = COALESCE(min_stem_score,              3.0),
            california_resident_min_gpa = COALESCE(california_resident_min_gpa, 2.5)
    """)


def downgrade() -> None:
    pass
