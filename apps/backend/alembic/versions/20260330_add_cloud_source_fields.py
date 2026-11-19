"""add source columns to cloud_file_location

Revision ID: add_cloud_source_fields
Revises: 20260310_fix_cloud_folder_unique_scope
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_cloud_source_fields'
down_revision = '20260310_fix_cloud_folder_unique_scope'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cloud_file_location') as batch:
        batch.add_column(sa.Column('source_type', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('source_uri', sa.Text(), nullable=True))
        batch.add_column(sa.Column('last_poll_status', sa.Text(), nullable=True))
    # set defaults to 'gcs' for existing rows
    op.execute("UPDATE cloud_file_location SET source_type = 'gcs' WHERE source_type IS NULL")


def downgrade():
    with op.batch_alter_table('cloud_file_location') as batch:
        batch.drop_column('last_poll_status')
        batch.drop_column('source_uri')
        batch.drop_column('source_type')
