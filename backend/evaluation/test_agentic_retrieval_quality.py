"""Agentic Retrieval 离线 DeepEval 回归评测。

这些评测不调用 LLM/数据库，使用确定性 retriever 和 DeepEval 自定义指标，验证
有界 agentic retrieval 的触发、预算、fast path，以及 RAG shadow/active adopt 策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

pytest.importorskip("deepeval")

from deepeval import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

import ai.agents.interview.interview_rag as rag_module
from ai.agents.interview.agentic_retrieval import (
    AgenticSearchContext,
    AgenticSearchQuery,
    run_agentic_retrieval,
)
from ai.agents.interview.interview_rag import RagEvidence, RetrievalQuery


@dataclass
class Evidence:
    source_type: str
    source_id: str
    evidence: str
    retrieval_score: float


def _evidence(source_type: str, source_id: str, score: float = 0.8) -> Evidence:
    return Evidence(
        source_type=source_type,
        source_id=source_id,
        evidence=f"{source_type}:{source_id}",
        retrieval_score=score,
    )


class AgenticRetrievalControlMetric(BaseMetric):
    """DeepEval 确定性指标：验证 agentic retrieval 控制流与质量结果。"""

    def __init__(self):
        self.threshold = 1.0
        self.score = None
        self.reason = None
        self.success = None
        self.async_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        metadata = test_case.metadata or {}
        checks = {
            "triggered": metadata.get("triggered") == metadata.get("expected_triggered"),
            "round_budget": int(metadata.get("rounds", 999)) <= int(metadata.get("max_rounds", 2)),
            "query_budget": int(metadata.get("retrieve_calls", 999)) <= int(metadata.get("max_retrieve_calls", 4)),
            "quality": metadata.get("quality_passed") == metadata.get("expected_quality_passed"),
        }
        self.success = all(checks.values())
        self.score = 1.0 if self.success else sum(checks.values()) / len(checks)
        self.reason = f"checks={checks}, metadata={metadata}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "Agentic Retrieval Control"


class AgenticAdoptionPolicyMetric(BaseMetric):
    """DeepEval 确定性指标：验证 RAG agentic shadow/active adopt 策略。"""

    def __init__(self):
        self.threshold = 1.0
        self.score = None
        self.reason = None
        self.success = None
        self.async_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        metadata = test_case.metadata or {}
        checks = {
            "mode": metadata.get("agentic_mode") == metadata.get("expected_agentic_mode"),
            "triggered": metadata.get("agentic_triggered") is True,
            "adopted": metadata.get("agentic_adopted") == metadata.get("expected_agentic_adopted"),
            "retrieval_mode": metadata.get("retrieval_mode") == metadata.get("expected_retrieval_mode"),
            "evidence_count": int(metadata.get("evidence_count", -1)) == int(metadata.get("expected_evidence_count")),
        }
        self.success = all(checks.values())
        self.score = 1.0 if self.success else sum(checks.values()) / len(checks)
        self.reason = f"checks={checks}, metadata={metadata}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "Agentic Adoption Policy"


@pytest.mark.fast
@pytest.mark.eval
@pytest.mark.asyncio
async def test_deepeval_agentic_retrieval_triggers_within_budget_and_improves_quality():
    calls: list[AgenticSearchQuery] = []

    async def retrieve(query: AgenticSearchQuery):
        calls.append(query)
        source_type = query.source_types[0] if query.source_types else "candidate_material"
        return [_evidence(source_type, f"hit-{len(calls)}", 0.9)]

    outcome = await run_agentic_retrieval(
        initial_evidences=[_evidence("question_bank", "low", 0.1)],
        context=AgenticSearchContext(
            job_description="Python FastAPI backend engineer with system design expectations",
            target_skills=("FastAPI", "System Design"),
            weakness_text="cache consistency and microservice boundary weakness",
        ),
        retrieve=retrieve,
        max_rounds=2,
        max_queries=2,
    )

    assert_test(
        LLMTestCase(
            name="agentic_trigger_budget_quality",
            input="low quality single-source evidence",
            actual_output=str(outcome.trace),
            metadata={
                "triggered": outcome.triggered,
                "expected_triggered": True,
                "rounds": outcome.rounds,
                "max_rounds": 2,
                "retrieve_calls": len(calls),
                "max_retrieve_calls": 2,
                "quality_passed": outcome.quality.passed,
                "expected_quality_passed": True,
            },
        ),
        [AgenticRetrievalControlMetric()],
    )


@pytest.mark.fast
@pytest.mark.eval
@pytest.mark.asyncio
async def test_deepeval_agentic_retrieval_fast_path_does_not_search():
    calls: list[AgenticSearchQuery] = []

    async def retrieve(query: AgenticSearchQuery):
        calls.append(query)
        return []

    outcome = await run_agentic_retrieval(
        initial_evidences=[
            _evidence("question_bank", "q1", 0.8),
            _evidence("candidate_material", "m1", 0.8),
        ],
        context=AgenticSearchContext(job_description="Python backend engineer"),
        retrieve=retrieve,
    )

    assert_test(
        LLMTestCase(
            name="agentic_fast_path_no_search",
            input="good multi-source evidence",
            actual_output=str(outcome.trace),
            metadata={
                "triggered": outcome.triggered,
                "expected_triggered": False,
                "rounds": outcome.rounds,
                "max_rounds": 0,
                "retrieve_calls": len(calls),
                "max_retrieve_calls": 0,
                "quality_passed": outcome.quality.passed,
                "expected_quality_passed": True,
            },
        ),
        [AgenticRetrievalControlMetric()],
    )


class _SingleSourceRepo:
    """始终只返回 question_bank 证据，用于验证 active 不应采纳无提升结果。"""

    async def search_structured(self, **kwargs):
        return []

    async def search_by_vector(self, **kwargs):
        return []

    async def search_by_text(self, **kwargs):
        return [{
            "source_type": "question_bank",
            "source_id": "q-only",
            "content": "FastAPI dependency injection question",
            "metadata": {},
            "text_score": 1.0,
        }]


class _ImprovingRepo:
    """初始召回单来源；agentic source-specific 查询能补充多来源证据。"""

    async def search_structured(self, **kwargs):
        return []

    async def search_by_vector(self, **kwargs):
        return []

    async def search_by_text(self, **kwargs):
        source_types = kwargs.get("source_types") or ["question_bank"]
        source_type = source_types[0]
        return [{
            "source_type": source_type,
            "source_id": f"{source_type}-hit",
            "content": f"{source_type} FastAPI system design evidence",
            "metadata": {},
            "text_score": 1.0,
        }]


async def _empty_memory(**_kwargs: Any) -> list[RagEvidence]:
    return []


@pytest.mark.fast
@pytest.mark.eval
@pytest.mark.parametrize(
    "mode,repo,expected_adopted,expected_retrieval_mode,expected_evidence_count",
    [
        ("shadow", _ImprovingRepo(), False, "structured", 1),
        ("active", _SingleSourceRepo(), False, "structured", 1),
        ("active", _ImprovingRepo(), True, "agentic_hybrid", 2),
    ],
    ids=["shadow_never_adopts", "active_rejects_no_improvement", "active_adopts_improvement"],
)
@pytest.mark.asyncio
async def test_deepeval_rag_agentic_adoption_policy(
    monkeypatch,
    mode: str,
    repo,
    expected_adopted: bool,
    expected_retrieval_mode: str,
    expected_evidence_count: int,
):
    from app.db.repositories.interview import rag_index_repo

    monkeypatch.setattr(rag_index_repo, "get_rag_index_repo", lambda: repo)
    monkeypatch.setattr(rag_module, "VECTOR_ENABLED", False)
    monkeypatch.setattr(rag_module, "AGENTIC_MODE", mode)
    monkeypatch.setattr(rag_module, "AGENTIC_MAX_QUERIES", 2)
    monkeypatch.setattr(rag_module, "_retrieve_memory_evidences", _empty_memory)

    result = await rag_module.run_rag_pipeline(
        user_id="user-1",
        job_description="Python FastAPI backend engineer",
        target_skills=["FastAPI"],
    )

    assert_test(
        LLMTestCase(
            name=f"rag_agentic_adoption_{mode}_{expected_adopted}",
            input="single-source initial RAG evidence",
            actual_output=str(result.retrieval_trace),
            metadata={
                "agentic_mode": result.retrieval_trace["agentic_mode"],
                "expected_agentic_mode": mode,
                "agentic_triggered": result.retrieval_trace["agentic_triggered"],
                "agentic_adopted": result.retrieval_trace["agentic_adopted"],
                "expected_agentic_adopted": expected_adopted,
                "retrieval_mode": result.retrieval_mode,
                "expected_retrieval_mode": expected_retrieval_mode,
                "evidence_count": len(result.evidences),
                "expected_evidence_count": expected_evidence_count,
            },
        ),
        [AgenticAdoptionPolicyMetric()],
    )
