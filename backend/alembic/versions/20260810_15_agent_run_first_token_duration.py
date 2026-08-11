"""add task-level first-token duration

Revision ID: 20260810_15
Revises: 20260809_14
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_15"
down_revision: str | Sequence[str] | None = "20260809_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable real TTFT telemetry without backfilling historical runs."""

    op.add_column(
        "agent_runs",
        sa.Column("first_token_duration_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Remove the task-level TTFT column without altering model metric events."""

    op.drop_column("agent_runs", "first_token_duration_ms")
