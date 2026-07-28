"""persist agent run step results

Revision ID: 20260727_02
Revises: 20260727_01
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260727_02"
down_revision: Union[str, Sequence[str], None] = "20260727_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a non-sensitive JSON checkpoint map for each durable task run."""
    op.add_column(
        "agent_runs",
        sa.Column("step_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.alter_column("agent_runs", "step_results", server_default=None)


def downgrade() -> None:
    """Remove the durable step checkpoint map."""
    op.drop_column("agent_runs", "step_results")
