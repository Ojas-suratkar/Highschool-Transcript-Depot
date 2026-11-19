"""
add program_id to extraction_file_details and create program_prerequisite

Revision ID: zz_add_program_id_and_prereq
Revises: 
Create Date: 2026-03-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'zz_add_program_id_and_prereq'
down_revision = 'f22264675a69'
branch_labels = None
depends_on = None


def upgrade():
    # add program_id column to extraction_file_details
    with op.batch_alter_table('extraction_file_details') as batch_op:
        batch_op.add_column(sa.Column('program_id', sa.BigInteger(), nullable=True))
        batch_op.create_index('ix_extraction_file_program_id', ['program_id'])


def downgrade():
    with op.batch_alter_table('extraction_file_details') as batch_op:
        batch_op.drop_index('ix_extraction_file_program_id')
        batch_op.drop_column('program_id')
