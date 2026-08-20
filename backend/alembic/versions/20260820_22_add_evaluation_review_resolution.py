"""add persisted evaluation review resolution

Revision ID: 20260820_22
Revises: 20260820_21
Create Date: 2026-08-20
"""
from collections.abc import Sequence
from alembic import op

revision: str = "20260820_22"
down_revision: str | Sequence[str] | None = "20260820_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF to_regclass('public.evaluation_case_runs') IS NOT NULL THEN
        ALTER TABLE evaluation_case_runs ADD COLUMN IF NOT EXISTS review_status VARCHAR(32);
        ALTER TABLE evaluation_case_runs ADD COLUMN IF NOT EXISTS review_resolver_key VARCHAR(120);
        ALTER TABLE evaluation_case_runs ADD COLUMN IF NOT EXISTS review_resolved_at TIMESTAMP;
        ALTER TABLE evaluation_case_runs ADD COLUMN IF NOT EXISTS review_resolution_note VARCHAR(2000);
        UPDATE evaluation_case_runs SET review_status = CASE WHEN needs_review THEN 'pending' ELSE 'not_required' END WHERE review_status IS NULL;
        ALTER TABLE evaluation_case_runs ALTER COLUMN review_status SET DEFAULT 'not_required';
        ALTER TABLE evaluation_case_runs ALTER COLUMN review_status SET NOT NULL;
      END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF to_regclass('public.evaluation_case_runs') IS NOT NULL THEN
        ALTER TABLE evaluation_case_runs DROP COLUMN IF EXISTS review_resolution_note;
        ALTER TABLE evaluation_case_runs DROP COLUMN IF EXISTS review_resolved_at;
        ALTER TABLE evaluation_case_runs DROP COLUMN IF EXISTS review_resolver_key;
        ALTER TABLE evaluation_case_runs DROP COLUMN IF EXISTS review_status;
      END IF;
    END $$;
    """)
