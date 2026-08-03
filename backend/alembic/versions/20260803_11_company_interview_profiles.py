"""add company interview profile storage

Revision ID: 20260803_11
Revises: 20260801_10
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_11"
down_revision: str | None = "20260801_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("company_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(
        "idx_sessions_company_profile_recent",
        "sessions",
        ["user_id", "round_index", "status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_company_profile_recent", table_name="sessions")
    op.drop_column("sessions", "company_profile")
