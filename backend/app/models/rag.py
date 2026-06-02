"""
RAG 向量检索相关 SQLAlchemy ORM 模型
对应表: rag_chunks
"""

import os
from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, DateTime, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .base import Base

# 向量维度由环境变量统一配置，与 embedding_service 保持一致
_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


class RagChunkModel(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    namespace: Mapped[str] = mapped_column(String, nullable=False, default="user_private")
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_key: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    embedding = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "namespace", "user_id", "source_type", "source_id", "chunk_key",
            name="uq_rag_chunks_scope"
        ),
        Index("idx_rag_chunks_scope", "namespace", "user_id", "source_type", "is_active"),
        Index("idx_rag_chunks_content_hash", "content_hash"),
    )
