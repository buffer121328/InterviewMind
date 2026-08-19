"""persist owner-scoped stable interview context snapshots

Revision ID: 20260817_18
Revises: 20260817_17
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260817_18"
down_revision: str | Sequence[str] | None = "20260817_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the private stable-prefix snapshot without changing API response shape."""
    op.add_column(
        "sessions",
        sa.Column(
            "stable_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the private stable-prefix snapshot."""
    op.drop_column("sessions", "stable_context")
