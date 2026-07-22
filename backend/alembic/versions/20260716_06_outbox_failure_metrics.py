"""add task outbox failure metrics

Revision ID: 20260716_06
Revises: 20260716_05
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260716_06"
down_revision: Union[str, Sequence[str], None] = "20260716_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """执行 `upgrade` 相关逻辑。"""
    op.add_column("task_outbox", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("task_outbox", sa.Column("last_attempt_duration_ms", sa.Integer(), nullable=True))
    op.add_column("task_outbox", sa.Column("last_error_type", sa.String(), nullable=True))
    op.add_column("task_outbox", sa.Column("last_failure_reason", sa.String(), nullable=True))


def downgrade() -> None:
    """执行 `downgrade` 相关逻辑。"""
    op.drop_column("task_outbox", "last_failure_reason")
    op.drop_column("task_outbox", "last_error_type")
    op.drop_column("task_outbox", "last_attempt_duration_ms")
    op.drop_column("task_outbox", "last_attempt_at")
