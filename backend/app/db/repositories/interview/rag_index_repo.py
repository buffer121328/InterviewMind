"""
RAG 索引数据仓库
负责 rag_chunks 表的 CRUD 和检索操作
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy import case, cast, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from app.db.models import async_session
from app.db.models.rag import RagChunkModel

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回带 UTC 时区的当前时间，保证数据库、队列和观测事件时间可比较。"""
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
            insert_stmt = pg_insert(RagChunkModel).values(
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
            content_changed = RagChunkModel.content_hash != insert_stmt.excluded.content_hash
            stmt = (
                insert_stmt
                .on_conflict_do_update(
                    constraint="uq_rag_chunks_scope",
                    set_={
                        "content": insert_stmt.excluded.content,
                        "content_hash": insert_stmt.excluded.content_hash,
                        "metadata": insert_stmt.excluded.metadata,
                        "source_version": insert_stmt.excluded.source_version,
                        "embedding": case(
                            (content_changed, None),
                            else_=RagChunkModel.embedding,
                        ),
                        "embedding_model": case(
                            (content_changed, None),
                            else_=RagChunkModel.embedding_model,
                        ),
                        "embedding_status": case(
                            (content_changed, "pending"),
                            else_=RagChunkModel.embedding_status,
                        ),
                        "is_active": True,
                        "updated_at": now,
                    },
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

    async def get_reusable_embeddings(
        self,
        *,
        user_id: str,
        content_hashes: set[str],
        embedding_model: str,
        dimensions: int | None = None,
    ) -> dict[str, List[float]]:
        """Return owner-scoped completed vectors whose content/model/dimension fingerprint matches."""
        if not content_hashes:
            return {}
        async with async_session() as db:
            rows = (await db.execute(
                select(RagChunkModel.content_hash, RagChunkModel.embedding).where(
                    RagChunkModel.user_id == user_id,
                    RagChunkModel.content_hash.in_(content_hashes),
                    RagChunkModel.embedding_model == embedding_model,
                    RagChunkModel.embedding_status == "completed",
                    RagChunkModel.is_active.is_(True),
                )
            )).all()
        reusable: dict[str, List[float]] = {}
        for content_hash, raw in rows:
            vector = [float(value) for value in list(raw or [])]
            if vector and (dimensions is None or len(vector) == dimensions):
                reusable.setdefault(str(content_hash), vector)
        return reusable

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

    async def deactivate_stale_chunks(
        self,
        user_id: str,
        namespace: str,
        source_type: str,
        active_chunk_scopes: set[tuple[str, str]],
    ) -> int:
        """失效一次成功重建后已不存在的 chunk，不跨越 owner、namespace 或来源类型边界。

        Args:
            user_id: 当前索引 owner。
            namespace: 当前检索命名空间。
            source_type: 本轮已完整提取的来源类型。
            active_chunk_scopes: 本轮仍存在的 ``(source_id, chunk_key)`` 集合。

        Returns:
            被标记为非活跃的旧 chunk 数量。
        """

        async with async_session() as db:
            stmt = update(RagChunkModel).where(
                RagChunkModel.user_id == user_id,
                RagChunkModel.namespace == namespace,
                RagChunkModel.source_type == source_type,
                RagChunkModel.is_active == True,
            )
            if active_chunk_scopes:
                stmt = stmt.where(
                    tuple_(RagChunkModel.source_id, RagChunkModel.chunk_key).not_in(
                        sorted(active_chunk_scopes)
                    )
                )
            result = await db.execute(
                stmt.values(is_active=False, updated_at=_utcnow())
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
                    RagChunkModel.chunk_metadata,
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
                    "metadata": r.chunk_metadata or {},
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
            # Keep the pgvector bind type explicit. Passing a bare Python list
            # to `func.cosine_distance` leaves asyncpg treating it as text.
            typed_query_embedding = cast(query_embedding, RagChunkModel.embedding.type)
            cosine_sim = func.cosine_distance(RagChunkModel.embedding, typed_query_embedding)
            stmt = (
                select(
                    RagChunkModel.id,
                    RagChunkModel.source_type,
                    RagChunkModel.source_id,
                    RagChunkModel.source_version,
                    RagChunkModel.chunk_key,
                    RagChunkModel.content,
                    RagChunkModel.chunk_metadata,
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
                    "metadata": r.chunk_metadata or {},
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
                    stmt = stmt.where(
                        RagChunkModel.chunk_metadata["tags"].contains(
                            cast([tag], JSONB)
                        )
                    )
            if target_skill:
                stmt = stmt.where(
                    RagChunkModel.chunk_metadata["target_skill"].astext == target_skill
                )
            if is_verified is not None:
                stmt = stmt.where(
                    RagChunkModel.chunk_metadata["is_verified"].astext == str(is_verified).lower()
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
                    "metadata": r.chunk_metadata or {},
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
    """构造 RAG 索引仓储，封装 chunk 的持久化查询，不负责嵌入生成或外部模型调用。"""
    global _rag_index_repo
    if _rag_index_repo is None:
        _rag_index_repo = RagIndexRepo()
    return _rag_index_repo
