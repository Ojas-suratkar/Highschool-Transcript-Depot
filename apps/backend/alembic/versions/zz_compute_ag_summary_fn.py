"""Add compute_student_ag_summary SQL function

Revision ID: zz_compute_ag_summary_fn
Revises: zz_summary_decision_term
Create Date: 2026-05-19
"""

from alembic import op
from pathlib import Path

revision = "zz_compute_ag_summary_fn"
down_revision = "zz_summary_decision_term"
branch_labels = None
depends_on = None

_SQL_FILE = Path(__file__).parent.parent.parent / "fix_ag_fn.sql"

_DROP_FN = "DROP FUNCTION IF EXISTS compute_student_ag_summary(BIGINT);"


def upgrade() -> None:
    sql = _SQL_FILE.read_text()
    op.execute(sql)


def downgrade() -> None:
    op.execute(_DROP_FN)
