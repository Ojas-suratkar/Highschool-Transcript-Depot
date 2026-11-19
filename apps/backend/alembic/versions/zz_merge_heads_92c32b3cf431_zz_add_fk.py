"""
Merge heads 92c32b3cf431 and zz_add_fk_extraction_program

Revision ID: zz_merge_heads_92c32b3cf431_zz_add_fk
Revises: 92c32b3cf431, zz_add_fk_extraction_program
Create Date: 2026-03-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'zz_merge_heads_92c32b3cf431_zz_add_fk'
down_revision = ('92c32b3cf431', 'zz_add_fk_extraction_program')
branch_labels = None
depends_on = None


def upgrade():
    # merge revision - no DB changes
    pass


def downgrade():
    # nothing to undo for merge
    pass
