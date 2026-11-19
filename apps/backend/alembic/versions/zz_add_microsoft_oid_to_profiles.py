"""add microsoft_oid to profiles

Revision ID: zz_add_microsoft_oid_to_profiles
Revises: zz_merge_heads_92c32b3cf431_zz_add_fk
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "zz_add_microsoft_oid_to_profiles"
down_revision: Union[str, None] = "fc0a7e3f10aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("microsoft_oid", sa.String(255), nullable=True),
    )
    op.create_index("ix_profiles_microsoft_oid", "profiles", ["microsoft_oid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_profiles_microsoft_oid", table_name="profiles")
    op.drop_column("profiles", "microsoft_oid")
