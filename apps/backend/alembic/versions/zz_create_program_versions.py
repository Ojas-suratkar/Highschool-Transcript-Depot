"""create program_versions table

Revision ID: zz_create_program_versions
Revises: zz_drop_uq_program_criteria
Create Date: 2026-03-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'zz_create_program_versions'
down_revision = 'zz_drop_uq_program_criteria'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'program_versions',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('program_criteria_id', sa.BigInteger(), sa.ForeignKey('program_criteria.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), sa.ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('notes', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('program_versions')
