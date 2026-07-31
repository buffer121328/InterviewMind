"""ATDD contracts for Phase 4 resume context, parallelism, and review governance."""

import asyncio
from typing import Any

import pytest


def _competition_result() -> dict[str, Any]:
    """Return a compact successful competition-analysis fixture."""
    return {
        "overall_score": 82,
        "dimension_scores": {},
        "strengths": ["Python 项目证据"],
        "weaknesses": [],
        "priority_improvements": [],
        "interview_insights": None,
    }


def _match_result() -> dict[str, Any]:
    """Return a compact successful JD-match fixture."""
    return {
        "overall_match_score": 80,
        "skill_match_score": 80,
        "project_match_score": 80,
        "experience_match_score": 80,
        "education_match_score": 80,
        "matched_keywords": ["Python"],
        "missing_keywords": ["Kubernetes"],
        "strengths": ["Python 项目证据"],
        "risks": ["未体现 Kubernetes"],
        "priority_actions": ["确认部署经验"],
        "selection_hints": {},
    }


def _pipeline_result() -> dict[str, Any]:
    """Return an optimization result that must remain pending human review."""
    return {
        "jd_analysis": {"match_score": 80, "hr_pass_rate": 68},
        "material_pool": {},
        "change_items": [{
            "section_name": "项目经历",
            "original_text": "参与平台开发",
            "optimized_text": "主导平台开发",
            "change_type": "fact_inference",
            "requires_user_confirmation": True,
            "confidence": 0.6,
            "reason": "职责级别需确认",
        }],
        "assembled_resume": "主导平台开发",
        "confirmation_items": [{
            "section_name": "项目经历",
            "change_type": "fact_inference",
            "original_text": "参与平台开发",
            "optimized_text": "主导平台开发",
            "reason": "职责级别需确认",
            "confidence": 0.6,
        }],
        "errors": [],
        "requires_user_review": True,
        "overall_confidence": 0.6,
    }


def test_resume_context_cache_is_owner_isolated_and_source_sensitive():
    """Cache identity must change across owners and source updates."""
    from ai.agents.resume.resume_context import (
        clear_resume_context_cache,
        get_resume_context,
    )

    clear_resume_context_cache()
    args = {
        "resume_content": "Python 工程师，参与订单平台开发",
        "job_description": "需要 Python 与 Kubernetes",
    }
    first = get_resume_context(owner_id="owner-a", **args)
    same = get_resume_context(owner_id="owner-a", **args)
    other_owner = get_resume_context(owner_id="owner-b", **args)
    updated = get_resume_context(
        owner_id="owner-a",
        resume_content=args["resume_content"] + "\n新增 Redis 证据",
        job_description=args["job_description"],
    )

    assert first[3] == same[3]
    assert first[3] != other_owner[3]
    assert first[3] != updated[3]


def test_absent_capability_is_not_promoted_to_resume_fact():
    """A JD-only requirement may be missing but can never become a candidate skill fact."""
    from ai.agents.resume.resume_context import assemble_resume_context

    bundle = assemble_resume_context(
        owner_id="owner-a",
        resume_content="Python 后端工程师，参与订单平台开发",
        job_description="要求 Kubernetes 集群运维经验",
    )

    assert all("Kubernetes" not in item for item in bundle.fact_sheet.skills)
    assert bundle.fact_sheet.unsupported_gaps == []
    assert any("Kubernetes" in item for item in bundle.match_map.missing_requirements)


@pytest.mark.asyncio
async def test_generation_fact_check_uses_compact_facts_not_raw_resume_tail(monkeypatch):
    """Fact check consumes bounded facts and change output rather than the complete raw resume."""
    from ai.agents.resume import resume_generation_graph as graph
    from app.schemas.llm_outputs import FactCheckOutput

    captured: dict[str, Any] = {}

    async def fake_invoke(prompt, output_model, *args, **kwargs):
        captured["prompt"] = prompt
        captured["metadata"] = kwargs.get("call_metadata")
        captured["channel"] = kwargs.get("channel")
        captured["temperature"] = kwargs.get("temperature")
        assert output_model is FactCheckOutput
        return FactCheckOutput(is_excessive=False, risk_details=[])

    monkeypatch.setattr("ai.agents.resume.resume_generation_review.invoke_structured", fake_invoke)
    raw_resume = "Python 后端经验\n" + "A" * 12_000 + "RAW_RESUME_TAIL_MARKER"
    result = await graph.node_fact_check({
        "resume_content": raw_resume,
        "optimized_draft": "# 简历\nPython 后端经验",
        "draft_content": "",
        "user_answers": {},
        "api_config": None,
    })

    assert result["fact_check_result"]["is_excessive"] is False
    assert "RAW_RESUME_TAIL_MARKER" not in captured["prompt"]
    assert captured["metadata"]["stage"] == "fact_check"
    assert captured["channel"] == "reflector"
    assert captured["temperature"] == 0.0


@pytest.mark.asyncio
async def test_workspace_parallel_branches_share_deadline_and_preserve_success(monkeypatch):
    """Both analyses start concurrently and one failure cannot overwrite the successful branch."""
    from ai.agents.resume import jd_matcher, resume_analyzer_graph, resume_orchestrator
    from ai.workflows.agent_tasks import resume_workspace

    started: set[str] = set()
    both_started = asyncio.Event()
    calls: list[tuple[str, int, str]] = []

    async def analyze_resume(**kwargs):
        started.add("competition")
        calls.append(("competition", id(kwargs["deadline"]), kwargs["call_metadata"]["input_fingerprint"]))
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.5)
        raise RuntimeError("competition unavailable")

    async def analyze_match(**kwargs):
        started.add("match")
        calls.append(("match", id(kwargs["deadline"]), kwargs["call_metadata"]["input_fingerprint"]))
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.5)
        return _match_result()

    async def run_pipeline(**kwargs):
        calls.append(("pipeline", id(kwargs["deadline"]), "pipeline"))
        return _pipeline_result()

    class FakeRepo:
        async def save_result(self, **kwargs):
            self.saved = kwargs["result_data"]
            return 7

    repo = FakeRepo()
    monkeypatch.setattr(resume_analyzer_graph, "analyze_resume", analyze_resume)
    monkeypatch.setattr(jd_matcher, "match_jd", analyze_match)
    monkeypatch.setattr(resume_orchestrator, "run_pipeline", run_pipeline)
    monkeypatch.setattr("app.db.repositories.resume.resume_repo.get_resume_repo", lambda: repo)

    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    result = await resume_workspace.execute_resume_workspace(
        {
            "resume_content": "Python 后端工程师，参与订单平台开发",
            "job_description": "需要 Python 与 Kubernetes",
            "session_ids": [],
        },
        "owner-a",
        progress,
    )

    assert started == {"competition", "match"}
    assert calls[0][1] == calls[1][1] == calls[2][1]
    assert calls[0][2] == calls[1][2]
    assert result["competition_analysis"]["degraded"] is True
    assert result["jd_matching"]["overall_match_score"] == 80
    assert result["review"]["status"] == "pending"
    assert stages == ["competition_analysis", "jd_matching", "content_optimization", "saving_result"]
