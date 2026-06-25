"""
简历相关 SQLAlchemy ORM 模型
对应表: resume_results, generated_resumes, candidate_materials,
        resume_assembly_results, project_rewrite_records
"""

from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, Float, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class ResumeResultModel(Base):
    __tablename__ = "resume_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    result_type: Mapped[str] = mapped_column(String)
    resume_content: Mapped[str] = mapped_column(Text)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    include_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    result_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_resume_results_user", "user_id", "created_at"),
        Index("idx_resume_results_type", "result_type"),
    )


class GeneratedResumeModel(Base):
    __tablename__ = "generated_resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    optimization_result_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_generated_resumes_user", "user_id", "created_at"),
    )


class CandidateMaterialModel(Base):
    __tablename__ = "candidate_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    material_type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    structured_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    source_type: Mapped[str] = mapped_column(String, default="manual")
    source_resume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_candidate_materials_user", "user_id", "created_at"),
        Index("idx_candidate_materials_type", "material_type"),
        Index("idx_candidate_materials_verified", "is_verified"),
    )


class ResumeAssemblyResultModel(Base):
    __tablename__ = "resume_assembly_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    job_description: Mapped[str] = mapped_column(Text)
    selected_material_ids: Mapped[list] = mapped_column(JSONB)
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assembled_outline: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assembled_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_resume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_resume_assembly_user", "user_id", "created_at"),
    )


class ProjectRewriteRecordModel(Base):
    __tablename__ = "project_rewrite_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_title: Mapped[str] = mapped_column(String)
    original_content: Mapped[str] = mapped_column(Text)
    rewrite_mode: Mapped[str] = mapped_column(String)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_project_rewrite_user", "user_id", "created_at"),
        Index("idx_project_rewrite_material", "material_id"),
    )
