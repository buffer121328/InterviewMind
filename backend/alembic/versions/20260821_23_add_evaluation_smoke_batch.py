"""add all-Agent smoke batch identifier

Revision ID: 20260821_23
Revises: 20260820_22
Create Date: 2026-08-21
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260821_23"
down_revision: str | Sequence[str] | None = "20260820_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF to_regclass('public.evaluation_runs') IS NOT NULL THEN
        ALTER TABLE evaluation_runs ADD COLUMN IF NOT EXISTS smoke_batch_id VARCHAR(160);
        CREATE INDEX IF NOT EXISTS idx_evaluation_run_owner_smoke_batch
          ON evaluation_runs (user_id, smoke_batch_id);
      END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF to_regclass('public.evaluation_runs') IS NOT NULL THEN
        DROP INDEX IF EXISTS idx_evaluation_run_owner_smoke_batch;
        ALTER TABLE evaluation_runs DROP COLUMN IF EXISTS smoke_batch_id;
      END IF;
    END $$;
    """)
