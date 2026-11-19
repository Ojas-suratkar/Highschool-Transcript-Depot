"""add title normalization functions

Revision ID: 1daa7f8ea639
Revises: 34a87936b4ec
Create Date: 2026-04-21 12:50:50.732892

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1daa7f8ea639"
down_revision: Union[str, None] = "34a87936b4ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.normalize_course_title(t text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT trim(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            translate(
                                lower(coalesce(t, '')),
                                '()[]{}',
                                '      '
                            ),
                            '&',
                            ' and ',
                            'g'
                        ),
                        '[^a-z0-9]+',
                        ' ',
                        'g'
                    ),
                    '\\s+',
                    ' ',
                    'g'
                )
            );
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.canonical_title_key(t text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT array_to_string(
                ARRAY(
                    SELECT tok
                    FROM unnest(
                        regexp_split_to_array(public.normalize_course_title(t), '\\s+')
                    ) AS tok
                    WHERE tok <> ''
                      AND tok <> 'and'
                    ORDER BY tok
                ),
                ' '
            );
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.compact_title_key(t text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT replace(public.normalize_course_title(t), ' ', '');
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.compact_title_key(text);")
    op.execute("DROP FUNCTION IF EXISTS public.canonical_title_key(text);")
    op.execute("DROP FUNCTION IF EXISTS public.normalize_course_title(text);")