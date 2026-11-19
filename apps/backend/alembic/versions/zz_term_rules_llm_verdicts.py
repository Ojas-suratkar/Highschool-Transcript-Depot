"""term_rule_set (LLM-compiled A-G rules) + student_llm_verdict (cached verdicts)

Revision ID: zz_term_rules_llm_verdicts
Revises: zz_course_ag_overrides
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "zz_term_rules_llm_verdicts"
down_revision = "zz_course_ag_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "term_rule_set",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("institution_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("year_intake", sa.String(40), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("document_name", sa.Text, nullable=True),
        sa.Column("document_hash", sa.String(64), nullable=True),
        sa.Column("rules", JSONB, nullable=True),
        sa.Column("unsupported", JSONB, nullable=True),
        sa.Column("approved_by", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "student_llm_verdict",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("institution_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("ruleset_id", sa.BigInteger, nullable=True, index=True),
        sa.Column("ruleset_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("baseline_decision", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("per_area", JSONB, nullable=True),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("learned_rules", JSONB, nullable=True),
        sa.Column("overridden", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("override_decision", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("student_id", "ruleset_version", name="uq_student_llm_verdict"),
    )


def downgrade() -> None:
    op.drop_table("student_llm_verdict")
    op.drop_table("term_rule_set")
