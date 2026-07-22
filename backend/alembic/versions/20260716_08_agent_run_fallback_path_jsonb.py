"""normalize agent run fallback path to JSONB

Revision ID: 20260716_08
Revises: 20260716_07
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_08"
down_revision: Union[str, Sequence[str], None] = "20260716_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_type() -> str | None:
    """执行 `_column_type` 相关逻辑。"""
    return op.get_bind().execute(
        sa.text(
            "SELECT format_type(attribute.atttypid, attribute.atttypmod) "
            "FROM pg_attribute AS attribute "
            "JOIN pg_class AS relation ON relation.oid = attribute.attrelid "
            "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = 'public' "
            "AND relation.relname = 'agent_runs' "
            "AND attribute.attname = 'fallback_path' "
            "AND NOT attribute.attisdropped"
        )
    ).scalar_one_or_none()


def upgrade() -> None:
    """执行 `upgrade` 相关逻辑。"""
    if _column_type() == "json":
        op.execute(
            "ALTER TABLE agent_runs ALTER COLUMN fallback_path "
            "TYPE JSONB USING fallback_path::jsonb"
        )


def downgrade() -> None:
    """执行 `downgrade` 相关逻辑。"""
    if _column_type() == "jsonb":
        op.execute(
            "ALTER TABLE agent_runs ALTER COLUMN fallback_path "
            "TYPE JSON USING fallback_path::json"
        )
