"""add session id to agent runs

Revision ID: 20260727_01
Revises: 20260716_09
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_01"
down_revision: Union[str, Sequence[str], None] = "20260716_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add an optional owner-scoped interview-session grouping key."""
    op.add_column("agent_runs", sa.Column("session_id", sa.String(), nullable=True))
    op.create_index(
        "idx_agent_runs_user_session_created",
        "agent_runs",
        ["user_id", "session_id", "created_at"],
    )


def downgrade() -> None:
    """Remove the interview-session grouping key."""
    op.drop_index("idx_agent_runs_user_session_created", table_name="agent_runs")
    op.drop_column("agent_runs", "session_id")
