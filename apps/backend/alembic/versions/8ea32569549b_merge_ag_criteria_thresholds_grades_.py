"""merge ag-criteria thresholds/grades branch into mainline

Revision ID: 8ea32569549b
Revises: zz_ag_criteria_gpa_cumulative_grades, zz_final_course_mapping_trigger
Create Date: 2026-06-27 19:15:40.641158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ea32569549b'
down_revision: Union[str, None] = ('zz_ag_criteria_gpa_cumulative_grades', 'zz_final_course_mapping_trigger')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
