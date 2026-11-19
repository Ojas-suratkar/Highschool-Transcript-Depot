"""fix cloud folder uniqueness scope

Revision ID: 20260310_fix_cloud_folder_unique_scope
Revises: 20260216_models_v2_relationship_fixes, zz_create_program_versions
Create Date: 2026-03-10 23:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260310_fix_cloud_folder_unique_scope"
down_revision = ("20260216_models_v2_relationship_fixes", "zz_create_program_versions")
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            UPDATE cloud_file_location
            SET is_active = FALSE
            WHERE deleted_at IS NOT NULL AND is_active = TRUE
            """
        )
    )
    op.drop_constraint(
        "uq_cloud_location_active_per_institution",
        "cloud_file_location",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_cloud_location_active_per_institution",
        "cloud_file_location",
        ["institution_id", "program_name", "is_active", "year_intake"],
    )


def downgrade():
    op.drop_constraint(
        "uq_cloud_location_active_per_institution",
        "cloud_file_location",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_cloud_location_active_per_institution",
        "cloud_file_location",
        ["program_name", "is_active", "year_intake"],
    )
