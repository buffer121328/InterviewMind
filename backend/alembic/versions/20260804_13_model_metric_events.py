"""add owner-scoped model metric events

Revision ID: 20260804_13
Revises: 20260804_12
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260804_13"
down_revision: Union[str, Sequence[str], None] = "20260804_12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the credential-free local model metrics store and query indexes."""
    op.create_table(
        "model_metric_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("is_degradation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "observation_id", "event_index", name="uq_model_metric_event_observation_index"),
    )
    op.create_index("idx_model_metric_events_owner_created", "model_metric_events", ["user_id", "created_at"])
    op.create_index("idx_model_metric_events_run_created", "model_metric_events", ["run_id", "created_at"])
    op.create_index("idx_model_metric_events_owner_degradation", "model_metric_events", ["user_id", "is_degradation", "created_at"])


def downgrade() -> None:
    """Drop the local model metrics store without altering AgentRun history."""
    op.drop_table("model_metric_events")
