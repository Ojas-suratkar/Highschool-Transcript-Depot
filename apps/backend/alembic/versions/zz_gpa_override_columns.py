"""Add GPA override columns to student_ag_summary and backfill

Revision ID: zz_gpa_override_columns
Revises: zz_ag_criteria_term_fk
Branch Labels: None
Depends On: None
"""

import sqlalchemy as sa
from alembic import op

revision = "zz_gpa_override_columns"
down_revision = "zz_ag_criteria_term_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("student_ag_summary", sa.Column("gpa_cumulative_override", sa.Float(), nullable=True))
    op.add_column("student_ag_summary", sa.Column("gpa_english_override",    sa.Float(), nullable=True))
    op.add_column("student_ag_summary", sa.Column("gpa_math_override",       sa.Float(), nullable=True))
    op.add_column("student_ag_summary", sa.Column("gpa_science_override",    sa.Float(), nullable=True))
    op.add_column("student_ag_summary", sa.Column("stem_score_override",     sa.Float(), nullable=True))
    op.add_column("student_ag_summary", sa.Column("csulb_score_override",    sa.Float(), nullable=True))

    # Backfill AG overrides for existing rows (override = calc where override is null)
    op.execute("""
        UPDATE student_ag_summary SET
            a_override  = COALESCE(a_override,  a_calc),
            b_override  = COALESCE(b_override,  b_calc),
            c_override  = COALESCE(c_override,  c_calc),
            d1_override = COALESCE(d1_override, d1_calc),
            d2_override = COALESCE(d2_override, d2_calc),
            d_override  = COALESCE(d_override,  d_calc),
            e_override  = COALESCE(e_override,  e_calc),
            f_override  = COALESCE(f_override,  f_calc),
            g_override  = COALESCE(g_override,  g_calc),
            gpa_cumulative_override = gpa_cumulative,
            gpa_english_override    = gpa_english,
            gpa_math_override       = gpa_math,
            gpa_science_override    = gpa_science,
            stem_score_override     = stem_score,
            csulb_score_override    = csulb_score
    """)


def downgrade() -> None:
    op.drop_column("student_ag_summary", "csulb_score_override")
    op.drop_column("student_ag_summary", "stem_score_override")
    op.drop_column("student_ag_summary", "gpa_science_override")
    op.drop_column("student_ag_summary", "gpa_math_override")
    op.drop_column("student_ag_summary", "gpa_english_override")
    op.drop_column("student_ag_summary", "gpa_cumulative_override")
