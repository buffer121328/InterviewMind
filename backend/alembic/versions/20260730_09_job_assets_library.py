"""Persist captured-job asset summaries for the clickable job library.

Revision ID: 20260730_09
Revises: 20260730_08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_09"
down_revision: Union[str, Sequence[str], None] = "20260730_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add persisted job-asset tracking fields to captured jobs."""

    op.add_column("captured_jobs", sa.Column("company_size_text", sa.String(), nullable=True))
    op.add_column("captured_jobs", sa.Column("match_score", sa.Float(), nullable=True))
    op.add_column("captured_jobs", sa.Column("asset_run_id", sa.String(), nullable=True))
    op.add_column("captured_jobs", sa.Column("asset_status", sa.String(), nullable=True))
    op.add_column("captured_jobs", sa.Column("asset_payload", sa.JSON(), nullable=True))
    op.create_index("idx_captured_jobs_asset_run", "captured_jobs", ["asset_run_id"], unique=False)


def downgrade() -> None:
    """Remove persisted job-asset tracking fields from captured jobs."""

    op.drop_index("idx_captured_jobs_asset_run", table_name="captured_jobs")
    op.drop_column("captured_jobs", "asset_payload")
    op.drop_column("captured_jobs", "asset_status")
    op.drop_column("captured_jobs", "asset_run_id")
    op.drop_column("captured_jobs", "match_score")
    op.drop_column("captured_jobs", "company_size_text")
