"""Merge migration heads

Revision ID: 695a9af430b3
Revises: zz_ag_criteria_defaults_backfill, zz_gpa_override_columns, zz_reviewed_flag
Create Date: 2026-06-04 11:30:39.212935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '695a9af430b3'
down_revision: Union[str, None] = ('zz_ag_criteria_defaults_backfill', 'zz_gpa_override_columns', 'zz_reviewed_flag')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
