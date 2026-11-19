"""Add academic_term_id FK to institution_ag_criteria

Revision ID: zz_ag_criteria_term_fk
Revises: zz_compute_ag_summary_fn
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision = "zz_ag_criteria_term_fk"
down_revision = "zz_compute_ag_summary_fn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institution_ag_criteria",
        sa.Column("academic_term_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_institution_ag_criteria_academic_term_id",
        "institution_ag_criteria",
        ["academic_term_id"],
    )
    # Populate from existing data where term_name matches year_intake within institution
    op.execute(
        """
        UPDATE institution_ag_criteria iac
        SET    academic_term_id = at.id
        FROM   academic_term at
        WHERE  at.institution_id = iac.institution_id
          AND  at.term_name      = iac.year_intake
        """
    )
    op.create_foreign_key(
        "fk_institution_ag_criteria_academic_term",
        "institution_ag_criteria",
        "academic_term",
        ["academic_term_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_institution_ag_criteria_academic_term", "institution_ag_criteria", type_="foreignkey"
    )
    op.drop_index("ix_institution_ag_criteria_academic_term_id", "institution_ag_criteria")
    op.drop_column("institution_ag_criteria", "academic_term_id")
