"""persist resume generation sessions and task result idempotency

Revision ID: 20260716_03
Revises: 20260715_02
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260716_03"
down_revision: Union[str, Sequence[str], None] = "20260715_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """执行 `upgrade` 相关逻辑。"""
    op.add_column("resume_results", sa.Column("agent_run_id", sa.String(), nullable=True))
    op.create_unique_constraint("uq_resume_results_agent_run", "resume_results", ["agent_run_id"])
    op.add_column("generated_resumes", sa.Column("generation_session_id", sa.String(), nullable=True))
    op.add_column("generated_resumes", sa.Column("agent_run_id", sa.String(), nullable=True))
    op.create_unique_constraint("uq_generated_resumes_generation_session", "generated_resumes", ["generation_session_id"])
    op.create_unique_constraint("uq_generated_resumes_agent_run", "generated_resumes", ["agent_run_id"])

    op.create_table(
        "resume_generation_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("resume_content", sa.Text(), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("optimization_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("template_style", sa.String(), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("user_answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("final_markdown", sa.Text(), nullable=False),
        sa.Column("generated_resume_id", sa.Integer(), nullable=True),
        sa.Column("agent_run_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_generation_sessions_user_id", "resume_generation_sessions", ["user_id"])
    op.create_index("idx_resume_generation_sessions_user", "resume_generation_sessions", ["user_id", "updated_at"])
    op.create_index("idx_resume_generation_sessions_status", "resume_generation_sessions", ["status", "updated_at"])


def downgrade() -> None:
    """执行 `downgrade` 相关逻辑。"""
    op.drop_index("idx_resume_generation_sessions_status", table_name="resume_generation_sessions")
    op.drop_index("idx_resume_generation_sessions_user", table_name="resume_generation_sessions")
    op.drop_index("ix_resume_generation_sessions_user_id", table_name="resume_generation_sessions")
    op.drop_table("resume_generation_sessions")
    op.drop_constraint("uq_generated_resumes_agent_run", "generated_resumes", type_="unique")
    op.drop_constraint("uq_generated_resumes_generation_session", "generated_resumes", type_="unique")
    op.drop_column("generated_resumes", "agent_run_id")
    op.drop_column("generated_resumes", "generation_session_id")
    op.drop_constraint("uq_resume_results_agent_run", "resume_results", type_="unique")
    op.drop_column("resume_results", "agent_run_id")
