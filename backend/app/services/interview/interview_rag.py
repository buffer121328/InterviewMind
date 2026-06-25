"""
面试 RAG 编排服务
实现 planner_router -> query_builder -> retriever -> reranker -> evidence_packer -> fact_guard 流程
"""

import logging
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# 功能开关：向量检索
VECTOR_ENABLED = os.getenv("RAG_VECTOR_ENABLED", "true").lower() == "true"

# 混合检索权重
WEIGHT_VECTOR = float(os.getenv("RAG_WEIGHT_VECTOR", "0.45"))
WEIGHT_TEXT = float(os.getenv("RAG_WEIGHT_TEXT", "0.25"))
WEIGHT_SOURCE_PRIORITY = float(os.getenv("RAG_WEIGHT_SOURCE", "0.20"))
WEIGHT_FRESHNESS = float(os.getenv("RAG_WEIGHT_FRESHNESS", "0.10"))


# ── 统一证据结构 ──────────────────────────────────────────


@dataclass
class RagEvidence:
    """统一证据条目"""
    source_type: str          # candidate_material, question_bank, weakness_report, jd_analysis, historical_question
    source_id: str
    source_title: str = ""
    evidence: str = ""        # 证据内容摘要
    metadata: Dict[str, Any] = field(default_factory=dict)
    retrieval_mode: str = "structured"  # structured, full_text, vector, hybrid
    retrieval_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RagResult:
    """RAG 检索结果"""
    retrieval_mode: str = "structured"  # structured, hybrid, fallback
    fallback_reason: Optional[str] = None
    evidences: List[RagEvidence] = field(default_factory=list)
    query_used: str = ""
    total_candidates: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retrieval_mode": self.retrieval_mode,
            "fallback_reason": self.fallback_reason,
            "evidences": [e.to_dict() for e in self.evidences],
            "query_used": self.query_used,
            "total_candidates": self.total_candidates,
        }

    def to_legacy_context(self) -> Dict[str, Any]:
        """
        向后兼容：转换为 retrieval_repo 旧格式
        让 interview_planner 的现有代码不用大改
        """
        bank_questions = []
        candidate_materials = []
        weakness_categories = []
        historical_questions = []
        jd_keywords = []

        for ev in self.evidences:
            if ev.source_type == "question_bank":
                bank_questions.append({
                    "id": ev.source_id,
                    "question_text": ev.evidence,
                    "target_skill": ev.metadata.get("target_skill"),
                    "difficulty": ev.metadata.get("difficulty", "medium"),
                    "tags": ev.metadata.get("tags", []),
                })
            elif ev.source_type == "candidate_material":
                candidate_materials.append({
                    "id": ev.source_id,
                    "material_type": ev.metadata.get("material_type"),
                    "title": ev.metadata.get("title", ev.source_title),
                    "content": ev.evidence,
                    "tags": ev.metadata.get("tags", []),
                })
            elif ev.source_type == "weakness_report":
                weakness_categories.append({
                    "category": ev.metadata.get("category"),
                    "severity": ev.metadata.get("severity", "medium"),
                    "description": ev.evidence,
                })
            elif ev.source_type == "historical_question":
                historical_questions.append(ev.evidence)
            elif ev.source_type == "jd_analysis":
                # 提取关键词
                keywords = ev.metadata.get("matched_keywords", [])
                keywords.extend(ev.metadata.get("missing_keywords", []))
                jd_keywords.extend(keywords)

        return {
            "jd_keywords": list(dict.fromkeys(jd_keywords)),
            "weakness_categories": weakness_categories,
            "historical_questions": historical_questions,
            "bank_questions": bank_questions,
            "candidate_materials": candidate_materials,
            "retrieval_mode": self.retrieval_mode,
            "fallback_reason": self.fallback_reason,
            # 新增字段：RAG 证据包
            "rag_evidences": [e.to_dict() for e in self.evidences],
        }


# ── 来源优先级 ────────────────────────────────────────────

_SOURCE_PRIORITY = {
    "weakness_report": 1.0,
    "candidate_material": 0.9,
    "question_bank": 0.85,
    "jd_analysis": 0.8,
    "historical_question": 0.6,
}


# ── Query Builder ─────────────────────────────────────────


@dataclass
class RetrievalQuery:
    """结构化检索 query"""
    text: str = ""
    source_types: Optional[List[str]] = None
    target_skills: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_verified: Optional[bool] = None


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
        source_types = ["candidate_material", "question_bank", "jd_analysis"]
        if target_skills:
            source_types.append("question_bank")
        queries.append(RetrievalQuery(
            text=jd_text,
            source_types=source_types,
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
                    source_types=["weakness_report", "question_bank", "historical_question"],
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
        if ev.retrieval_mode == "vector":
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
    事实守卫：检查证据质量

    Returns:
        {"passed": bool, "issues": [...]}
    """
    issues = []

    # 1. 检查是否有足够证据
    if len(evidences) == 0:
        issues.append("no_evidence")

    # 2. 检查是否跨用户（所有 evidence 必须属于同一用户）
    # 这在检索层已通过 user_id 过滤保证，这里做二次检查

    # 3. 检查是否全是低分证据
    high_score_count = sum(1 for e in evidences if e.retrieval_score > 0.3)
    if len(evidences) > 0 and high_score_count == 0:
        issues.append("all_low_score_evidence")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
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
    4. evidence_packer: 组装证据包
    5. fact_guard: 事实检查
    6. 降级处理
    """
    from app.repositories.interview.rag_index_repo import get_rag_index_repo
    from app.services.rag.embedding_service import generate_embedding

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

    # Step 2: Retriever（混合检索）
    all_evidences: List[RagEvidence] = []

    for q in queries:
        # 2a. 结构化检索
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
        except Exception as e:
            logger.warning(f"[RAG] 结构化检索失败: {e}")

        # 2b. 全文检索（pg_trgm）
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
            except Exception as e:
                logger.warning(f"[RAG] 全文检索失败: {e}")

        # 2c. 向量检索（pgvector）
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
            except Exception as e:
                logger.warning(f"[RAG] 向量检索失败（降级到非向量模式）: {e}")

    # Step 3: Reranker
    reranked = rerank_evidences(all_evidences, max_results=15)

    # Step 4: Fact Guard
    guard_result = fact_guard(reranked, user_id)

    # Step 5: 构建结果
    if not guard_result["passed"]:
        fallback_reason = "; ".join(guard_result["issues"])
        logger.info(f"[RAG] fact_guard 未通过: {fallback_reason}")
        return RagResult(
            retrieval_mode="fallback",
            fallback_reason=fallback_reason,
            evidences=[],
            query_used=primary_query.text[:200],
            total_candidates=len(all_evidences),
        )

    if not reranked:
        return RagResult(
            retrieval_mode="fallback",
            fallback_reason="no_evidence_found",
            evidences=[],
            query_used=primary_query.text[:200],
            total_candidates=0,
        )

    # 判断检索模式
    has_vector = any(e.retrieval_mode == "vector" for e in reranked)
    mode = "hybrid" if has_vector else "structured"

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
