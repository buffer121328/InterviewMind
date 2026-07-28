"""Regression tests for staged resume generation and direct AgentRun visibility."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_no_gap_initialization_returns_before_draft_generation(monkeypatch):
    """The init request finishes after requirement analysis so the browser can poll real later stages."""
    from ai.agents.resume import resume_generation_graph
    from ai.agents.resume import resume_generation_sessions as sessions

    created: list[dict] = []
    updated: list[dict] = []

    async def create(**kwargs):
        created.append(kwargs)

    async def update(*_args, **kwargs):
        updated.append(kwargs)

    async def analyze(_state):
        return {"missing_info_analysis": {"has_gaps": False}, "questions": []}

    async def unexpected_complete(*_args, **_kwargs):
        raise AssertionError("draft generation must start through the submit endpoint")

    monkeypatch.setattr(sessions.session_store, "create", create)
    monkeypatch.setattr(sessions.session_store, "update", update)
    monkeypatch.setattr(resume_generation_graph, "node_analyze_needs", analyze)
    monkeypatch.setattr(sessions, "_complete_generation", unexpected_complete)

    result = await sessions.init_generation_session(
        resume_content="# 简历",
        job_description="AI 应用开发工程师",
        optimization_result={},
        user_id="owner-1",
    )

    assert result["needs_input"] is False
    assert result["result"] is None
    assert created[0]["user_id"] == "owner-1"
    assert updated[-1]["status"] == "ready_to_generate"


@pytest.mark.asyncio
async def test_submit_creates_visible_resume_generation_agent_run(monkeypatch):
    """Direct professional-resume generation owns a Run Center record linked to the generation session."""
    from ai.agents.resume import resume_generation_sessions as sessions
    from ai.runtime.agent_runs import service as run_service_module

    session = SimpleNamespace(
        status="ready_to_generate",
        generated_resume_id=None,
        resume_content="# 原简历",
        job_description="AI Agent 开发",
        optimization_result={},
        template_style="professional",
        user_id="owner-1",
        agent_run_id=None,
        questions=[],
    )
    updates: list[dict] = []
    run_calls: list[dict] = []
    captured_state: dict = {}

    async def get(_session_id, user_id=None):
        assert user_id == "owner-1"
        return session

    async def update(*_args, **kwargs):
        updates.append(kwargs)

    async def create_inline_or_get(_self, **kwargs):
        run_calls.append(kwargs)
        return SimpleNamespace(id="run-resume-1"), True

    async def complete(_session_id, state, _api_config):
        captured_state.update(state)
        return {"resume_id": 7, "title": "新简历", "content": "# 新简历"}

    monkeypatch.setattr(sessions.session_store, "get", get)
    monkeypatch.setattr(sessions.session_store, "update", update)
    monkeypatch.setattr(run_service_module.AgentRunService, "create_inline_or_get", create_inline_or_get)
    monkeypatch.setattr(sessions, "_complete_generation", complete)

    result = await sessions.submit_user_answers("generation-1", {}, "owner-1")

    assert result["resume_id"] == 7
    assert run_calls[0]["task_type"] == "resume_generation"
    assert run_calls[0]["idempotency_key"] == "generation-1"
    assert run_calls[0]["payload"] == {"generation_session_id": "generation-1"}
    assert updates[0]["agent_run_id"] == "run-resume-1"
    assert captured_state["agent_run_id"] == "run-resume-1"
    assert captured_state["manage_agent_run"] is True
