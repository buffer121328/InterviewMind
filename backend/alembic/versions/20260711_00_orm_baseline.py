"""create ORM baseline schema

Revision ID: 20260711_00
Revises:
Create Date: 2026-07-11
"""

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "20260711_00"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


def upgrade() -> None:
    """执行 `upgrade` 相关逻辑。"""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("resume_filename", sa.String(), nullable=True),
        sa.Column("resume_content", sa.Text(), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("company_info", sa.Text(), nullable=True),
        sa.Column("interview_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("max_questions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("candidate_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("series_id", sa.String(), nullable=True),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("round_type", sa.String(), nullable=False),
        sa.Column("parent_session_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["parent_session_id"], ["sessions.session_id"]),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("idx_session_updated", "sessions", ["updated_at"])
    op.create_index("idx_session_status", "sessions", ["status"])
    op.create_index("idx_session_mode", "sessions", ["mode"])
    op.create_index("idx_session_user", "sessions", ["user_id"])
    op.create_index("idx_session_user_pinned", "sessions", ["user_id", "pinned", "updated_at"])
    op.create_index("idx_session_series", "sessions", ["series_id"])
    op.create_index("idx_session_parent", "sessions", ["parent_session_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("audio_url", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_message_session", "messages", ["session_id", "timestamp"])
    op.create_index("idx_message_timestamp", "messages", ["timestamp"])

    op.create_table(
        "user_profile",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("profile_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "resume_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("result_type", sa.String(), nullable=False),
        sa.Column("resume_content", sa.Text(), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("session_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("include_profile", sa.Boolean(), nullable=False),
        sa.Column("result_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_resume_results_user", "resume_results", ["user_id", "created_at"])
    op.create_index("idx_resume_results_type", "resume_results", ["result_type"])

    op.create_table(
        "generated_resumes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("optimization_result_id", sa.Integer(), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_generated_resumes_user", "generated_resumes", ["user_id", "created_at"])

    op.create_table(
        "candidate_materials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("material_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_resume_id", sa.Integer(), nullable=True),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_candidate_materials_user", "candidate_materials", ["user_id", "created_at"])
    op.create_index("idx_candidate_materials_type", "candidate_materials", ["material_type"])
    op.create_index("idx_candidate_materials_verified", "candidate_materials", ["is_verified"])

    op.create_table(
        "resume_assembly_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("selected_material_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selection_reason", sa.Text(), nullable=True),
        sa.Column("assembled_outline", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("assembled_content", sa.Text(), nullable=True),
        sa.Column("generated_resume_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_resume_assembly_user", "resume_assembly_results", ["user_id", "created_at"])

    op.create_table(
        "project_rewrite_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("project_title", sa.String(), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("rewrite_mode", sa.String(), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("result_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_project_rewrite_user", "project_rewrite_records", ["user_id", "created_at"])
    op.create_index("idx_project_rewrite_material", "project_rewrite_records", ["material_id"])

    op.create_table(
        "interview_weakness_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("series_id", sa.String(), nullable=True),
        sa.Column("report_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index("idx_weakness_report_user", "interview_weakness_reports", ["user_id", "created_at"])
    op.create_index("idx_weakness_report_session", "interview_weakness_reports", ["session_id"])

    op.create_table(
        "question_bank_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("origin_session_id", sa.String(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("target_skill", sa.String(), nullable=True),
        sa.Column("question_type", sa.String(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_question_bank_user", "question_bank_items", ["user_id", "created_at"])
    op.create_index("idx_question_bank_type", "question_bank_items", ["question_type"])
    op.create_index("idx_question_bank_difficulty", "question_bank_items", ["difficulty"])
    op.create_index("idx_question_bank_verified", "question_bank_items", ["is_verified"])

    op.create_table(
        "question_bank_imports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("import_source", sa.String(), nullable=False),
        sa.Column("import_status", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_question_bank_imports_user", "question_bank_imports", ["user_id", "created_at"])

    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=True),
        sa.Column("chunk_key", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("embedding_status", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace", "user_id", "source_type", "source_id", "chunk_key", name="uq_rag_chunks_scope"),
    )
    op.create_index("idx_rag_chunks_scope", "rag_chunks", ["namespace", "user_id", "source_type", "is_active"])
    op.create_index("idx_rag_chunks_content_hash", "rag_chunks", ["content_hash"])
    op.execute(
        "CREATE INDEX idx_rag_chunks_embedding_hnsw ON rag_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding_status = 'completed' AND is_active = TRUE"
    )
    op.execute("CREATE INDEX idx_rag_chunks_content_trgm ON rag_chunks USING gin (content gin_trgm_ops)")
    op.execute("CREATE INDEX idx_rag_chunks_metadata_gin ON rag_chunks USING gin (metadata)")

    op.create_table(
        "job_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("job_title", sa.String(), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("generated_resume_id", sa.Integer(), nullable=True),
        sa.Column("latest_status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source_platform", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("external_job_id", sa.String(), nullable=True),
        sa.Column("captured_job_id", sa.Integer(), nullable=True),
        sa.Column("greeting_text", sa.Text(), nullable=True),
        sa.Column("send_status", sa.String(), nullable=True),
        sa.Column("send_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_screenshot_path", sa.String(), nullable=True),
        sa.Column("jd_analysis_id", sa.Integer(), nullable=True),
        sa.Column("custom_resume_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_job_applications_user", "job_applications", ["user_id", "updated_at"])
    op.create_index("idx_job_applications_status", "job_applications", ["latest_status"])
    op.create_index("idx_job_applications_send_status", "job_applications", ["send_status"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_time", sa.DateTime(), nullable=False),
        sa.Column("event_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["job_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_application_events_app", "application_events", ["application_id", "event_time"])

    op.create_table(
        "jd_analysis_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("resume_source_type", sa.String(), nullable=False),
        sa.Column("resume_source_id", sa.Integer(), nullable=True),
        sa.Column("resume_content_snapshot", sa.Text(), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("analysis_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_jd_analysis_user", "jd_analysis_results", ["user_id", "created_at"])

    op.create_table(
        "captured_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("external_job_id", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("job_title", sa.String(), nullable=True),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("salary_text", sa.String(), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("tags", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("source_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_captured_jobs_source_hash", "captured_jobs", ["source_hash"])
    op.create_index("idx_captured_jobs_user", "captured_jobs", ["user_id", "created_at"])
    op.create_index("idx_captured_jobs_platform", "captured_jobs", ["platform", "user_id"])
    op.create_index("idx_captured_jobs_hash_user", "captured_jobs", ["source_hash", "user_id"], unique=True)


def downgrade() -> None:
    """执行 `downgrade` 相关逻辑。"""
    op.drop_table("captured_jobs")
    op.drop_table("jd_analysis_results")
    op.drop_table("application_events")
    op.drop_table("job_applications")
    op.drop_table("rag_chunks")
    op.drop_table("question_bank_imports")
    op.drop_table("question_bank_items")
    op.drop_table("interview_weakness_reports")
    op.drop_table("project_rewrite_records")
    op.drop_table("resume_assembly_results")
    op.drop_table("candidate_materials")
    op.drop_table("generated_resumes")
    op.drop_table("resume_results")
    op.drop_table("user_profile")
    op.drop_table("messages")
    op.drop_table("sessions")
