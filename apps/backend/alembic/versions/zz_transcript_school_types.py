"""transcript_school_types + samples + classifier routes (new-type onboarding)

Revision ID: zz_transcript_school_types
Revises: zz_term_rule_set_progress
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa


revision = "zz_transcript_school_types"
down_revision = "zz_term_rule_set_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The friend's rollout created these tables directly in the DB; guard each
    # create so the migration is idempotent across environments.
    from sqlalchemy import inspect as _inspect
    insp = _inspect(op.get_bind())
    existing = set(insp.get_table_names())

    if "transcript_school_types" in existing:
        pass
    else:
        _create_school_types()
    if "transcript_school_type_samples" not in existing:
        _create_samples()
    if "transcript_classifier_routes" not in existing:
        _create_routes()


def _create_school_types() -> None:
    op.create_table(
        "transcript_school_types",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(255), nullable=False, index=True),
        sa.Column("normalized_name", sa.String(255), nullable=False, index=True),
        sa.Column("classifier_label", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="needs_setup", index=True),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("required_sample_count", sa.Integer, nullable=False, server_default="15"),
        sa.Column("cluster_confidence", sa.Float, nullable=True),
        sa.Column("gcs_raw_prefix", sa.Text, nullable=True),
        sa.Column("gcs_training_prefix", sa.Text, nullable=True),
        sa.Column("document_ai_processor_id", sa.String(255), nullable=True),
        sa.Column("document_ai_processor_version_id", sa.String(255), nullable=True),
        sa.Column("training_operation_name", sa.Text, nullable=True),
        sa.Column("import_operation_name", sa.Text, nullable=True),
        sa.Column("deploy_operation_name", sa.Text, nullable=True),
        sa.Column("extractor_profile", sa.String(100), nullable=False, server_default="generic_transcript"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def _create_samples() -> None:
    op.create_table(
        "transcript_school_type_samples",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("school_type_id", sa.BigInteger, sa.ForeignKey("transcript_school_types.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("extraction_file_id", sa.BigInteger, sa.ForeignKey("extraction_file_details.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("source_file", sa.Text, nullable=True),
        sa.Column("gcs_uri", sa.Text, nullable=False),
        sa.Column("detected_school_name", sa.String(255), nullable=True),
        sa.Column("cluster_id", sa.String(255), nullable=True, index=True),
        sa.Column("cluster_confidence", sa.Float, nullable=True),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("school_type_id", "gcs_uri", name="uq_school_type_sample_gcs_uri"),
    )

def _create_routes() -> None:
    op.create_table(
        "transcript_classifier_routes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("classifier_label", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("extractor_profile", sa.String(100), nullable=False, server_default="generic_transcript"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("transcript_classifier_routes")
    op.drop_table("transcript_school_type_samples")
    op.drop_table("transcript_school_types")
