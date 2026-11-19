"""merge heads for cloud source

Revision ID: 400a0b51220e
Revises: add_cloud_source_fields, 217dfc5a0d6c
Create Date: 2026-03-30 10:40:42.921119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '400a0b51220e'
down_revision: Union[str, None] = ('add_cloud_source_fields', '217dfc5a0d6c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
