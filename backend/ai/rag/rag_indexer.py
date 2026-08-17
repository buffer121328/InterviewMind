"""
RAG 索引构建服务
负责从业务表提取内容、切分、生成 embedding 并写入 rag_chunks
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from app.db.models import async_session
from ai.rag.embedding_service import (
    compute_content_hash,
    generate_embedding,
    generate_embeddings_batch,
    get_embedding_config,
)
from app.db.repositories.interview.rag_index_repo import get_rag_index_repo

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回带 UTC 时区的当前时间，保证数据库、队列和观测事件时间可比较。"""
    return datetime.now(timezone.utc)


def _make_chunk_key(source_type: str, source_id: str, suffix: str = "main") -> str:
    """生成稳定的 chunk_key

    Args:
        source_type: 来源类型。
        source_id: 来源记录 ID。
        suffix: 传入的 suffix 值。
    """
    return f"{source_type}:{source_id}:{suffix}"


def _truncate_chunk(text: str, max_chars: int = 800) -> str:
    """截断 chunk 到最大字符数

    Args:
        text: 文本内容。
        max_chars: chars 的最大值。
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


# ── 内容提取器（从业务表提取可索引内容）────────────────────


async def extract_question_bank_chunks(
    user_id: str, limit: int = 200
) -> List[Dict[str, Any]]:
    """从 question_bank_items 提取 chunk

    Args:
        user_id: 用户 ID，所有者范围限定。
        limit: 返回数量上限。
    """
    from app.db.models.interview import QuestionBankItemModel

    async with async_session() as db:
        from sqlalchemy import select
        stmt = (
            select(QuestionBankItemModel)
            .where(QuestionBankItemModel.user_id == user_id)
            .order_by(QuestionBankItemModel.updated_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

    chunks = []
    for row in rows:
        content_parts = [row.question_text]
        if row.reference_answer:
            content_parts.append(f"参考答案: {row.reference_answer}")
        content = "\n".join(content_parts)

        chunks.append({
            "source_type": "question_bank",
            "source_id": str(row.id),
            "chunk_key": _make_chunk_key("question_bank", str(row.id)),
            "content": _truncate_chunk(content),
            "metadata": {
                "target_skill": row.target_skill,
                "difficulty": row.difficulty,
                "question_type": row.question_type,
                "tags": row.tags or [],
                "is_verified": row.is_verified,
                "usage_count": row.usage_count,
            },
        })
    return chunks


async def extract_candidate_material_chunks(
    user_id: str, limit: int = 100
) -> List[Dict[str, Any]]:
    """从 candidate_materials 提取 chunk

    Args:
        user_id: 用户 ID，所有者范围限定。
        limit: 返回数量上限。
    """
    from app.db.models.resume import CandidateMaterialModel

    async with async_session() as db:
        from sqlalchemy import select
        stmt = (
            select(CandidateMaterialModel)
            .where(CandidateMaterialModel.user_id == user_id)
            .order_by(CandidateMaterialModel.updated_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

    chunks = []
    for row in rows:
        content = f"[{row.material_type}] {row.title}\n{row.content}"

        chunks.append({
            "source_type": "candidate_material",
            "source_id": str(row.id),
            "chunk_key": _make_chunk_key("candidate_material", str(row.id)),
            "content": _truncate_chunk(content),
            "metadata": {
                "material_type": row.material_type,
                "title": row.title,
                "tags": row.tags or [],
                "is_verified": row.is_verified,
                "importance_score": row.importance_score,
            },
        })
    return chunks


async def extract_weakness_report_chunks(
    user_id: str, limit: int = 20
) -> List[Dict[str, Any]]:
    """从 interview_weakness_reports 提取 chunk（每个短板分类一个 chunk）

    Args:
        user_id: 用户 ID，所有者范围限定。
        limit: 返回数量上限。
    """
    from app.db.models.interview import WeaknessReportModel

    async with async_session() as db:
        from sqlalchemy import select
        stmt = (
            select(WeaknessReportModel)
            .where(WeaknessReportModel.user_id == user_id)
            .order_by(WeaknessReportModel.updated_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

    chunks = []
    for row in rows:
        report = row.report_data or {}
        categories = report.get("weakness_categories", [])
        for idx, cat in enumerate(categories):
            parts = []
            if cat.get("category"):
                parts.append(f"分类: {cat['category']}")
            if cat.get("severity"):
                parts.append(f"严重程度: {cat['severity']}")
            if cat.get("description"):
                parts.append(f"描述: {cat['description']}")
            if cat.get("evidence"):
                parts.append(f"证据: {cat['evidence']}")
            content = "\n".join(parts)

            chunks.append({
                "source_type": "weakness_report",
                "source_id": str(row.id),
                "chunk_key": _make_chunk_key("weakness_report", str(row.id), f"cat_{idx}"),
                "content": _truncate_chunk(content),
                "metadata": {
                    "session_id": row.session_id,
                    "series_id": row.series_id,
                    "category": cat.get("category"),
                    "severity": cat.get("severity"),
                },
            })
    return chunks


async def extract_jd_analysis_chunks(
    user_id: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """从 jd_analysis_results 提取 chunk

    Args:
        user_id: 用户 ID，所有者范围限定。
        limit: 返回数量上限。
    """
    from app.db.models.jd import JdAnalysisResultModel

    async with async_session() as db:
        from sqlalchemy import select
        stmt = (
            select(JdAnalysisResultModel)
            .where(JdAnalysisResultModel.user_id == user_id)
            .order_by(JdAnalysisResultModel.updated_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

    chunks = []
    for row in rows:
        result = row.analysis_result or {}
        parts = []
        matched = result.get("matched_keywords", [])
        missing = result.get("missing_keywords", [])
        hints = result.get("selection_hints", [])
        if matched:
            parts.append(f"匹配关键词: {', '.join(matched[:10])}")
        if missing:
            parts.append(f"缺失关键词: {', '.join(missing[:10])}")
        if hints:
            parts.append(f"筛选提示: {'; '.join(str(h) for h in hints[:5])}")
        priorities = result.get("priority_actions", [])
        if priorities:
            parts.append(f"优先改进: {'; '.join(str(p) for p in priorities[:3])}")

        content = f"JD 分析结果\n{row.job_description[:200]}\n" + "\n".join(parts)

        chunks.append({
            "source_type": "jd_analysis",
            "source_id": str(row.id),
            "chunk_key": _make_chunk_key("jd_analysis", str(row.id)),
            "content": _truncate_chunk(content),
            "metadata": {
                "matched_keywords": matched[:10],
                "missing_keywords": missing[:10],
            },
        })
    return chunks


async def extract_session_qa_chunks(
    user_id: str, session_id: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """从 sessions.interview_plan 提取历史题目 chunk（用于去重和追问）

    Args:
        user_id: 用户 ID，所有者范围限定。
        session_id: 面试会话 ID。
        limit: 返回数量上限。
    """
    from app.db.models.session import SessionModel

    async with async_session() as db:
        from sqlalchemy import select
        stmt = (
            select(SessionModel)
            .where(
                SessionModel.user_id == user_id,
                SessionModel.interview_plan.is_not(None),
            )
        )
        if session_id:
            stmt = stmt.where(SessionModel.session_id != session_id)
        stmt = stmt.order_by(SessionModel.updated_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    chunks = []
    for row in rows:
        plan = row.interview_plan or []
        if isinstance(plan, list):
            for idx, q in enumerate(plan):
                if isinstance(q, dict) and q.get("content"):
                    content = f"题目: {q['content']}"
                    if q.get("topic"):
                        content = f"[{q['topic']}] {content}"

                    chunks.append({
                        "source_type": "historical_question",
                        "source_id": row.session_id,
                        "chunk_key": _make_chunk_key(
                            "historical_question", row.session_id, f"q_{idx}"
                        ),
                        "content": _truncate_chunk(content),
                        "metadata": {
                            "session_id": row.session_id,
                            "question_index": idx,
                            "question_type": q.get("type", "tech"),
                            "topic": q.get("topic"),
                        },
                    })
    return chunks


# ── 索引构建器 ────────────────────────────────────────────


class RagIndexer:
    """RAG 索引编排器，负责文档切分、嵌入和索引写入的流程边界；调用方仍需提供 owner、配置和外部 URL 校验。
    RAG 索引构建服务
    负责从业务表提取 chunk、生成 embedding、写入 rag_chunks
    """

    def __init__(self):
        """初始化 `RagIndexer` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._repo = get_rag_index_repo()
        self._config = get_embedding_config()

    async def index_user_data(
        self,
        user_id: str,
        with_embedding: bool = True,
        source_types: Optional[List[str]] = None,
        api_config: Optional[dict] = None,
    ) -> Dict[str, int]:
        """
        为用户构建/更新全部 RAG 索引

        Args:
            user_id: 用户 ID
            with_embedding: 是否同时生成 embedding
            source_types: 限定索引的来源类型，None 表示全部

        Returns:
            {"source_type": count} 各来源索引的 chunk 数
        """
        stats: Dict[str, int] = {}

        extractors = {
            "question_bank": extract_question_bank_chunks,
            "candidate_material": extract_candidate_material_chunks,
            "weakness_report": extract_weakness_report_chunks,
            "jd_analysis": extract_jd_analysis_chunks,
            "historical_question": extract_session_qa_chunks,
        }

        for source_type, extractor in extractors.items():
            if source_types and source_type not in source_types:
                continue
            try:
                chunks = await extractor(user_id)
                count = await self._index_chunks(
                    chunks,
                    user_id,
                    with_embedding,
                    api_config=api_config,
                )
                stale_count = await self._deactivate_stale_snapshot(
                    user_id=user_id,
                    source_type=source_type,
                    chunks=chunks,
                )
                stats[source_type] = count
                logger.info(
                    "[RAG Indexer] %s: indexed=%s stale_deactivated=%s",
                    source_type,
                    count,
                    stale_count,
                )
            except Exception as e:
                logger.error(
                    "[RAG Indexer] %s 索引失败: error_type=%s",
                    source_type,
                    type(e).__name__,
                )
                stats[source_type] = 0

        return stats

    async def _deactivate_stale_snapshot(
        self,
        *,
        user_id: str,
        source_type: str,
        chunks: List[Dict[str, Any]],
    ) -> int:
        """在某来源完整提取和 upsert 成功后，失效本轮快照中已经消失的旧 chunk。

        Args:
            user_id: 用户 ID，所有者范围限定。
            source_type: 来源类型。
            chunks: 分片列表。
        """

        scopes_by_namespace: dict[str, set[tuple[str, str]]] = {
            "user_private": set()
        }
        for chunk in chunks:
            if str(chunk.get("source_type") or "") != source_type:
                continue
            namespace = str(chunk.get("namespace") or "user_private")
            scopes_by_namespace.setdefault(namespace, set()).add(
                (str(chunk["source_id"]), str(chunk["chunk_key"]))
            )

        stale_count = 0
        for namespace, active_scopes in scopes_by_namespace.items():
            stale_count += await self._repo.deactivate_stale_chunks(
                user_id=user_id,
                namespace=namespace,
                source_type=source_type,
                active_chunk_scopes=active_scopes,
            )
        return stale_count

    async def _index_chunks(
        self,
        chunks: List[Dict[str, Any]],
        user_id: str,
        with_embedding: bool,
        api_config: Optional[dict] = None,
    ) -> int:
        """批量索引分片并返回更新计数。

        Args:
            chunks: 分片列表。
            user_id: 用户 ID，所有者范围限定。
            with_embedding: 传入的 with_embedding 值。
            api_config: 前端请求携带的模型通道配置。
        """
        if not chunks:
            return 0

        config = get_embedding_config(api_config) if api_config else self._config
        contents = [str(chunk["content"]) for chunk in chunks]
        content_hashes = [compute_content_hash(content) for content in contents]
        embeddings: list[list[float]] | None = None
        if with_embedding:
            reusable: dict[str, list[float]] = {}
            loader = getattr(self._repo, "get_reusable_embeddings", None)
            if loader is not None:
                reusable = await loader(
                    user_id=user_id,
                    content_hashes=set(content_hashes),
                    embedding_model=config["model"],
                    dimensions=config.get("dimensions"),
                )
            missing_hashes: list[str] = []
            missing_texts: list[str] = []
            for content_hash, content in zip(content_hashes, contents):
                if content_hash not in reusable and content_hash not in missing_hashes:
                    missing_hashes.append(content_hash)
                    missing_texts.append(content)
            try:
                if missing_texts:
                    generated = await generate_embeddings_batch(
                        missing_texts,
                        model=config["model"],
                        dimensions=config.get("dimensions"),
                        batch_size=min(20, max(1, len(missing_texts))),
                        api_config=api_config,
                    )
                    if len(generated) != len(missing_texts):
                        raise ValueError("embedding batch result count mismatch")
                    reusable.update(dict(zip(missing_hashes, generated)))
                embeddings = [reusable[content_hash] for content_hash in content_hashes]
            except Exception as exc:
                logger.warning(
                    "[RAG Indexer] 批量 embedding 失败，整批降级为 pending: error_type=%s",
                    type(exc).__name__,
                )
                embeddings = None

        for index, chunk in enumerate(chunks):
            common = {
                "user_id": user_id,
                "namespace": chunk.get("namespace", "user_private"),
                "source_type": chunk["source_type"],
                "source_id": chunk["source_id"],
                "chunk_key": chunk["chunk_key"],
                "content": contents[index],
                "content_hash": content_hashes[index],
                "metadata": chunk.get("metadata", {}),
            }
            if embeddings is not None:
                await self._repo.upsert_chunk_with_embedding(
                    **common,
                    embedding=embeddings[index],
                    embedding_model=config["model"],
                    dimensions=config["dimensions"],
                )
            else:
                await self._repo.upsert_chunk(**common)
        return len(chunks)

    async def process_pending_embeddings(
        self,
        user_id: Optional[str] = None,
        batch_size: int = 20,
        api_config: Optional[dict] = None,
    ) -> int:
        """
        处理状态为 pending 的 chunk，生成 embedding

        Args:
            user_id: 限定用户
            batch_size: 每批大小

        Returns:
            成功处理的 chunk 数
        """
        pending = await self._repo.get_pending_chunks(user_id=user_id, limit=batch_size)
        if not pending:
            return 0

        texts = [c.content for c in pending]
        try:
            config = get_embedding_config(api_config) if api_config else self._config
            embeddings = await generate_embeddings_batch(
                texts,
                model=config["model"],
                dimensions=config["dimensions"],
                batch_size=batch_size,
                api_config=api_config,
            )
        except Exception as e:
            logger.error(
                "[RAG Indexer] 批量 embedding 失败: error_type=%s",
                type(e).__name__,
            )
            raise RuntimeError("待处理 embedding 批次生成失败") from e

        success = 0
        for chunk, emb in zip(pending, embeddings):
            try:
                await self._repo.update_embedding(
                    chunk_id=chunk.id,
                    embedding=emb,
                    embedding_model=config["model"],
                    dimensions=config["dimensions"],
                )
                success += 1
            except Exception as e:
                logger.warning(
                    "[RAG Indexer] 更新 chunk embedding 失败: chunk_id=%s error_type=%s",
                    chunk.id,
                    type(e).__name__,
                )

        return success


# 全局单例
_rag_indexer: Optional[RagIndexer] = None


def get_rag_indexer() -> RagIndexer:
    """返回共享的 RAG 索引器实例，集中管理嵌入配置和索引生命周期，避免请求间重复初始化。"""
    global _rag_indexer
    if _rag_indexer is None:
        _rag_indexer = RagIndexer()
    return _rag_indexer
