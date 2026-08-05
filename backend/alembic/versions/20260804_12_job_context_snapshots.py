"""add job context snapshots to interview sessions

Revision ID: 20260804_12
Revises: 20260803_11
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_12"
down_revision: str | None = "20260803_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the source job reference and immutable interview-time snapshot."""
    op.add_column("sessions", sa.Column("source_job_id", sa.Integer(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("job_context_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("idx_sessions_source_job", "sessions", ["user_id", "source_job_id"], unique=False)


def downgrade() -> None:
    """Remove the job handoff persistence fields."""
    op.drop_index("idx_sessions_source_job", table_name="sessions")
    op.drop_column("sessions", "job_context_snapshot")
    op.drop_column("sessions", "source_job_id")
