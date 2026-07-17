"""add agent run observability fields

Revision ID: 20260716_07
Revises: 20260716_06
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260716_07"
down_revision: Union[str, Sequence[str], None] = "20260716_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("trace_id", sa.String(), nullable=True))
    op.add_column("agent_runs", sa.Column("model_provider", sa.String(), nullable=True))
    op.add_column("agent_runs", sa.Column("model_name", sa.String(), nullable=True))
    op.add_column("agent_runs", sa.Column("model_member", sa.String(), nullable=True))
    op.add_column("agent_runs", sa.Column("request_latency_ms", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("fallback_count", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("fallback_path", sa.JSON(), nullable=True))
    op.add_column("agent_runs", sa.Column("estimated_cost_usd", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("model_error_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "model_error_type")
    op.drop_column("agent_runs", "estimated_cost_usd")
    op.drop_column("agent_runs", "fallback_path")
    op.drop_column("agent_runs", "fallback_count")
    op.drop_column("agent_runs", "output_tokens")
    op.drop_column("agent_runs", "input_tokens")
    op.drop_column("agent_runs", "request_latency_ms")
    op.drop_column("agent_runs", "model_member")
    op.drop_column("agent_runs", "model_name")
    op.drop_column("agent_runs", "model_provider")
    op.drop_column("agent_runs", "trace_id")
