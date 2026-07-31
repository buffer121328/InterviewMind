"""clear inferred answers from interview-origin question bank items

Revision ID: 20260728_06
Revises: 20260728_05
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260728_06"
down_revision: Union[str, Sequence[str], None] = "20260728_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove coaching hints that were previously presented as reference answers."""
    op.execute(
        """
        UPDATE question_bank_items
        SET reference_answer = NULL
        WHERE origin_session_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Keep cleared inferred answers because their former values cannot be distinguished safely."""
