"""create users and otp_challenges tables

Revision ID: 0001
Revises: 
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_extension('uuid-ossp', if_not_exists=True)

    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('contact', sa.Text, nullable=True, unique=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'otp_challenges',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('destination', sa.Text, nullable=False),
        sa.Column('channel', sa.Text, nullable=False),
        sa.Column('otp_hash', sa.Text, nullable=False),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer, nullable=False, server_default='5'),
        sa.Column('last_sent_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('verified_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('otp_challenges')
    op.drop_table('users')
