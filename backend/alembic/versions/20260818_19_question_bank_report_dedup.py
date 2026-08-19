"""deduplicate interview report question-bank entries

Revision ID: 20260818_19
Revises: 20260817_18
Create Date: 2026-08-18
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260818_19"
down_revision: str | Sequence[str] | None = "20260817_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("""
        DELETE FROM question_bank_items AS duplicate
        USING question_bank_items AS keeper
        WHERE duplicate.source_type = 'interview_report'
          AND keeper.source_type = 'interview_report'
          AND duplicate.user_id = keeper.user_id
          AND duplicate.source_id = keeper.source_id
          AND duplicate.origin_session_id = keeper.origin_session_id
          AND duplicate.id > keeper.id
    """)
    op.create_unique_constraint(
        "uq_question_bank_report_source", "question_bank_items",
        ["user_id", "source_type", "source_id", "origin_session_id"],
    )

def downgrade() -> None:
    op.drop_constraint("uq_question_bank_report_source", "question_bank_items", type_="unique")
