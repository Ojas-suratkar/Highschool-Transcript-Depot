"""term_rule_set: store handbook GCS location

Revision ID: zz_term_rule_set_gcs
Revises: zz_term_rule_set_status
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa


revision = "zz_term_rule_set_gcs"
down_revision = "zz_term_rule_set_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("term_rule_set", sa.Column("document_bucket", sa.Text, nullable=True))
    op.add_column("term_rule_set", sa.Column("document_gcs_path", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("term_rule_set", "document_gcs_path")
    op.drop_column("term_rule_set", "document_bucket")
