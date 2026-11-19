"""add rule_config JSONB to institution_ag_criteria

Holds the strict handbook A-G rule toggles (and future per-rule settings).
Nullable; a missing/empty config means every strict rule is off (current
behavior), so this is a safe additive change.

Revision ID: zz_ag_criteria_rule_config
Revises: 8ea32569549b
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "zz_ag_criteria_rule_config"
down_revision = "8ea32569549b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institution_ag_criteria",
        sa.Column("rule_config", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("institution_ag_criteria", "rule_config")
