"""add replayable agent run events

Revision ID: 20260716_04
Revises: 20260716_03
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260716_04"
down_revision: Union[str, Sequence[str], None] = "20260716_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """执行 `upgrade` 相关逻辑。"""
    op.add_column("agent_runs", sa.Column("agent_name", sa.String(), nullable=False, server_default="unknown"))
    op.add_column("agent_runs", sa.Column("agent_version", sa.String(), nullable=False, server_default="1"))
    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
    )
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])
    op.create_index("idx_agent_run_events_run_created", "agent_run_events", ["run_id", "created_at"])


def downgrade() -> None:
    """执行 `downgrade` 相关逻辑。"""
    op.drop_index("idx_agent_run_events_run_created", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_id", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    op.drop_column("agent_runs", "agent_version")
    op.drop_column("agent_runs", "agent_name")
