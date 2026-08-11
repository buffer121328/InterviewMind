"""Phase 3 acceptance tests for resilient calls, context integrity, and background work."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def test_resume_section_checkpoint_reuses_only_matching_sources():
    """Completed sections are reusable only while authoritative source fingerprints match."""
    from ai.agents.resume.resume_sections import (
        build_section_checkpoint,
        reusable_sections,
    )

    checkpoint = build_section_checkpoint(
        markdown="# 张三\n## 个人总结\n后端工程师\n## 项目经历\n支付平台",
        resume_content="原简历",
        job_description="后端 JD",
    )
    assert reusable_sections(checkpoint, resume_content="原简历", job_description="后端 JD")
    assert reusable_sections(checkpoint, resume_content="已修改", job_description="后端 JD") == {}


def test_resume_section_retry_merges_only_targeted_patch():
    """A verifier issue targets one section without replacing unaffected content."""
    from ai.agents.resume.resume_sections import (
        merge_section_patch,
        select_retry_sections,
    )

    sections = {"summary": "旧总结", "projects": "旧项目", "skills": "Python"}
    retry = select_retry_sections([{"location": "项目经历", "reason": "缺少证据"}], available_sections=sections)
    assert retry == ("projects",)
    assert merge_section_patch(sections, {"projects": "新项目"}) == {
        "summary": "旧总结", "projects": "新项目", "skills": "Python"
    }


def test_authoritative_context_never_uses_silent_head_tail_truncation():
    """JD/resume/Q&A authoritative sources remain complete and expose integrity metadata."""
    from ai.runtime.authoritative_context import assemble_authoritative_context

    text = "事实" * 5000
    assembled = assemble_authoritative_context(
        agent_name="phase3-test",
        sources={"resume": text, "job_description": text, "current_qa": text},
    )
    assert text in assembled.model_context
    assert assembled.metadata["authoritative_source_truncated"] is False
    assert set(assembled.metadata["source_fingerprints"]) == {"resume", "job_description", "current_qa"}


def test_reviewer_contexts_are_perspective_specific_and_evidence_bound():
    """Each reviewer receives a distinct minimal view while retaining question references."""
    from ai.workflows.analysis.reviewer_contexts import build_reviewer_contexts

    contexts = build_reviewer_contexts(
        resume="FastAPI 工程师",
        job_description="需要 Python 与系统设计",
        company_info="SaaS",
        evidence=[{
            "question_id": "Q1", "question_summary": "系统设计", "candidate_claims": ["设计过限流"],
            "demonstrated_skills": ["Python"], "missing_evidence": ["容量数据"],
            "communication_observations": ["结构清晰"],
        }],
    )
    assert len(set(contexts.values())) == 4
    assert all("Q1" in value for value in contexts.values())
    assert "SaaS" in contexts["job_fit"]
    assert "容量数据" in contexts["factual_risk"]


def test_dynamic_ability_reviewers_skip_unneeded_perspectives():
    """Reviewer selection uses evidence coverage and short-circuits empty samples."""
    from ai.workflows.analysis.reviewer_contexts import select_ability_reviewers

    assert select_ability_reviewers([]) == ()
    selected = select_ability_reviewers([
        {"communication": {"score": 8}, "professional_competence": {"score": 7}},
        {"communication": {"score": 6}, "professional_competence": {"score": 8}, "recommendation": "hire"},
    ])
    assert {"technical_depth", "communication", "factual_risk"}.issubset(selected)


def test_ability_profile_is_registered_as_agent_run_task():
    """Ability profile uses the same recoverable registry and plan as other AgentRuns."""
    from ai.workflows.agent_tasks.registry import get_production_adapter_registry
    from app.domain.agent_definitions import get_agent_definition
    from app.domain.agent_runs import TASK_TYPE_ABILITY_PROFILE

    assert TASK_TYPE_ABILITY_PROFILE in set(get_production_adapter_registry().keys())
    definition = get_agent_definition(TASK_TYPE_ABILITY_PROFILE)
    assert definition.checkpoint_policy == "durable"
    assert definition.steps[-1][0] == "saving_profile"


@pytest.mark.asyncio
async def test_embedding_batch_deduplicates_and_reuses_cache(monkeypatch):
    """Duplicate text is embedded once per model fingerprint and reused on later calls."""
    from ai.rag import embedding_service

    embedding_service.clear_embedding_cache()
    calls: list[list[str]] = []

    async def fake_create(inputs, **_kwargs):
        values = list(inputs) if isinstance(inputs, list) else [inputs]
        calls.append(values)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[float(len(value)), 1.0]) for value in values])

    monkeypatch.setattr(embedding_service.llms.model_gateway, "create_embeddings", fake_create)
    monkeypatch.setattr(embedding_service, "get_settings", lambda: SimpleNamespace(embedding_timeout_seconds=8.0))
    first = await embedding_service.generate_embeddings_batch(
        ["alpha", "alpha", "beta"], model="m", dimensions=2, batch_size=10
    )
    second = await embedding_service.generate_embeddings_batch(
        ["beta", "alpha"], model="m", dimensions=2, batch_size=10
    )
    assert first[0] == first[1]
    assert second == [first[2], first[0]]
    assert calls == [["alpha", "beta"]]


@pytest.mark.asyncio
async def test_report_memory_schedule_is_non_blocking(monkeypatch):
    """Optional mem0 report writes run through the governed background task helper."""
    from ai.workflows.interview import report_memory

    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_persist(**_kwargs):
        started.set()
        await release.wait()
        return 1

    created: list[str] = []

    def fake_background(coro, name):
        created.append(name)
        return asyncio.create_task(coro, name=name)

    monkeypatch.setattr(report_memory, "persist_interview_report_memories", fake_persist)
    monkeypatch.setattr("ai.runtime.background_tasks.create_background_task", fake_background)
    task = report_memory.schedule_interview_report_memories(
        user_id="u1", session_id="s1", profile={}, weakness_report={}, api_config=None
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert not task.done()
    assert created == ["report-memory:s1"]
    release.set()
    assert await task == 1


def test_phase3_budget_configuration_has_safe_attempt_relationship():
    """Interactive and voice deadlines reserve enough time before starting another attempt."""
    from ai.runtime.call_budgets import CallBudget, validate_call_budget

    validate_call_budget(CallBudget(node_timeout=12, task_deadline=30, max_attempts=1, min_remaining=3))
    with pytest.raises(ValueError):
        validate_call_budget(CallBudget(node_timeout=20, task_deadline=20, max_attempts=1, min_remaining=3))
