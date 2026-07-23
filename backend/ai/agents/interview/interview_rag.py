"""
面试 RAG 编排服务
实现 planner_router -> query_builder -> retriever -> reranker -> evidence_packer -> fact_guard 流程
"""

import asyncio
import logging
import os
from collections import Counter
from dataclasses import replace
from time import perf_counter
from typing import List, Optional, Dict, Any

from ai.agents.interview.interview_rag_models import RagEvidence, RagResult, RetrievalQuery

logger = logging.getLogger(__name__)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    """去重并保留来源优先级顺序。"""
    return list(dict.fromkeys(values))


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """读取有上下界的整数配置，非法值回退默认值。"""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning("%s 配置非法，使用默认值 %s", name, default)
        value = default
    return min(max(value, minimum), maximum)


def _bounded_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    """读取有上下界的浮点配置，非法值回退默认值。"""
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning("%s 配置非法，使用默认值 %s", name, default)
        value = default
    return min(max(value, minimum), maximum)

# 功能开关：向量检索
VECTOR_ENABLED = os.getenv("RAG_VECTOR_ENABLED", "true").lower() == "true"

# 混合检索权重
WEIGHT_VECTOR = float(os.getenv("RAG_WEIGHT_VECTOR", "0.45"))
WEIGHT_TEXT = float(os.getenv("RAG_WEIGHT_TEXT", "0.25"))
WEIGHT_SOURCE_PRIORITY = float(os.getenv("RAG_WEIGHT_SOURCE", "0.20"))
WEIGHT_FRESHNESS = float(os.getenv("RAG_WEIGHT_FRESHNESS", "0.10"))

# 有界 Agentic Retrieval：off / shadow / active
AGENTIC_MODE = os.getenv("RAG_AGENTIC_MODE", "shadow").lower()
if AGENTIC_MODE not in {"off", "shadow", "active"}:
    logger.warning("未知 RAG_AGENTIC_MODE=%s，按 off 处理", AGENTIC_MODE)
    AGENTIC_MODE = "off"
AGENTIC_MAX_ROUNDS = _bounded_int_env("RAG_AGENTIC_MAX_ROUNDS", 2, 1, 2)
AGENTIC_MAX_QUERIES = _bounded_int_env("RAG_AGENTIC_MAX_QUERIES", 4, 1, 4)
AGENTIC_MIN_SCORE = _bounded_float_env("RAG_AGENTIC_MIN_SCORE", 0.30, 0.0, 1.0)
AGENTIC_MIN_EVIDENCES = _bounded_int_env("RAG_AGENTIC_MIN_EVIDENCES", 2, 1, 20)
AGENTIC_MIN_SOURCE_TYPES = _bounded_int_env("RAG_AGENTIC_MIN_SOURCE_TYPES", 2, 1, 10)


# ── 来源优先级 ────────────────────────────────────────────

_SOURCE_PRIORITY = {
    "weakness_report": 1.0,
    "candidate_material": 0.9,
    "question_bank": 0.85,
    "question_bank_followup": 0.83,
    "jd_analysis": 0.8,
    "memory": 0.75,
    "historical_question": 0.6,
}


# ── Query Builder ─────────────────────────────────────────


def build_queries(
    job_description: str,
    resume: str = "",
    weakness_report: Optional[Dict] = None,
    target_skills: Optional[List[str]] = None,
    round_type: str = "tech_initial",
) -> List[RetrievalQuery]:
    """
    从 JD、简历、短板中提取检索 query
    返回 1-3 个 query
    """
    queries: List[RetrievalQuery] = []

    # Query 1: JD 定向（核心 query）
    jd_text = (job_description or "")[:300]
    if jd_text.strip():
        source_types = ["candidate_material", "question_bank", "question_bank_followup", "jd_analysis"]
        if target_skills:
            source_types.append("question_bank")
        queries.append(RetrievalQuery(
            text=jd_text,
            source_types=_dedupe_preserve_order(source_types),
            target_skills=target_skills,
        ))

    # Query 2: 短板复练（如果有短板报告）
    if weakness_report:
        categories = weakness_report.get("weakness_categories", [])
        if categories:
            weakness_text = " ".join(
                [cat.get("description", cat.get("category", "")) for cat in categories[:3]]
            )
            if weakness_text.strip():
                queries.append(RetrievalQuery(
                    text=weakness_text,
                    source_types=["weakness_report", "question_bank", "question_bank_followup", "historical_question"],
                ))

    # Query 3: 简历素材匹配
    if resume and len(resume.strip()) > 50:
        resume_excerpt = resume[:300]
        queries.append(RetrievalQuery(
            text=resume_excerpt,
            source_types=["candidate_material"],
        ))

    # 至少有一个 query
    if not queries:
        queries.append(RetrievalQuery(text=job_description or "面试", source_types=None))

    return queries[:3]


# ── Reranker ──────────────────────────────────────────────


def _compute_freshness_score(metadata: Dict[str, Any]) -> float:
    """基于元数据估算新鲜度分（简单启发式）"""
    # 如果有 usage_count，使用越多分越低
    usage = metadata.get("usage_count", 0)
    if usage > 10:
        return 0.3
    if usage > 5:
        return 0.5
    return 0.8


def rerank_evidences(
    evidences: List[RagEvidence],
    max_results: int = 15,
) -> List[RagEvidence]:
    """
    对证据列表做混合重排序

    final_score =
      WEIGHT_VECTOR * vector_score +
      WEIGHT_TEXT * text_score +
      WEIGHT_SOURCE_PRIORITY * source_priority +
      WEIGHT_FRESHNESS * freshness
    """
    for ev in evidences:
        source_priority = _SOURCE_PRIORITY.get(ev.source_type, 0.5)
        freshness = _compute_freshness_score(ev.metadata)

        # retrieval_score 已由检索层计算（vector_score 或 text_score）
        raw_score = ev.retrieval_score

        # 根据 retrieval_mode 决定权重分配
        if ev.retrieval_mode in {"vector", "memory"}:
            final = (
                WEIGHT_VECTOR * raw_score
                + WEIGHT_SOURCE_PRIORITY * source_priority
                + WEIGHT_FRESHNESS * freshness
            )
        elif ev.retrieval_mode == "full_text":
            final = (
                WEIGHT_TEXT * raw_score
                + WEIGHT_SOURCE_PRIORITY * source_priority
                + WEIGHT_FRESHNESS * freshness
            )
        elif ev.retrieval_mode == "structured":
            final = (
                WEIGHT_SOURCE_PRIORITY * source_priority
                + WEIGHT_FRESHNESS * freshness
            )
        else:
            final = raw_score

        # 用户确认的素材加分
        if ev.metadata.get("is_verified"):
            final += 0.05

        ev.retrieval_score = round(final, 4)

    # 按分数降序
    evidences.sort(key=lambda e: e.retrieval_score, reverse=True)

    # 去重（按 source_type + source_id）
    seen = set()
    deduped = []
    for ev in evidences:
        key = f"{ev.source_type}:{ev.source_id}"
        if key not in seen:
            seen.add(key)
            deduped.append(ev)

    return deduped[:max_results]


# ── Fact Guard ────────────────────────────────────────────


def fact_guard(
    evidences: List[RagEvidence],
    user_id: str,
    historical_questions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    事实守卫：检查证据质量与租户边界。

    检索层会固定注入 user_id + user_private namespace；这里做防御式二次
    校验，避免测试桩、未来仓库实现或外部适配器误传跨用户/不可信证据。

    Returns:
        {"passed": bool, "issues": [...]}
    """
    issues = []

    # 1. 检查是否有足够证据
    if len(evidences) == 0:
        issues.append("no_evidence")

    # 2. 防御式检查租户边界与可信来源
    allowed_namespaces = {"user_private"}
    allowed_trust_levels = {"user_private", "user_memory"}
    for evidence in evidences:
        owner = (
            evidence.metadata.get("user_id")
            or evidence.metadata.get("owner_user_id")
            or evidence.metadata.get("created_by")
        )
        if owner and str(owner) != str(user_id):
            issues.append("cross_user_evidence")
            break

    if any(evidence.namespace not in allowed_namespaces for evidence in evidences):
        issues.append("unexpected_namespace")

    if any(evidence.trust_level not in allowed_trust_levels for evidence in evidences):
        issues.append("untrusted_evidence")

    # 3. 检查是否全是低分证据
    high_score_count = sum(1 for e in evidences if e.retrieval_score > 0.3)
    if len(evidences) > 0 and high_score_count == 0:
        issues.append("all_low_score_evidence")

    return {
        "passed": len(issues) == 0,
        "issues": list(dict.fromkeys(issues)),
    }


# ── 可复用检索与观测 ──────────────────────────────────────


async def _retrieve_queries(
    *,
    repo: Any,
    user_id: str,
    queries: List[RetrievalQuery],
) -> List[RagEvidence]:
    """执行只读混合召回；user_id 与 namespace 由服务端固定注入。"""
    from ai.rag.embedding_service import generate_embedding

    all_evidences: List[RagEvidence] = []
    for q in queries:
        try:
            structured = await repo.search_structured(
                user_id=user_id,
                namespace="user_private",
                source_types=q.source_types,
                tags=q.tags,
                target_skill=q.target_skills[0] if q.target_skills else None,
                is_verified=q.is_verified,
                limit=10,
            )
            for item in structured:
                all_evidences.append(RagEvidence(
                    source_type=item["source_type"],
                    source_id=item["source_id"],
                    evidence=item["content"][:300],
                    metadata=item.get("metadata", {}),
                    retrieval_mode="structured",
                    retrieval_score=0.5,
                ))
        except Exception as exc:
            logger.warning("[RAG] 结构化检索失败: %s", type(exc).__name__)

        if q.text and len(q.text.strip()) > 10:
            try:
                text_results = await repo.search_by_text(
                    user_id=user_id,
                    namespace="user_private",
                    query=q.text[:200],
                    source_types=q.source_types,
                    limit=8,
                )
                for item in text_results:
                    all_evidences.append(RagEvidence(
                        source_type=item["source_type"],
                        source_id=item["source_id"],
                        evidence=item["content"][:300],
                        metadata=item.get("metadata", {}),
                        retrieval_mode="full_text",
                        retrieval_score=item.get("text_score", 0),
                    ))
            except Exception as exc:
                logger.warning("[RAG] 全文检索失败: %s", type(exc).__name__)

        if VECTOR_ENABLED and q.text and len(q.text.strip()) > 10:
            try:
                query_embedding = await generate_embedding(q.text[:300])
                vector_results = await repo.search_by_vector(
                    user_id=user_id,
                    namespace="user_private",
                    query_embedding=query_embedding,
                    source_types=q.source_types,
                    limit=8,
                    min_score=0.3,
                )
                for item in vector_results:
                    all_evidences.append(RagEvidence(
                        source_type=item["source_type"],
                        source_id=item["source_id"],
                        evidence=item["content"][:300],
                        metadata=item.get("metadata", {}),
                        retrieval_mode="vector",
                        retrieval_score=item.get("vector_score", 0),
                    ))
            except Exception as exc:
                logger.warning("[RAG] 向量检索失败（降级到非向量模式）: %s", type(exc).__name__)

    return all_evidences


async def _retrieve_memory_evidences(
    *,
    user_id: str,
    query: str,
    limit: int = 5,
) -> List[RagEvidence]:
    """将 mem0 只读结果适配为统一证据结构。"""
    from ai.runtime.middleware.content_safety import contains_prompt_injection
    from ai.tools.memory_tools import search_memory

    memories = await search_memory(user_id=user_id, query=query, limit=limit)
    evidences: List[RagEvidence] = []
    for index, item in enumerate(memories):
        if not isinstance(item, dict) or item.get("message"):
            continue
        content = str(item.get("memory") or item.get("text") or "").strip()
        if not content or contains_prompt_injection(content):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        raw_score = item.get("score", item.get("similarity", 0.5))
        try:
            score = min(max(float(raw_score), 0.0), 1.0)
        except (TypeError, ValueError):
            score = 0.5
        evidences.append(RagEvidence(
            source_type="memory",
            source_id=str(item.get("id") or f"memory-{index}"),
            source_title="长期记忆",
            evidence=content[:300],
            metadata={"memory_type": metadata.get("memory_type")},
            retrieval_mode="memory",
            retrieval_score=score,
            trust_level="user_memory",
        ))
    return evidences


def _rank_evidence_copies(
    evidences: List[RagEvidence],
    *,
    max_results: int = 15,
) -> List[RagEvidence]:
    """重排副本，避免影子检索修改旧链路的原始分数。"""
    return rerank_evidences([replace(item) for item in evidences], max_results=max_results)


def _merge_ranked_evidences(
    evidences: List[RagEvidence],
    *,
    max_results: int = 15,
) -> List[RagEvidence]:
    """合并多个已重排结果，按来源键去重。"""
    best_by_source: Dict[str, RagEvidence] = {}
    for evidence in evidences:
        key = f"{evidence.source_type}:{evidence.source_id}"
        current = best_by_source.get(key)
        if current is None or evidence.retrieval_score > current.retrieval_score:
            best_by_source[key] = evidence
    return sorted(
        best_by_source.values(),
        key=lambda item: item.retrieval_score,
        reverse=True,
    )[:max_results]


def _quality_key(quality: Any) -> tuple:
    """仅在 Agentic 结果严格改善时允许替换旧结果。"""
    return (
        int(bool(quality.passed)),
        int(quality.high_score_count),
        int(quality.source_count),
        int(quality.evidence_count),
        -float(quality.duplicate_ratio),
    )


def _build_retrieval_trace(
    *,
    started_at: float,
    evidences: List[RagEvidence],
    total_candidates: int,
    agentic_mode: str,
    triggered: bool = False,
    adopted: bool = False,
    rounds: int = 0,
    initial_issues: Optional[List[str]] = None,
    final_issues: Optional[List[str]] = None,
    agentic_error_type: Optional[str] = None,
) -> Dict[str, Any]:
    """构建不含原始查询和用户内容的检索指标。"""
    return {
        "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        "total_candidates": total_candidates,
        "evidence_count": len(evidences),
        "source_counts": dict(Counter(item.source_type for item in evidences)),
        "agentic_mode": agentic_mode,
        "agentic_triggered": triggered,
        "agentic_adopted": adopted,
        "search_rounds": rounds,
        "initial_quality_issues": initial_issues or [],
        "final_quality_issues": final_issues or [],
        "agentic_error_type": agentic_error_type,
    }


# ── RAG 编排主流程 ────────────────────────────────────────


async def run_rag_pipeline(
    user_id: str,
    job_description: str,
    resume: str = "",
    session_id: Optional[str] = None,
    weakness_report: Optional[Dict] = None,
    target_skills: Optional[List[str]] = None,
    round_type: str = "tech_initial",
) -> RagResult:
    """
    RAG 编排主入口

    流程:
    1. query_builder: 从 JD/简历/短板提取检索 query
    2. retriever: 结构化 + 全文 + 可选向量
    3. reranker: 混合重排序
    4. agentic_retrieval: 低置信度时受限扩展（可关闭/影子运行）
    5. evidence_packer: 组装证据包
    6. fact_guard: 事实检查
    7. 降级处理
    """
    from app.db.repositories.interview.rag_index_repo import get_rag_index_repo

    started_at = perf_counter()
    repo = get_rag_index_repo()

    # Step 1: Query Builder
    queries = build_queries(
        job_description=job_description,
        resume=resume,
        weakness_report=weakness_report,
        target_skills=target_skills,
        round_type=round_type,
    )
    primary_query = queries[0] if queries else RetrievalQuery()

    logger.info(f"[RAG] user={user_id}, queries={len(queries)}, vector={VECTOR_ENABLED}")

    # Step 2-3: Retriever + Reranker
    all_evidences = await _retrieve_queries(repo=repo, user_id=user_id, queries=queries)
    reranked = _rank_evidence_copies(all_evidences, max_results=15)

    # Step 4: 低置信度时执行有界 Agentic Retrieval。
    agentic_triggered = False
    agentic_adopted = False
    agentic_rounds = 0
    agentic_candidate_count = 0
    initial_issues: List[str] = []
    final_issues: List[str] = []
    agentic_error_type: Optional[str] = None

    if AGENTIC_MODE != "off":
        try:
            from ai.agents.interview.agentic_retrieval import (
                AgenticSearchContext,
                AgenticSearchQuery,
                grade_evidences,
                run_agentic_retrieval,
            )

            initial_quality = grade_evidences(
                reranked,
                min_score=AGENTIC_MIN_SCORE,
                min_evidences=AGENTIC_MIN_EVIDENCES,
                min_source_types=AGENTIC_MIN_SOURCE_TYPES,
            )
            initial_issues = list(initial_quality.issues)

            weakness_categories = (weakness_report or {}).get("weakness_categories") or []
            weakness_text = " ".join(
                str(item.get("description") or item.get("category") or "")
                for item in weakness_categories[:3]
                if isinstance(item, dict)
            ).strip()

            async def retrieve_agentic_query(query: AgenticSearchQuery) -> List[RagEvidence]:
                """检索 `agentic query`。

                Args:
                    query: 查询条件。
                """
                nonlocal agentic_candidate_count
                requested_sources = set(query.source_types)
                search_memory_branch = not requested_sources or "memory" in requested_sources
                rag_sources = requested_sources.difference({"memory"})
                search_rag_branch = not requested_sources or bool(rag_sources)

                tasks = []
                if search_rag_branch:
                    tasks.append(_retrieve_queries(
                        repo=repo,
                        user_id=user_id,
                        queries=[RetrievalQuery(
                            text=query.text,
                            source_types=sorted(rag_sources) or None,
                            target_skills=list(query.target_skills) or None,
                        )],
                    ))
                if search_memory_branch:
                    tasks.append(_retrieve_memory_evidences(
                        user_id=user_id,
                        query=query.text,
                        limit=5,
                    ))

                batches = await asyncio.gather(*tasks) if tasks else []
                raw = [item for batch in batches for item in batch]
                agentic_candidate_count += len(raw)
                return _rank_evidence_copies(raw, max_results=15)

            outcome = await run_agentic_retrieval(
                initial_evidences=reranked,
                context=AgenticSearchContext(
                    job_description=job_description,
                    target_skills=tuple(target_skills or ()),
                    weakness_text=weakness_text,
                    round_type=round_type,
                ),
                retrieve=retrieve_agentic_query,
                max_rounds=AGENTIC_MAX_ROUNDS,
                max_queries=AGENTIC_MAX_QUERIES,
                min_score=AGENTIC_MIN_SCORE,
                min_evidences=AGENTIC_MIN_EVIDENCES,
                min_source_types=AGENTIC_MIN_SOURCE_TYPES,
            )
            agentic_triggered = outcome.triggered
            agentic_rounds = outcome.rounds
            agentic_candidate = _merge_ranked_evidences(outcome.evidences, max_results=15)
            agentic_candidate_quality = grade_evidences(
                agentic_candidate,
                min_score=AGENTIC_MIN_SCORE,
                min_evidences=AGENTIC_MIN_EVIDENCES,
                min_source_types=AGENTIC_MIN_SOURCE_TYPES,
            )
            final_issues = list(agentic_candidate_quality.issues)

            if (
                AGENTIC_MODE == "active"
                and outcome.triggered
                and _quality_key(agentic_candidate_quality) > _quality_key(initial_quality)
            ):
                reranked = agentic_candidate
                agentic_adopted = True
        except Exception as exc:
            # Agentic 分支永远不能阻断原 RAG 快路径。
            agentic_error_type = type(exc).__name__
            logger.warning("[RAG] Agentic Retrieval 失败，保留原结果: %s", type(exc).__name__)

    trace = _build_retrieval_trace(
        started_at=started_at,
        evidences=reranked,
        total_candidates=len(all_evidences) + agentic_candidate_count,
        agentic_mode=AGENTIC_MODE,
        triggered=agentic_triggered,
        adopted=agentic_adopted,
        rounds=agentic_rounds,
        initial_issues=initial_issues,
        final_issues=final_issues,
        agentic_error_type=agentic_error_type,
    )

    # Step 5: Fact Guard
    guard_result = fact_guard(reranked, user_id)

    # Step 6: 构建结果
    if not guard_result["passed"]:
        fallback_reason = "; ".join(guard_result["issues"])
        logger.info(f"[RAG] fact_guard 未通过: {fallback_reason}")
        return RagResult(
            retrieval_mode="fallback",
            fallback_reason=fallback_reason,
            evidences=[],
            query_used=primary_query.text[:200],
            total_candidates=len(all_evidences),
            retrieval_trace=trace,
        )

    if not reranked:
        return RagResult(
            retrieval_mode="fallback",
            fallback_reason="no_evidence_found",
            evidences=[],
            query_used=primary_query.text[:200],
            total_candidates=0,
            retrieval_trace=trace,
        )

    # 判断检索模式
    has_vector = any(e.retrieval_mode == "vector" for e in reranked)
    mode = "agentic_hybrid" if agentic_adopted else ("hybrid" if has_vector else "structured")

    logger.info(
        f"[RAG] 完成: mode={mode}, evidences={len(reranked)}, "
        f"candidates={len(all_evidences)}"
    )

    return RagResult(
        retrieval_mode=mode,
        fallback_reason=None,
        evidences=reranked,
        query_used=primary_query.text[:200],
        total_candidates=len(all_evidences),
        retrieval_trace=trace,
    )


# ── 便捷入口（供 interview_graph 调用）────────────────────


async def rag_retrieve_for_interview(
    user_id: str,
    job_description: str,
    resume: str = "",
    session_id: Optional[str] = None,
    weakness_report: Optional[Dict] = None,
    target_skills: Optional[List[str]] = None,
    round_type: str = "tech_initial",
) -> Dict[str, Any]:
    """
    面试场景 RAG 检索入口

    返回旧格式 dict（兼容 interview_planner）+ rag_evidences 新字段
    """
    result = await run_rag_pipeline(
        user_id=user_id,
        job_description=job_description,
        resume=resume,
        session_id=session_id,
        weakness_report=weakness_report,
        target_skills=target_skills,
        round_type=round_type,
    )
    return result.to_legacy_context()
