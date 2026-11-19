"""term_rule_set: add error + started_at for async extraction progress

Revision ID: zz_term_rule_set_status
Revises: zz_term_rules_llm_verdicts
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa


revision = "zz_term_rule_set_status"
down_revision = "zz_term_rules_llm_verdicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("term_rule_set", sa.Column("error", sa.Text, nullable=True))
    op.add_column(
        "term_rule_set",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("term_rule_set", "started_at")
    op.drop_column("term_rule_set", "error")
