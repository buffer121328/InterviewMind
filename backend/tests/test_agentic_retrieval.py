"""有界 Agentic Retrieval 单元测试。"""

from dataclasses import dataclass

import pytest

from app.agents.interview.agentic_retrieval import (
    AgenticSearchContext,
    build_search_plan,
    grade_evidences,
    run_agentic_retrieval,
)


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
        evidence=f"{source_type}-{source_id}",
        retrieval_score=score,
    )


def test_grade_evidences_detects_quality_gaps():
    quality = grade_evidences([_evidence("question_bank", "1", 0.1)])

    assert quality.passed is False
    assert "insufficient_evidence" in quality.issues
    assert "all_low_score_evidence" in quality.issues
    assert "insufficient_source_coverage" in quality.issues


def test_search_plan_is_source_aware_and_bounded():
    initial = [_evidence("question_bank", "1", 0.1)]
    quality = grade_evidences(initial)

    plan = build_search_plan(
        AgenticSearchContext(
            job_description="Python FastAPI 后端工程师",
            target_skills=("Python", "FastAPI"),
            weakness_text="系统设计薄弱",
        ),
        initial,
        quality,
        max_queries=2,
    )

    assert len(plan) == 2
    assert all("question_bank" not in query.source_types for query in plan)


@pytest.mark.asyncio
async def test_good_evidence_uses_fast_path_without_retrieval():
    calls = []

    async def retrieve(query):
        calls.append(query)
        return []

    outcome = await run_agentic_retrieval(
        initial_evidences=[
            _evidence("question_bank", "1"),
            _evidence("candidate_material", "2"),
        ],
        context=AgenticSearchContext(job_description="Python 后端工程师"),
        retrieve=retrieve,
    )

    assert outcome.triggered is False
    assert outcome.rounds == 0
    assert calls == []


@pytest.mark.asyncio
async def test_low_quality_evidence_triggers_bounded_parallel_search():
    calls = []

    async def retrieve(query):
        calls.append(query)
        source_type = query.source_types[0] if query.source_types else "question_bank"
        return [_evidence(source_type, str(len(calls)), 0.8)]

    outcome = await run_agentic_retrieval(
        initial_evidences=[_evidence("question_bank", "initial", 0.1)],
        context=AgenticSearchContext(
            job_description="Python FastAPI 后端工程师",
            weakness_text="系统设计薄弱",
        ),
        retrieve=retrieve,
        max_queries=2,
    )

    assert outcome.triggered is True
    assert outcome.rounds == 1
    assert len(calls) == 2
    assert outcome.quality.passed is True


@pytest.mark.asyncio
async def test_failed_retrieval_stops_after_two_rounds():
    calls = []

    async def retrieve(query):
        calls.append(query)
        raise RuntimeError("temporary failure")

    outcome = await run_agentic_retrieval(
        initial_evidences=[],
        context=AgenticSearchContext(job_description="Java 后端工程师"),
        retrieve=retrieve,
        max_queries=2,
        max_rounds=9,
    )

    assert outcome.triggered is True
    assert outcome.rounds == 2
    assert len(calls) == 3  # 第一轮 2 个并行请求 + 第二轮 1 个改写请求
    assert outcome.quality.passed is False
    assert any(item.get("error_type") == "RuntimeError" for item in outcome.trace)
