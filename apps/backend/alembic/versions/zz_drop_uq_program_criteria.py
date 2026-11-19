"""drop unique constraint on program_criteria

Revision ID: zz_drop_uq_program_criteria
Revises: zz_merge_heads_92c32b3cf431_zz_add_fk
Create Date: 2026-03-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'zz_drop_uq_program_criteria'
down_revision = 'zz_merge_heads_92c32b3cf431_zz_add_fk'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # remove the unique constraint that prevents multiple prerequisite rows
    op.drop_constraint('uq_program_criteria', 'program_criteria', type_='unique')


def downgrade() -> None:
    # restore unique constraint (note: downgrading will fail if duplicate rows exist)
    op.create_unique_constraint('uq_program_criteria', 'program_criteria', ['institution_id', 'program_name', 'year_intake'])
