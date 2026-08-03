"""Create the user_feedback table for satisfaction tracking.

Revision ID: 20260801_10
Revises: 20260730_09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260801_10"
down_revision: Union[str, Sequence[str], None] = "20260730_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the satisfaction feedback table (owner + ref-key idempotent)."""

    op.create_table(
        "user_feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("ref_key", sa.String(length=256), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("satisfied_aspects", JSONB(), nullable=False),
        sa.Column("dissatisfied_aspects", JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "agent_type", "ref_key", name="uq_user_feedback_owner_ref"
        ),
    )
    op.create_index("ix_user_feedback_user_id", "user_feedback", ["user_id"], unique=False)


def downgrade() -> None:
    """Drop the satisfaction feedback table."""

    op.drop_index("ix_user_feedback_user_id", table_name="user_feedback")
    op.drop_table("user_feedback")
