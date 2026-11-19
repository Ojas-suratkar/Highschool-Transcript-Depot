"""Add final_course_details_id column to mapping table

Revision ID: c3ccf2bea1dc
Revises: 695a9af430b3
Create Date: 2026-06-05 19:40:14.575871

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3ccf2bea1dc'
down_revision: Union[str, None] = '695a9af430b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add final_course_details_id column if it doesn't exist
    op.add_column('course_detail_mapping_uc_doorway_courses',
                  sa.Column('final_course_details_id', sa.BigInteger(), nullable=True))

    # Create index on final_course_details_id
    op.create_index(
        op.f('ix_course_detail_mapping_uc_doorway_courses_final_course_details_id'),
        'course_detail_mapping_uc_doorway_courses',
        ['final_course_details_id'],
        unique=True
    )

    # Create foreign key constraint
    op.create_foreign_key(
        'fk_course_detail_mapping_final_course_details_id',
        'course_detail_mapping_uc_doorway_courses',
        'final_course_details',
        ['final_course_details_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # Make course_details_id nullable (since we now use final_course_details_id)
    op.alter_column('course_detail_mapping_uc_doorway_courses', 'course_details_id',
               existing_type=sa.BIGINT(),
               nullable=True)


def downgrade() -> None:
    # Reverse the changes
    op.alter_column('course_detail_mapping_uc_doorway_courses', 'course_details_id',
               existing_type=sa.BIGINT(),
               nullable=False)

    op.drop_constraint('fk_course_detail_mapping_final_course_details_id',
                      'course_detail_mapping_uc_doorway_courses',
                      type_='foreignkey')

    op.drop_index(
        op.f('ix_course_detail_mapping_uc_doorway_courses_final_course_details_id'),
        'course_detail_mapping_uc_doorway_courses'
    )

    op.drop_column('course_detail_mapping_uc_doorway_courses', 'final_course_details_id')
