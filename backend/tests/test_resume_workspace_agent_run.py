"""Focused contracts and lifecycle tests for the recoverable Resume Workspace."""

import sys
from types import ModuleType, SimpleNamespace

import pytest


def _competition_analysis() -> dict:
    """Return a contract-complete competition analysis fixture."""
    return {
        "overall_score": 82,
        "dimension_scores": {
            name: {"score": 82, "comment": f"{name} is strong"}
            for name in ("structure", "completeness", "quantification", "clarity", "highlights", "job_match")
        },
        "strengths": ["Python"],
        "weaknesses": ["Needs metrics"],
        "priority_improvements": ["Quantify impact"],
        "interview_insights": None,
    }


def _jd_match() -> dict:
    """Return a contract-complete JD matching fixture."""
    return {
        "overall_match_score": 81,
        "skill_match_score": 82,
        "project_match_score": 80,
        "experience_match_score": 81,
        "education_match_score": 79,
        "matched_keywords": ["Python"],
        "missing_keywords": ["Kubernetes"],
        "strengths": ["Backend experience"],
        "risks": ["Missing Kubernetes evidence"],
        "priority_actions": ["Clarify deployment work"],
        "selection_hints": {"focus": "backend"},
    }


def _pipeline_result() -> dict:
    """Return the minimum pipeline result that preserves a high-risk review item."""
    return {
        "jd_analysis": {"match_score": 78, "hr_pass_rate": 70, "keywords_required": ["Python"]},
        "material_pool": {},
        "change_items": [
            {
                "change_type": "fact_inference",
                "section_name": "项目经历",
                "original_text": "旧内容",
                "optimized_text": "主导平台迁移",
                "confidence": 0.7,
                "requires_user_confirmation": True,
                "reason": "突出匹配经验",
            }
        ],
        "assembled_resume": "主导平台迁移",
        "confirmation_items": [
            {
                "section_name": "项目经历",
                "change_type": "fact_inference",
                "original_text": "旧内容",
                "optimized_text": "主导平台迁移",
                "reason": "突出匹配经验",
                "confidence": 0.7,
            }
        ],
        "errors": [],
        "overall_confidence": 0.7,
        "requires_user_review": True,
    }


def test_resume_workspace_schema_accepts_one_resume_and_jd_contract():
    """The request and completed-result schemas expose the three workspace outputs."""
    from app.schemas.resume_schemas import (
        JDMatchResult,
        ResumeAnalyzeResult,
        ResumeOptimizeResult,
        ResumeWorkspaceRequest,
        ResumeWorkspaceResult,
    )

    request = ResumeWorkspaceRequest(resume_content="resume", job_description="jd", session_ids=["s1"])
    result = ResumeWorkspaceResult(
        result_id=1,
        competition_analysis=ResumeAnalyzeResult(**_competition_analysis()),
        jd_matching=JDMatchResult(**_jd_match()),
        content_optimization=ResumeOptimizeResult(
            match_score=78,
            hr_pass_rate=70,
            optimized_sections=[],
            key_improvements=[],
        ),
    )

    assert request.session_ids == ["s1"]
    assert result.competition_analysis.overall_score == 82
    assert result.jd_matching.overall_match_score == 81


def test_workspace_maps_richer_jd_result_into_pipeline_contract():
    """The optimizer must reuse the same non-zero JD score shown by the workspace."""
    from ai.workflows.agent_tasks.resume_workspace import _pipeline_jd_analysis

    mapped = _pipeline_jd_analysis(_jd_match())

    assert mapped["match_score"] == 81
    assert mapped["hr_pass_rate"] == 69
    assert mapped["keywords_required"] == ["Python", "Kubernetes"]


def test_public_workspace_result_repairs_legacy_zero_score():
    """Old persisted workspace records should expose the richer JD score to clients."""
    from ai.workflows.agent_tasks.resume_workspace import _public_workspace_result

    result_data = _pipeline_result()
    result_data["jd_analysis"] = {"match_score": 0, "hr_pass_rate": 0}
    result_data["workspace"] = {"jd_matching": _jd_match(), "competition_analysis": _competition_analysis()}

    public = _public_workspace_result(9, result_data)

    assert public["content_optimization"]["match_score"] == 81
    assert public["content_optimization"]["hr_pass_rate"] == 69


def test_resume_workspace_task_definition_exposes_recoverable_stages():
    """The registered task plan reports each business stage for polling and recovery UI."""
    from app.domain.agent_definitions import get_agent_definition

    definition = get_agent_definition("resume_workspace")

    assert definition.checkpoint_policy == "durable"
    assert [stage for stage, _title in definition.steps] == [
        "queued",
        "competition_analysis",
        "jd_matching",
        "content_optimization",
        "saving_result",
    ]


@pytest.mark.asyncio
async def test_resume_workspace_api_forwards_owner_payload_and_header_key(monkeypatch):
    """The route delegates only authenticated ownership and request data to the use case."""
    from app.api import agent_runs
    from ai.workflows.agent_runs import AgentRunResponse
    from app.schemas.resume_schemas import ResumeWorkspaceRequest

    received = {}

    async def create_resume_workspace(**kwargs):
        received.update(kwargs)
        return AgentRunResponse(payload={"task_type": "resume_workspace", "status": "queued"}, status_code=202)

    monkeypatch.setattr(agent_runs.agent_run_use_cases, "create_resume_workspace", create_resume_workspace)
    response = await agent_runs.create_resume_workspace_run(
        ResumeWorkspaceRequest(resume_content="private resume", job_description="private jd"),
        user_id="owner-1",
        idempotency_key="workspace-key",
    )

    assert getattr(response, "status_code", 200) == 202
    assert received["user_id"] == "owner-1"
    assert received["idempotency_key"] == "workspace-key"
    assert received["payload"]["resume_content"] == "private resume"


@pytest.mark.asyncio
async def test_resume_workspace_use_case_rejects_unowned_session(monkeypatch):
    """Referenced interview sessions must be owner-scoped before payload encryption."""
    from ai.workflows.agent_runs import AgentRunNotFound, AgentRunUseCases

    use_cases = AgentRunUseCases()

    async def get_session(session_id, *, user_id=None):
        assert session_id == "other-owner-session"
        assert user_id == "owner-1"
        return None

    monkeypatch.setattr(use_cases._session_repo, "get_session", get_session)
    with pytest.raises(AgentRunNotFound):
        await use_cases.create_resume_workspace(
            payload={"session_ids": ["other-owner-session"]},
            user_id="owner-1",
            idempotency_key="key",
        )


@pytest.mark.asyncio
async def test_resume_workspace_executor_persists_parent_and_reuses_after_crash(monkeypatch):
    """The executor stores all outputs once and retains pending human review on retry."""
    from ai.workflows.agent_tasks import resume_workspace
    from ai.workflows.agent_tasks.types import DeferredExecutionResult

    progress_stages: list[str] = []
    save_calls: list[dict] = []
    stored: dict | None = None

    class FakeResumeRepo:
        async def get_result_by_agent_run_id(self, agent_run_id, user_id):
            assert agent_run_id == "workspace-run"
            assert user_id == "owner-1"
            if stored is None:
                return None
            return {"id": 9, "result_data": stored}

        async def save_result(self, **kwargs):
            nonlocal stored
            save_calls.append(kwargs)
            stored = kwargs["result_data"]
            return 9

    async def progress(stage):
        progress_stages.append(stage)

    async def unexpected_pipeline(**_kwargs):
        raise AssertionError("persisted workspace result must prevent regeneration")

    monkeypatch.setattr("app.db.repositories.resume.resume_repo.get_resume_repo", lambda: FakeResumeRepo())
    analyzer_module = ModuleType("ai.agents.resume.resume_analyzer_graph")
    setattr(analyzer_module, "analyze_resume", lambda **_kwargs: _async_result(_competition_analysis()))
    matcher_module = ModuleType("ai.agents.resume.jd_matcher")
    setattr(matcher_module, "analyze_jd_match", lambda **_kwargs: _async_result(_jd_match()))
    orchestrator_module = ModuleType("ai.agents.resume.resume_orchestrator")
    setattr(orchestrator_module, "run_pipeline", lambda **_kwargs: _async_result(_pipeline_result()))
    monkeypatch.setitem(sys.modules, analyzer_module.__name__, analyzer_module)
    monkeypatch.setitem(sys.modules, matcher_module.__name__, matcher_module)
    monkeypatch.setitem(sys.modules, orchestrator_module.__name__, orchestrator_module)

    result = await resume_workspace.execute_resume_workspace(
        {"_agent_run_id": "workspace-run", "resume_content": "resume", "job_description": "jd", "session_ids": []},
        "owner-1",
        progress,
    )

    assert isinstance(result, DeferredExecutionResult)
    assert progress_stages == ["competition_analysis", "jd_matching", "content_optimization", "saving_result"]
    public_result = await result.persist(SimpleNamespace())  # type: ignore[arg-type]
    assert public_result["competition_analysis"]["overall_score"] == 82
    assert public_result["jd_matching"]["overall_match_score"] == 81
    assert public_result["review"]["status"] == "pending"
    assert save_calls[0]["result_type"] == "optimize"
    assert save_calls[0]["agent_run_id"] == "workspace-run"

    setattr(orchestrator_module, "run_pipeline", unexpected_pipeline)
    retried = await resume_workspace.execute_resume_workspace(
        {"_agent_run_id": "workspace-run", "resume_content": "resume", "job_description": "jd", "session_ids": []},
        "owner-1",
        progress,
    )
    assert isinstance(retried, dict)
    assert retried["result_id"] == 9
    assert len(save_calls) == 1


async def _async_result(value):
    """Adapt deterministic fixtures to the async agent interfaces used by the executor."""
    return value
