"""institution course A-G overrides + searchable UC Doorways catalog

- pg_trgm + a materialized catalog of DISTINCT (name, A-G, discipline) combos
  (~95k rows out of 3.6M) with a trigram index, so the Course Mapping search is
  fast instead of a 7s full scan.
- institution_course_ag_override: per-institution reassignment of a course's A-G
  category (overrides UC Doorways), plus user-added courses.

Revision ID: zz_course_ag_overrides
Revises: zz_ag_criteria_rule_config
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "zz_course_ag_overrides"
down_revision = "zz_ag_criteria_rule_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "institution_course_ag_override",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("institution_id", sa.BigInteger, nullable=False, index=True),
        # Normalized UC Doorways course name (lowercased on write).
        sa.Column("course_name", sa.Text, nullable=False),
        sa.Column("discipline", sa.Text, nullable=True),
        # What UC Doorways said (for display / audit) and the override target.
        sa.Column("original_ag", sa.String(5), nullable=True),
        sa.Column("target_ag", sa.String(10), nullable=False),
        sa.Column("is_new", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("institution_id", "course_name", "discipline", name="uq_course_ag_override"),
    )

    # Distinct-course catalog for the search UI (small + trigram-indexed).
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS uc_doorway_course_catalog AS
        SELECT
            crs_description AS course_name,
            crs_ag_category_letter AS ag_letter,
            crs_ag_category_description AS ag_description,
            crs_discipline AS discipline,
            COUNT(*)::bigint AS occurrences
        FROM uc_doorway_courses
        WHERE crs_description IS NOT NULL AND crs_description <> ''
        GROUP BY crs_description, crs_ag_category_letter, crs_ag_category_description, crs_discipline
        WITH DATA
        """
    )
    op.execute(
        "CREATE INDEX ix_uc_catalog_name_trgm ON uc_doorway_course_catalog "
        "USING gin (lower(course_name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_uc_catalog_unique ON uc_doorway_course_catalog "
        "(course_name, ag_letter, discipline)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS uc_doorway_course_catalog")
    op.drop_table("institution_course_ag_override")
