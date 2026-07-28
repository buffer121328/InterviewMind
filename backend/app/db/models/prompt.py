"""Database-backed, user-scoped prompt versions used by runtime prompt resolution."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PromptVersionModel(Base):
    """Immutable prompt content with an explicit production pointer per owner and name.

    Prompt templates are server-side configuration assets.  They never contain model
    credentials; owner scoping ensures one user's edits cannot change another user's
    runtime prompts.
    """

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt: Mapped[dict] = mapped_column(JSONB, nullable=False)
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_production: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", "version", name="uq_prompt_version_owner_name_version"),
        Index("idx_prompt_versions_owner_name_production", "user_id", "name", "is_production"),
    )
