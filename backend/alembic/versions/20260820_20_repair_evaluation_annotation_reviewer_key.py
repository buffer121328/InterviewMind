"""repair legacy evaluation annotation reviewer identity

Revision ID: 20260820_20
Revises: 20260818_19
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_20"
down_revision: str | Sequence[str] | None = "20260818_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restore the non-null reviewer identity required by evaluation detail reads."""

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.evaluation_annotations') IS NOT NULL THEN
                ALTER TABLE evaluation_annotations
                    ADD COLUMN IF NOT EXISTS reviewer_key VARCHAR(120);
                UPDATE evaluation_annotations
                    SET reviewer_key = 'reviewer-default'
                    WHERE reviewer_key IS NULL;
                ALTER TABLE evaluation_annotations
                    ALTER COLUMN reviewer_key SET NOT NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Remove the repaired column when deliberately returning to the prior schema."""

    op.execute(
        "ALTER TABLE IF EXISTS evaluation_annotations "
        "DROP COLUMN IF EXISTS reviewer_key"
    )
