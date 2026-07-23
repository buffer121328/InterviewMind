"""
RAG 索引数据仓库
负责 rag_chunks 表的 CRUD 和检索操作
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy import select, update, delete, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import async_session
from app.db.models.rag import RagChunkModel

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """执行 `_utcnow` 相关逻辑。"""
    return datetime.now(timezone.utc)


class RagIndexRepo:
    """RAG chunk 索引仓库"""

    # ── 写入 ──────────────────────────────────────────────

    async def upsert_chunk(
        self,
        user_id: str,
        namespace: str,
        source_type: str,
        source_id: str,
        chunk_key: str,
        content: str,
        content_hash: str,
        metadata: Optional[Dict[str, Any]] = None,
        source_version: Optional[str] = None,
    ) -> int:
        """
        插入或更新一个 chunk（按 scope 唯一键做 upsert）。
        返回 chunk id。
        """
        now = _utcnow()
        async with async_session() as db:
            stmt = (
                pg_insert(RagChunkModel)
                .values(
                    user_id=user_id,
                    namespace=namespace,
                    source_type=source_type,
                    source_id=source_id,
                    source_version=source_version,
                    chunk_key=chunk_key,
                    content=content,
                    content_hash=content_hash,
                    chunk_metadata=metadata or {},
                    embedding_status="pending",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_rag_chunks_scope",
                    set_={
                        "content": content,
                        "content_hash": content_hash,
                        "metadata": metadata or {},
                        "source_version": source_version,
                        "embedding_status": "pending",
                        "is_active": True,
                        "updated_at": now,
                    },
                    where=RagChunkModel.content_hash != content_hash,
                )
                .returning(RagChunkModel.id)
            )
            result = (await db.execute(stmt)).scalar_one()
            await db.commit()
            return result

    async def upsert_chunk_with_embedding(
        self,
        user_id: str,
        namespace: str,
        source_type: str,
        source_id: str,
        chunk_key: str,
        content: str,
        content_hash: str,
        embedding: List[float],
        embedding_model: str,
        metadata: Optional[Dict[str, Any]] = None,
        source_version: Optional[str] = None,
    ) -> int:
        """upsert chunk 并同时写入 embedding"""
        now = _utcnow()
        async with async_session() as db:
            stmt = (
                pg_insert(RagChunkModel)
                .values(
                    user_id=user_id,
                    namespace=namespace,
                    source_type=source_type,
                    source_id=source_id,
                    source_version=source_version,
                    chunk_key=chunk_key,
                    content=content,
                    content_hash=content_hash,
                    chunk_metadata=metadata or {},
                    embedding=embedding,
                    embedding_model=embedding_model,
                    embedding_status="completed",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_rag_chunks_scope",
                    set_={
                        "content": content,
                        "content_hash": content_hash,
                        "metadata": metadata or {},
                        "source_version": source_version,
                        "embedding": embedding,
                        "embedding_model": embedding_model,
                        "embedding_status": "completed",
                        "is_active": True,
                        "updated_at": now,
                    },
                )
                .returning(RagChunkModel.id)
            )
            result = (await db.execute(stmt)).scalar_one()
            await db.commit()
            return result

    async def update_embedding(
        self,
        chunk_id: int,
        embedding: List[float],
        embedding_model: str,
    ) -> None:
        """更新单个 chunk 的 embedding"""
        async with async_session() as db:
            await db.execute(
                update(RagChunkModel)
                .where(RagChunkModel.id == chunk_id)
                .values(
                    embedding=embedding,
                    embedding_model=embedding_model,
                    embedding_status="completed",
                    updated_at=_utcnow(),
                )
            )
            await db.commit()

    async def soft_delete_by_source(
        self,
        user_id: str,
        source_type: str,
        source_id: str,
    ) -> int:
        """软删除某个来源的所有 chunk，返回受影响行数"""
        async with async_session() as db:
            result = await db.execute(
                update(RagChunkModel)
                .where(
                    RagChunkModel.user_id == user_id,
                    RagChunkModel.source_type == source_type,
                    RagChunkModel.source_id == source_id,
                    RagChunkModel.is_active == True,
                )
                .values(is_active=False, updated_at=_utcnow())
            )
            await db.commit()
            return result.rowcount

    # ── 读取 ──────────────────────────────────────────────

    async def get_pending_chunks(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[RagChunkModel]:
        """获取待 embedding 的 chunk"""
        async with async_session() as db:
            stmt = (
                select(RagChunkModel)
                .where(
                    RagChunkModel.embedding_status == "pending",
                    RagChunkModel.is_active == True,
                )
            )
            if user_id:
                stmt = stmt.where(RagChunkModel.user_id == user_id)
            stmt = stmt.order_by(RagChunkModel.created_at.asc()).limit(limit)
            rows = (await db.execute(stmt)).scalars().all()
            return list(rows)

    async def search_by_text(
        self,
        user_id: str,
        namespace: str,
        query: str,
        source_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        使用 pg_trgm 做模糊文本检索
        """
        async with async_session() as db:
            similarity_expr = func.similarity(RagChunkModel.content, query)
            stmt = (
                select(
                    RagChunkModel.id,
                    RagChunkModel.source_type,
                    RagChunkModel.source_id,
                    RagChunkModel.source_version,
                    RagChunkModel.chunk_key,
                    RagChunkModel.content,
                    RagChunkModel.metadata,
                    similarity_expr.label("text_score"),
                )
                .where(
                    RagChunkModel.user_id == user_id,
                    RagChunkModel.namespace == namespace,
                    RagChunkModel.is_active == True,
                    similarity_expr > 0.05,
                )
            )
            if source_types:
                stmt = stmt.where(RagChunkModel.source_type.in_(source_types))
            stmt = stmt.order_by(similarity_expr.desc()).limit(limit)
            rows = (await db.execute(stmt)).all()
            return [
                {
                    "id": r.id,
                    "source_type": r.source_type,
                    "source_id": r.source_id,
                    "source_version": r.source_version,
                    "chunk_key": r.chunk_key,
                    "content": r.content,
                    "metadata": r.metadata or {},
                    "text_score": float(r.text_score or 0),
                }
                for r in rows
            ]

    async def search_by_vector(
        self,
        user_id: str,
        namespace: str,
        query_embedding: List[float],
        source_types: Optional[List[str]] = None,
        limit: int = 10,
        min_score: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        使用 pgvector 做余弦相似度检索
        """
        async with async_session() as db:
            # 1 - cosine_distance = cosine_similarity
            cosine_sim = func.cosine_distance(RagChunkModel.embedding, query_embedding)
            stmt = (
                select(
                    RagChunkModel.id,
                    RagChunkModel.source_type,
                    RagChunkModel.source_id,
                    RagChunkModel.source_version,
                    RagChunkModel.chunk_key,
                    RagChunkModel.content,
                    RagChunkModel.metadata,
                    (1 - cosine_sim).label("vector_score"),
                )
                .where(
                    RagChunkModel.user_id == user_id,
                    RagChunkModel.namespace == namespace,
                    RagChunkModel.is_active == True,
                    RagChunkModel.embedding_status == "completed",
                    RagChunkModel.embedding.is_not(None),
                    (1 - cosine_sim) >= min_score,
                )
            )
            if source_types:
                stmt = stmt.where(RagChunkModel.source_type.in_(source_types))
            stmt = stmt.order_by(cosine_sim.asc()).limit(limit)
            rows = (await db.execute(stmt)).all()
            return [
                {
                    "id": r.id,
                    "source_type": r.source_type,
                    "source_id": r.source_id,
                    "source_version": r.source_version,
                    "chunk_key": r.chunk_key,
                    "content": r.content,
                    "metadata": r.metadata or {},
                    "vector_score": float(r.vector_score or 0),
                }
                for r in rows
            ]

    async def search_structured(
        self,
        user_id: str,
        namespace: str,
        source_types: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        target_skill: Optional[str] = None,
        is_verified: Optional[bool] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        结构化过滤检索
        """
        async with async_session() as db:
            stmt = select(RagChunkModel).where(
                RagChunkModel.user_id == user_id,
                RagChunkModel.namespace == namespace,
                RagChunkModel.is_active == True,
            )
            if source_types:
                stmt = stmt.where(RagChunkModel.source_type.in_(source_types))
            if tags:
                # JSONB array contains
                for tag in tags:
                    stmt = stmt.where(RagChunkModel.metadata["tags"].contains(tag))
            if target_skill:
                stmt = stmt.where(
                    RagChunkModel.metadata["target_skill"].astext == target_skill
                )
            if is_verified is not None:
                stmt = stmt.where(
                    RagChunkModel.metadata["is_verified"].astext == str(is_verified).lower()
                )
            stmt = stmt.order_by(RagChunkModel.updated_at.desc()).limit(limit)
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "source_type": r.source_type,
                    "source_id": r.source_id,
                    "source_version": r.source_version,
                    "chunk_key": r.chunk_key,
                    "content": r.content,
                    "metadata": r.metadata or {},
                    "retrieval_mode": "structured",
                }
                for r in rows
            ]

    async def count_chunks(
        self,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        source_type: Optional[str] = None,
        only_active: bool = True,
    ) -> int:
        """统计 chunk 数量"""
        async with async_session() as db:
            stmt = select(func.count(RagChunkModel.id))
            if user_id:
                stmt = stmt.where(RagChunkModel.user_id == user_id)
            if namespace:
                stmt = stmt.where(RagChunkModel.namespace == namespace)
            if source_type:
                stmt = stmt.where(RagChunkModel.source_type == source_type)
            if only_active:
                stmt = stmt.where(RagChunkModel.is_active == True)
            return (await db.execute(stmt)).scalar() or 0


# 全局单例
_rag_index_repo: Optional[RagIndexRepo] = None


def get_rag_index_repo() -> RagIndexRepo:
    """获取 `rag index repo`。"""
    global _rag_index_repo
    if _rag_index_repo is None:
        _rag_index_repo = RagIndexRepo()
    return _rag_index_repo
