"""add question followups and interview attempts

Revision ID: 20260712_01
Revises:
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260712_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_bank_followups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("parent_question_id", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("trigger_condition", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_question_id"], ["question_bank_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_question_followups_parent", "question_bank_followups", ["parent_question_id", "created_at"])
    op.create_index("idx_question_followups_user", "question_bank_followups", ["user_id", "created_at"])

    op.create_table(
        "interview_question_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("turn_key", sa.String(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("followup_id", sa.Integer(), nullable=True),
        sa.Column("asked_question", sa.Text(), nullable=False),
        sa.Column("user_answer", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["followup_id"], ["question_bank_followups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["question_id"], ["question_bank_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "session_id", "turn_key", name="uq_interview_attempt_turn"),
    )
    op.create_index("idx_interview_attempts_session", "interview_question_attempts", ["user_id", "session_id", "sequence"])
    op.create_index("idx_interview_attempts_question", "interview_question_attempts", ["question_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_interview_attempts_question", table_name="interview_question_attempts")
    op.drop_index("idx_interview_attempts_session", table_name="interview_question_attempts")
    op.drop_table("interview_question_attempts")
    op.drop_index("idx_question_followups_user", table_name="question_bank_followups")
    op.drop_index("idx_question_followups_parent", table_name="question_bank_followups")
    op.drop_table("question_bank_followups")
