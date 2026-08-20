"""repair legacy evaluation annotation blind flag

Revision ID: 20260820_21
Revises: 20260820_20
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_21"
down_revision: str | Sequence[str] | None = "20260820_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restore the non-null blind flag required by evaluation annotation reads."""

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.evaluation_annotations') IS NOT NULL THEN
                ALTER TABLE evaluation_annotations
                    ADD COLUMN IF NOT EXISTS blind BOOLEAN;
                UPDATE evaluation_annotations
                    SET blind = TRUE
                    WHERE blind IS NULL;
                ALTER TABLE evaluation_annotations
                    ALTER COLUMN blind SET NOT NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Remove the repaired column when deliberately returning to the prior schema."""

    op.execute(
        "ALTER TABLE IF EXISTS evaluation_annotations "
        "DROP COLUMN IF EXISTS blind"
    )
