"""有界 Agentic Retrieval 编排。

该模块只决定何时扩展检索、检索哪些来源以及是否再检索一次。
数据访问通过调用方注入的只读 retriever 完成，租户边界不进入图状态。
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, Awaitable, Callable, Sequence, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


@dataclass(frozen=True)
class AgenticSearchQuery:
    """受限搜索请求；source_types 为空表示由检索底座搜索全部允许来源。"""

    text: str
    source_types: tuple[str, ...] = ()
    target_skills: tuple[str, ...] = ()
    reason: str = "evidence_gap"


@dataclass(frozen=True)
class AgenticSearchContext:
    """不包含 user_id 等安全边界的搜索规划上下文。"""

    job_description: str
    target_skills: tuple[str, ...] = ()
    weakness_text: str = ""
    round_type: str = "tech_initial"


@dataclass(frozen=True)
class EvidenceQuality:
    passed: bool
    issues: tuple[str, ...] = ()
    evidence_count: int = 0
    high_score_count: int = 0
    source_count: int = 0
    duplicate_ratio: float = 0.0


@dataclass
class AgenticSearchOutcome:
    triggered: bool
    evidences: list[Any]
    quality: EvidenceQuality
    rounds: int = 0
    trace: list[dict[str, Any]] = field(default_factory=list)


ReadOnlyRetriever = Callable[[AgenticSearchQuery], Awaitable[list[Any]]]


class _SearchState(TypedDict, total=False):
    context: AgenticSearchContext
    retrieve: ReadOnlyRetriever
    query: AgenticSearchQuery
    queries: list[AgenticSearchQuery]
    evidences: Annotated[list[Any], operator.add]
    quality: EvidenceQuality
    triggered: bool
    rounds: int
    max_rounds: int
    max_queries: int
    min_score: float
    min_evidences: int
    min_source_types: int
    trace: Annotated[list[dict[str, Any]], operator.add]


def grade_evidences(
    evidences: Sequence[Any],
    *,
    min_score: float = 0.3,
    min_evidences: int = 2,
    min_source_types: int = 2,
) -> EvidenceQuality:
    """用确定性规则判断是否值得扩展检索。"""

    if not evidences:
        return EvidenceQuality(passed=False, issues=("no_evidence",))

    scores = [float(getattr(item, "retrieval_score", 0.0) or 0.0) for item in evidences]
    high_score_count = sum(score >= min_score for score in scores)
    source_types = {
        str(getattr(item, "source_type", "") or "")
        for item in evidences
        if getattr(item, "source_type", None)
    }
    normalized_contents = [
        " ".join(str(getattr(item, "evidence", "") or "").lower().split())
        for item in evidences
    ]
    non_empty_contents = [content for content in normalized_contents if content]
    unique_contents = set(non_empty_contents)
    duplicate_ratio = (
        1.0 - len(unique_contents) / len(non_empty_contents)
        if non_empty_contents
        else 0.0
    )

    issues: list[str] = []
    if len(evidences) < min_evidences:
        issues.append("insufficient_evidence")
    if high_score_count == 0:
        issues.append("all_low_score_evidence")
    if len(source_types) < min_source_types:
        issues.append("insufficient_source_coverage")
    if duplicate_ratio > 0.5:
        issues.append("high_duplicate_ratio")

    return EvidenceQuality(
        passed=not issues,
        issues=tuple(issues),
        evidence_count=len(evidences),
        high_score_count=high_score_count,
        source_count=len(source_types),
        duplicate_ratio=round(duplicate_ratio, 4),
    )


def build_search_plan(
    context: AgenticSearchContext,
    evidences: Sequence[Any],
    quality: EvidenceQuality,
    *,
    max_queries: int = 4,
) -> list[AgenticSearchQuery]:
    """根据证据缺口生成有限搜索计划，不调用模型。"""

    existing_sources = {
        str(getattr(item, "source_type", "") or "")
        for item in evidences
        if getattr(item, "source_type", None)
    }
    base_text = " ".join(context.job_description.split())[:300] or "面试"
    skill_text = " ".join(context.target_skills[:5])
    focused_text = " ".join(part for part in (skill_text, base_text) if part).strip()

    queries: list[AgenticSearchQuery] = []
    source_candidates = (
        ("question_bank", "题库证据缺失"),
        ("candidate_material", "候选人素材缺失"),
        ("weakness_report", "短板证据缺失"),
        ("memory", "长期记忆证据缺失"),
        ("historical_question", "历史题目证据缺失"),
    )
    for source_type, reason in source_candidates:
        if source_type in existing_sources:
            continue
        query_text = context.weakness_text if source_type == "weakness_report" else focused_text
        if not query_text.strip():
            continue
        queries.append(
            AgenticSearchQuery(
                text=query_text[:300],
                source_types=(source_type,),
                target_skills=context.target_skills,
                reason=reason,
            )
        )

    if "all_low_score_evidence" in quality.issues or "no_evidence" in quality.issues:
        queries.append(
            AgenticSearchQuery(
                text=focused_text,
                target_skills=context.target_skills,
                reason="低置信度，扩大允许来源",
            )
        )

    deduped: list[AgenticSearchQuery] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for query in queries:
        key = (query.text, query.source_types)
        if key not in seen:
            seen.add(key)
            deduped.append(query)
    return deduped[:max_queries]


def _rewrite_query(context: AgenticSearchContext) -> AgenticSearchQuery:
    """第二轮使用确定性扩展，避免额外模型思考。"""

    parts = [*context.target_skills[:5], context.job_description[:220]]
    if context.weakness_text:
        parts.append(context.weakness_text[:120])
    parts.extend(("核心原理", "项目实践", "追问"))
    return AgenticSearchQuery(
        text=" ".join(part.strip() for part in parts if part and part.strip())[:400],
        reason="一次性查询扩展",
    )


def _quality_from_state(state: _SearchState) -> EvidenceQuality:
    return grade_evidences(
        state.get("evidences", []),
        min_score=state.get("min_score", 0.3),
        min_evidences=state.get("min_evidences", 2),
        min_source_types=state.get("min_source_types", 2),
    )


async def _assess(state: _SearchState) -> dict[str, Any]:
    quality = _quality_from_state(state)
    return {
        "quality": quality,
        "triggered": not quality.passed,
        "trace": [{"step": "assess", "issues": list(quality.issues)}],
    }


def _after_assess(state: _SearchState) -> str:
    return "plan" if state.get("triggered") else END


async def _plan(state: _SearchState) -> dict[str, Any]:
    queries = build_search_plan(
        state["context"],
        state.get("evidences", []),
        state["quality"],
        max_queries=state.get("max_queries", 4),
    )
    return {
        "queries": queries,
        "rounds": 1 if queries else 0,
        "trace": [{"step": "plan", "query_count": len(queries)}],
    }


def _dispatch_queries(state: _SearchState) -> list[Send] | str:
    queries = state.get("queries", [])
    if not queries:
        return END
    return [
        Send("retrieve_one", {"query": query, "retrieve": state["retrieve"]})
        for query in queries
    ]


async def _retrieve_one(state: _SearchState) -> dict[str, Any]:
    query = state["query"]
    try:
        evidences = await state["retrieve"](query)
        return {
            "evidences": evidences,
            "trace": [{
                "step": "retrieve",
                "reason": query.reason,
                "source_types": list(query.source_types),
                "result_count": len(evidences),
            }],
        }
    except Exception as exc:
        return {
            "evidences": [],
            "trace": [{
                "step": "retrieve",
                "reason": query.reason,
                "source_types": list(query.source_types),
                "result_count": 0,
                "error_type": type(exc).__name__,
            }],
        }


async def _grade(state: _SearchState) -> dict[str, Any]:
    quality = _quality_from_state(state)
    return {
        "quality": quality,
        "trace": [{"step": "grade", "issues": list(quality.issues)}],
    }


def _after_grade(state: _SearchState) -> str:
    if state["quality"].passed:
        return END
    if state.get("rounds", 0) < state.get("max_rounds", 2):
        return "rewrite"
    return END


async def _rewrite(state: _SearchState) -> dict[str, Any]:
    query = _rewrite_query(state["context"])
    return {
        "queries": [query],
        "rounds": state.get("rounds", 0) + 1,
        "trace": [{"step": "rewrite", "query_count": 1}],
    }


def build_agentic_retrieval_graph():
    """构建无持久化、无副作用的有界检索图。"""

    graph = StateGraph(_SearchState)
    graph.add_node("assess", _assess)
    graph.add_node("plan", _plan)
    graph.add_node("retrieve_one", _retrieve_one)
    graph.add_node("grade", _grade)
    graph.add_node("rewrite", _rewrite)

    graph.add_edge(START, "assess")
    graph.add_conditional_edges("assess", _after_assess)
    graph.add_conditional_edges("plan", _dispatch_queries)
    graph.add_edge("retrieve_one", "grade")
    graph.add_conditional_edges("grade", _after_grade)
    graph.add_conditional_edges("rewrite", _dispatch_queries)
    return graph.compile()


_agentic_retrieval_graph = build_agentic_retrieval_graph()


async def run_agentic_retrieval(
    *,
    initial_evidences: Sequence[Any],
    context: AgenticSearchContext,
    retrieve: ReadOnlyRetriever,
    max_rounds: int = 2,
    max_queries: int = 4,
    min_score: float = 0.3,
    min_evidences: int = 2,
    min_source_types: int = 2,
) -> AgenticSearchOutcome:
    """执行受预算约束的 Agentic Retrieval。"""

    safe_max_rounds = min(max(int(max_rounds), 1), 2)
    safe_max_queries = min(max(int(max_queries), 1), 4)
    result = await _agentic_retrieval_graph.ainvoke({
        "context": context,
        "retrieve": retrieve,
        "evidences": list(initial_evidences),
        "rounds": 0,
        "max_rounds": safe_max_rounds,
        "max_queries": safe_max_queries,
        "min_score": min_score,
        "min_evidences": min_evidences,
        "min_source_types": min_source_types,
        "trace": [],
    })
    return AgenticSearchOutcome(
        triggered=bool(result.get("triggered")),
        evidences=list(result.get("evidences", [])),
        quality=result.get("quality") or grade_evidences([]),
        rounds=int(result.get("rounds", 0) or 0),
        trace=list(result.get("trace", [])),
    )
