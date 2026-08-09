"""add question bank priority

Revision ID: 20260809_14
Revises: 20260804_13
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_14"
down_revision: str | Sequence[str] | None = "20260804_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a constrained priority used by round-aware question selection."""
    op.add_column(
        "question_bank_items",
        sa.Column("priority", sa.String(), nullable=False, server_default="low"),
    )
    op.create_check_constraint(
        "ck_question_bank_priority",
        "question_bank_items",
        "priority IN ('required', 'high', 'low')",
    )
    op.create_index(
        "idx_question_bank_selection",
        "question_bank_items",
        ["user_id", "question_type", "priority", "usage_count"],
    )


def downgrade() -> None:
    """Remove the priority selection contract."""
    op.drop_index("idx_question_bank_selection", table_name="question_bank_items")
    op.drop_constraint("ck_question_bank_priority", "question_bank_items", type_="check")
    op.drop_column("question_bank_items", "priority")
