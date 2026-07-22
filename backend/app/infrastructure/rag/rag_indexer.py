"""
RAG 索引构建服务
负责从业务表提取内容、切分、生成 embedding 并写入 rag_chunks
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from app.infrastructure.db.models import async_session
from app.infrastructure.rag.embedding_service import (
    compute_content_hash,
    generate_embedding,
    generate_embeddings_batch,
    get_embedding_config,
)
from app.infrastructure.db.repositories.interview.rag_index_repo import get_rag_index_repo

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """执行 `_utcnow` 相关逻辑。"""
    return datetime.now(timezone.utc)


def _make_chunk_key(source_type: str, source_id: str, suffix: str = "main") -> str:
    """生成稳定的 chunk_key"""
    return f"{source_type}:{source_id}:{suffix}"


def _truncate_chunk(text: str, max_chars: int = 800) -> str:
    """截断 chunk 到最大字符数"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


# ── 内容提取器（从业务表提取可索引内容）────────────────────


async def extract_question_bank_chunks(
    user_id: str, limit: int = 200
) -> List[Dict[str, Any]]:
    """从 question_bank_items 提取 chunk"""
    from app.infrastructure.db.models.interview import QuestionBankItemModel

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
    """从 candidate_materials 提取 chunk"""
    from app.infrastructure.db.models.resume import CandidateMaterialModel

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
    """从 interview_weakness_reports 提取 chunk（每个短板分类一个 chunk）"""
    from app.infrastructure.db.models.interview import WeaknessReportModel

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
    """从 jd_analysis_results 提取 chunk"""
    from app.infrastructure.db.models.jd import JdAnalysisResultModel

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
    """从 sessions.interview_plan 提取历史题目 chunk（用于去重和追问）"""
    from app.infrastructure.db.models.session import SessionModel

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
    """
    RAG 索引构建服务
    负责从业务表提取 chunk、生成 embedding、写入 rag_chunks
    """

    def __init__(self):
        """初始化当前对象实例。"""
        self._repo = get_rag_index_repo()
        self._config = get_embedding_config()

    async def index_user_data(
        self,
        user_id: str,
        with_embedding: bool = True,
        source_types: Optional[List[str]] = None,
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
                count = await self._index_chunks(chunks, user_id, with_embedding)
                stats[source_type] = count
                logger.info(f"[RAG Indexer] {source_type}: {count} chunks indexed")
            except Exception as e:
                logger.error(
                    f"[RAG Indexer] {source_type} 索引失败: {e}", exc_info=True
                )
                stats[source_type] = 0

        return stats

    async def index_single_source(
        self,
        user_id: str,
        source_type: str,
        chunks: List[Dict[str, Any]],
        with_embedding: bool = True,
    ) -> int:
        """
        索引单个来源的 chunk 列表

        Args:
            user_id: 用户 ID
            source_type: 来源类型
            chunks: chunk 数据列表
            with_embedding: 是否生成 embedding

        Returns:
            索引的 chunk 数量
        """
        return await self._index_chunks(chunks, user_id, with_embedding)

    async def _index_chunks(
        self,
        chunks: List[Dict[str, Any]],
        user_id: str,
        with_embedding: bool,
    ) -> int:
        """内部方法：写入 chunk 到 rag_chunks 表"""
        if not chunks:
            return 0

        count = 0
        for chunk in chunks:
            content = chunk["content"]
            content_hash = compute_content_hash(content)

            if with_embedding:
                try:
                    embedding = await generate_embedding(content)
                    await self._repo.upsert_chunk_with_embedding(
                        user_id=user_id,
                        namespace=chunk.get("namespace", "user_private"),
                        source_type=chunk["source_type"],
                        source_id=chunk["source_id"],
                        chunk_key=chunk["chunk_key"],
                        content=content,
                        content_hash=content_hash,
                        embedding=embedding,
                        embedding_model=self._config["model"],
                        metadata=chunk.get("metadata", {}),
                    )
                except Exception as e:
                    logger.warning(
                        f"[RAG Indexer] embedding 生成失败，降级为 pending: {e}"
                    )
                    await self._repo.upsert_chunk(
                        user_id=user_id,
                        namespace=chunk.get("namespace", "user_private"),
                        source_type=chunk["source_type"],
                        source_id=chunk["source_id"],
                        chunk_key=chunk["chunk_key"],
                        content=content,
                        content_hash=content_hash,
                        metadata=chunk.get("metadata", {}),
                    )
            else:
                await self._repo.upsert_chunk(
                    user_id=user_id,
                    namespace=chunk.get("namespace", "user_private"),
                    source_type=chunk["source_type"],
                    source_id=chunk["source_id"],
                    chunk_key=chunk["chunk_key"],
                    content=content,
                    content_hash=content_hash,
                    metadata=chunk.get("metadata", {}),
                )
            count += 1

        return count

    async def process_pending_embeddings(
        self,
        user_id: Optional[str] = None,
        batch_size: int = 20,
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
            embeddings = await generate_embeddings_batch(texts, batch_size=batch_size)
        except Exception as e:
            logger.error(f"[RAG Indexer] 批量 embedding 失败: {e}")
            return 0

        success = 0
        for chunk, emb in zip(pending, embeddings):
            try:
                await self._repo.update_embedding(
                    chunk_id=chunk.id,
                    embedding=emb,
                    embedding_model=self._config["model"],
                )
                success += 1
            except Exception as e:
                logger.warning(f"[RAG Indexer] 更新 chunk {chunk.id} embedding 失败: {e}")

        return success


# 全局单例
_rag_indexer: Optional[RagIndexer] = None


def get_rag_indexer() -> RagIndexer:
    """获取 `rag indexer`。"""
    global _rag_indexer
    if _rag_indexer is None:
        _rag_indexer = RagIndexer()
    return _rag_indexer
