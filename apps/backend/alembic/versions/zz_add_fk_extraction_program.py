"""
add foreign key from extraction_file_details.program_id -> program_criteria.id

Revision ID: zz_add_fk_extraction_program
Revises: zz_add_program_id_and_prereq
Create Date: 2026-03-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'zz_add_fk_extraction_program'
down_revision = 'zz_add_program_id_and_prereq'
branch_labels = None
depends_on = None


def upgrade():
    # Create FK from extraction_file_details.program_id -> program_criteria.id
    op.create_foreign_key(
        'fk_extraction_file_program_id',
        'extraction_file_details',
        'program_criteria',
        ['program_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_extraction_file_program_id', 'extraction_file_details', type_='foreignkey')
