"""add database-backed prompt versions

Revision ID: 20260727_03
Revises: 20260727_02
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260727_03"
down_revision: Union[str, Sequence[str], None] = "20260727_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create immutable owner-scoped prompt version records."""
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_type", sa.String(length=16), nullable=False),
        sa.Column("prompt", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_production", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", "version", name="uq_prompt_version_owner_name_version"),
    )
    op.create_index("ix_prompt_versions_user_id", "prompt_versions", ["user_id"])
    op.create_index("idx_prompt_versions_owner_name_production", "prompt_versions", ["user_id", "name", "is_production"])


def downgrade() -> None:
    """Drop database-backed prompt version records."""
    op.drop_index("idx_prompt_versions_owner_name_production", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_user_id", table_name="prompt_versions")
    op.drop_table("prompt_versions")
