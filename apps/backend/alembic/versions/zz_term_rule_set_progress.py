"""term_rule_set: page-level extraction progress

Revision ID: zz_term_rule_set_progress
Revises: zz_term_rule_set_gcs
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa


revision = "zz_term_rule_set_progress"
down_revision = "zz_term_rule_set_gcs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("term_rule_set", sa.Column("pages_total", sa.Integer, nullable=True))
    op.add_column("term_rule_set", sa.Column("pages_done", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("term_rule_set", "pages_done")
    op.drop_column("term_rule_set", "pages_total")
