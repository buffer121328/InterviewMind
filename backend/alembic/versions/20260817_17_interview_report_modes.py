"""persist report modes, source identities and interview context references

Revision ID: 20260817_17
Revises: 20260815_16
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260817_17"
down_revision: str | Sequence[str] | None = "20260815_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable-compatible fields and backfill legacy reports as deep."""

    session_columns = (
        sa.Column("report_mode", sa.String(length=16), nullable=True),
        sa.Column("report_source_version", sa.String(length=128), nullable=True),
        sa.Column("stable_context_version", sa.String(length=128), nullable=True),
        sa.Column("stable_context_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("round_strategy_version", sa.String(length=128), nullable=True),
        sa.Column("turn_state_version", sa.String(length=64), nullable=True),
        sa.Column("turn_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("turn_checkpoint_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    for column in session_columns:
        op.add_column("sessions", column)
    op.execute("UPDATE sessions SET report_mode = 'deep' WHERE report_mode IS NULL")
    op.alter_column(
        "sessions",
        "report_mode",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default=sa.text("'deep'"),
    )

    op.add_column("artifacts", sa.Column("artifact_mode", sa.String(length=16), nullable=True))
    op.add_column("artifacts", sa.Column("report_source_version", sa.String(length=128), nullable=True))
    op.execute(
        "UPDATE artifacts SET artifact_mode = CASE "
        "WHEN source_type = 'interview_report' THEN 'deep' ELSE 'default' END "
        "WHERE artifact_mode IS NULL"
    )
    op.execute("UPDATE artifacts SET report_source_version = 'legacy' WHERE report_source_version IS NULL")
    op.alter_column(
        "artifacts",
        "artifact_mode",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default=sa.text("'default'"),
    )
    op.alter_column(
        "artifacts",
        "report_source_version",
        existing_type=sa.String(length=128),
        nullable=False,
        server_default=sa.text("'legacy'"),
    )
    op.drop_constraint("uq_artifact_source_format", "artifacts", type_="unique")
    op.create_unique_constraint(
        "uq_artifact_source_format_mode_version",
        "artifacts",
        ["user_id", "source_type", "source_id", "format", "artifact_mode", "report_source_version"],
    )


def downgrade() -> None:
    """Reject a downgrade that would collapse coexisting mode/version artifacts."""

    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM artifacts "
        "GROUP BY user_id, source_type, source_id, format "
        "HAVING COUNT(*) > 1) THEN "
        "RAISE EXCEPTION 'cannot downgrade report artifacts with coexisting modes or source versions'; "
        "END IF; END $$"
    )
    op.drop_constraint("uq_artifact_source_format_mode_version", "artifacts", type_="unique")
    op.create_unique_constraint(
        "uq_artifact_source_format",
        "artifacts",
        ["user_id", "source_type", "source_id", "format"],
    )
    op.drop_column("artifacts", "report_source_version")
    op.drop_column("artifacts", "artifact_mode")

    op.drop_column("sessions", "turn_checkpoint_refs")
    op.drop_column("sessions", "turn_state")
    op.drop_column("sessions", "turn_state_version")
    op.drop_column("sessions", "round_strategy_version")
    op.drop_column("sessions", "stable_context_fingerprint")
    op.drop_column("sessions", "stable_context_version")
    op.drop_column("sessions", "report_source_version")
    op.drop_column("sessions", "report_mode")
