"""backfill legacy generated interview titles

Revision ID: 20260728_05
Revises: 20260727_04
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260728_05"
down_revision: Union[str, Sequence[str], None] = "20260727_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace only titles produced by known legacy generators, preserving manual names."""
    op.execute(
        """
        UPDATE sessions
        SET title = concat(
            to_char(created_at, 'YYYY-MM-DD HH24:MI'),
            ' · ',
            CASE COALESCE(round_type, 'tech_initial')
                WHEN 'tech_deep' THEN '深度技术面'
                WHEN 'hr_comprehensive' THEN 'HR 综合面'
                ELSE '综合面'
            END,
            ' · ',
            COALESCE(
                max_questions,
                CASE COALESCE(round_type, 'tech_initial')
                    WHEN 'tech_deep' THEN 20
                    WHEN 'hr_comprehensive' THEN 5
                    ELSE 10
                END
            ),
            '题 · 第',
            GREATEST(COALESCE(round_index, 1), 1),
            '轮'
        )
        WHERE
            title IN ('新模拟面试', '新面试', '模拟面试')
            OR title ~ '^(模拟面试|辅导模式) - [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$'
            OR title = concat(
                CASE
                    WHEN length(COALESCE(job_description, '')) > 15
                        THEN substring(COALESCE(job_description, '') FROM 1 FOR 15) || '...'
                    ELSE COALESCE(job_description, '')
                END,
                ' - 第',
                GREATEST(COALESCE(round_index, 1), 1),
                '轮'
            )
            OR title LIKE '% (语音版)'
        """
    )


def downgrade() -> None:
    """Keep backfilled display titles because the former generated text is not recoverable."""
