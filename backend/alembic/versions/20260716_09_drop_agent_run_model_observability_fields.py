"""drop redundant agent run model observability columns

Revision ID: 20260716_09
Revises: 20260716_08
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260716_09"
down_revision: Union[str, Sequence[str], None] = "20260716_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OBSOLETE_COLUMNS: tuple[str, ...] = (
    "model_error_type",
    "estimated_cost_usd",
    "fallback_path",
    "fallback_count",
    "output_tokens",
    "input_tokens",
    "request_latency_ms",
    "model_member",
    "model_name",
    "model_provider",
)

_RESTORE_COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    ("model_provider", sa.Column("model_provider", sa.String(), nullable=True)),
    ("model_name", sa.Column("model_name", sa.String(), nullable=True)),
    ("model_member", sa.Column("model_member", sa.String(), nullable=True)),
    ("request_latency_ms", sa.Column("request_latency_ms", sa.Integer(), nullable=True)),
    ("input_tokens", sa.Column("input_tokens", sa.Integer(), nullable=True)),
    ("output_tokens", sa.Column("output_tokens", sa.Integer(), nullable=True)),
    ("fallback_count", sa.Column("fallback_count", sa.Integer(), nullable=True)),
    ("fallback_path", sa.Column("fallback_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True)),
    ("estimated_cost_usd", sa.Column("estimated_cost_usd", sa.Float(), nullable=True)),
    ("model_error_type", sa.Column("model_error_type", sa.String(), nullable=True)),
)


def _columns() -> set[str]:
    """Return currently present agent_runs columns."""
    return {
        row[0]
        for row in op.get_bind().execute(
            sa.text(
                "SELECT attribute.attname "
                "FROM pg_attribute AS attribute "
                "JOIN pg_class AS relation ON relation.oid = attribute.attrelid "
                "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relname = 'agent_runs' "
                "AND attribute.attnum > 0 "
                "AND NOT attribute.attisdropped"
            )
        )
    }


def upgrade() -> None:
    """Remove model telemetry already owned by Langfuse/LangChain observability."""
    existing = _columns()
    for column_name in _OBSOLETE_COLUMNS:
        if column_name in existing:
            op.drop_column("agent_runs", column_name)


def downgrade() -> None:
    """Restore removed columns for rollback compatibility."""
    existing = _columns()
    for column_name, column in _RESTORE_COLUMNS:
        if column_name not in existing:
            op.add_column("agent_runs", column)
