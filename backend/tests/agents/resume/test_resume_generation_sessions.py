"""Regression tests for staged resume generation and direct AgentRun visibility."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

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
async def test_submit_uses_workflow_injected_resume_generation_run(monkeypatch):
    """Agent session code consumes a run reference without importing AgentRun runtime."""
    from ai.agents.resume import resume_generation_sessions as sessions

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
    captured_state: dict = {}
    captured_callback: dict = {}

    async def get(_session_id, user_id=None):
        assert user_id == "owner-1"
        return session

    async def update(*_args, **kwargs):
        updates.append(kwargs)

    async def complete(_session_id, state, _api_config, **kwargs):
        captured_state.update(state)
        captured_callback.update(kwargs)
        return {"resume_id": 7, "title": "新简历", "content": "# 新简历"}

    monkeypatch.setattr(sessions.session_store, "get", get)
    monkeypatch.setattr(sessions.session_store, "update", update)
    monkeypatch.setattr(sessions, "_complete_generation", complete)

    async def mark_stage(_stage: str) -> None:
        """Test stage callback."""

    result = await sessions.submit_user_answers(
        "generation-1",
        {},
        "owner-1",
        agent_run_id="run-resume-1",
        run_stage_callback=mark_stage,
    )

    assert result["resume_id"] == 7
    assert updates[0]["agent_run_id"] == "run-resume-1"
    assert captured_state["agent_run_id"] == "run-resume-1"
    assert captured_callback["run_stage_callback"] is mark_stage


@pytest.mark.asyncio
async def test_generation_workflow_routes_agent_run_lifecycle_through_session_driver(monkeypatch):
    """SessionDriver creates, advances, and completes the visible resume-generation run."""
    from contextlib import asynccontextmanager

    from ai.workflows.resume import generation

    run = SimpleNamespace(id="run-resume-1", status="running")
    created: list[dict] = []
    stages: list[tuple[str, str]] = []
    succeeded: list[tuple[str, dict]] = []
    submitted: dict = {}
    observations: list[dict] = []

    async def create_inline_or_get(_self, **kwargs):
        created.append(kwargs)
        return run, True

    async def mark_stage(_self, run_id, stage):
        stages.append((run_id, stage))

    async def succeed(_self, run_id, result):
        succeeded.append((run_id, result))

    async def fail(_self, _run_id, _message):
        raise AssertionError("successful workflow must not fail the run")

    async def is_cancel_requested(_self, _run_id):
        return False

    async def mark_cancelled(_self, _run_id, _message="任务已取消"):
        raise AssertionError("successful workflow must not cancel the run")

    async def submit(**kwargs):
        submitted.update(kwargs)
        await kwargs["run_stage_callback"]("draft_optimization")
        return {"resume_id": 7, "title": "新简历", "content": "# 新简历"}

    @asynccontextmanager
    async def observe(**kwargs):
        observations.append(kwargs)
        yield SimpleNamespace(set_output=lambda _output: None)

    monkeypatch.setattr(generation.AgentRunService, "create_inline_or_get", create_inline_or_get)
    monkeypatch.setattr(generation.AgentRunService, "mark_stage", mark_stage)
    monkeypatch.setattr(generation.AgentRunService, "succeed", succeed)
    monkeypatch.setattr(generation.AgentRunService, "fail", fail)
    monkeypatch.setattr(generation.AgentRunService, "is_cancel_requested", is_cancel_requested)
    monkeypatch.setattr(generation.AgentRunService, "mark_cancelled", mark_cancelled)
    monkeypatch.setattr(generation, "submit_user_answers", submit)
    monkeypatch.setattr(generation, "agent_observation", observe)
    session = SimpleNamespace(
        session_id="generation-1",
        status="awaiting_input",
        questions=["q"],
        agent_run_id=None,
        generated_resume_id=None,
        resume_content="# 简历",
        job_description="AI Agent",
    )
    monkeypatch.setattr(generation.session_store, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(
        generation.session_store,
        "claim_continuation",
        AsyncMock(return_value=SimpleNamespace(status="draft_generation", generated_resume_id=None)),
    )
    bind_continuation_run = AsyncMock()
    monkeypatch.setattr(
        generation.session_store,
        "bind_continuation_run",
        bind_continuation_run,
    )
    monkeypatch.setattr(generation.session_store, "update", AsyncMock())

    response = await generation.ResumeGenerationUseCases().submit_generation_answers(
        request=SimpleNamespace(
            session_id="generation-1",
            answers={"q": "a"},
            api_config=SimpleNamespace(model_dump=lambda: {"fast": {"model": "mock"}}),
        ),
        user_id="owner-1",
    )

    assert response.resume_id == 7
    assert created[0]["task_type"] == "resume_generation"
    assert created[0]["idempotency_key"].startswith("resume-generation:generation-1:")
    assert created[0]["payload"]["generation_session_id"] == "generation-1"
    assert created[0]["payload"]["answer_count"] == 1
    assert set(created[0]["payload"]) == {
        "generation_session_id",
        "answer_count",
        "continuation_digest",
    }
    assert all(value != "a" for value in created[0]["payload"].values())
    assert submitted["agent_run_id"] == "run-resume-1"
    bind_continuation_run.assert_awaited_once()
    assert bind_continuation_run.await_args.kwargs["agent_run_id"] == "run-resume-1"
    assert stages == [("run-resume-1", "draft_optimization")]
    assert succeeded[0][1]["generation_session_id"] == "generation-1"
    assert observations == [
        {
            "name": "resume-generation",
            "agent_type": "resume_generation",
            "user_id": "owner-1",
            "session_id": "generation-1",
            "run_id": "run-resume-1",
            "input_payload": {"answer_count": 1},
        }
    ]


@pytest.mark.asyncio
async def test_repeated_identical_answers_reuse_the_existing_generation_run(monkeypatch):
    """A retried continuation cannot call the generation Graph a second time."""
    from contextlib import asynccontextmanager

    from ai.workflows.resume import generation

    run = SimpleNamespace(id="run-resume-1", status="running")
    create_calls = 0
    submit = AsyncMock(return_value={"resume_id": 7, "title": "新简历", "content": "# 新简历"})

    async def create_inline_or_get(_self, **_kwargs):
        nonlocal create_calls
        create_calls += 1
        return run, create_calls == 1

    async def no_cancel(_self, _run_id):
        return False

    @asynccontextmanager
    async def observe(**_kwargs):
        yield SimpleNamespace(set_output=lambda _output: None)

    session = SimpleNamespace(
        session_id="generation-1",
        status="awaiting_input",
        questions=["q"],
        agent_run_id=None,
        generated_resume_id=None,
        resume_content="# 简历",
        job_description="AI Agent",
    )
    monkeypatch.setattr(generation.AgentRunService, "create_inline_or_get", create_inline_or_get)
    monkeypatch.setattr(generation.AgentRunService, "is_cancel_requested", no_cancel)
    monkeypatch.setattr(generation.AgentRunService, "succeed", AsyncMock())
    monkeypatch.setattr(generation.AgentRunService, "fail", AsyncMock())
    monkeypatch.setattr(generation.AgentRunService, "mark_stage", AsyncMock())
    monkeypatch.setattr(generation.AgentRunService, "mark_cancelled", AsyncMock())
    monkeypatch.setattr(generation.session_store, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(
        generation.session_store,
        "claim_continuation",
        AsyncMock(return_value=SimpleNamespace(status="draft_generation", generated_resume_id=None)),
    )
    monkeypatch.setattr(generation.session_store, "bind_continuation_run", AsyncMock())
    monkeypatch.setattr(generation.session_store, "update", AsyncMock())
    monkeypatch.setattr(generation, "submit_user_answers", submit)
    monkeypatch.setattr(generation, "agent_observation", observe)

    request = SimpleNamespace(
        session_id="generation-1",
        answers={"q": "same answer"},
        api_config=SimpleNamespace(model_dump=lambda: {"fast": {"model": "mock"}}),
    )
    use_cases = generation.ResumeGenerationUseCases()

    first = await use_cases.submit_generation_answers(request=request, user_id="owner-1")
    assert first.resume_id == 7

    with pytest.raises(generation.ResumeGenerationConflict) as exc_info:
        await use_cases.submit_generation_answers(request=request, user_id="owner-1")

    assert exc_info.value.message == "同一简历生成请求正在执行，请等待当前生成完成"
    assert create_calls == 2
    assert submit.await_count == 1


@pytest.mark.asyncio
async def test_cancelled_generation_converges_session_without_running_graph(monkeypatch):
    """Cancellation before execution maps both lifecycle owners to cancelled."""
    from ai.workflows.resume import generation

    async def create_inline_or_get(_self, **_kwargs):
        return SimpleNamespace(id="run-resume-1", status="running"), True

    async def cancelled(_self, _run_id):
        return True

    updates = AsyncMock()
    session = SimpleNamespace(
        session_id="generation-1",
        status="awaiting_input",
        questions=["q"],
        agent_run_id=None,
        generated_resume_id=None,
        resume_content="# 简历",
        job_description="AI Agent",
    )
    monkeypatch.setattr(generation.AgentRunService, "create_inline_or_get", create_inline_or_get)
    monkeypatch.setattr(generation.AgentRunService, "is_cancel_requested", cancelled)
    monkeypatch.setattr(generation.AgentRunService, "mark_cancelled", AsyncMock())
    monkeypatch.setattr(generation.AgentRunService, "fail", AsyncMock())
    monkeypatch.setattr(generation.session_store, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(
        generation.session_store,
        "claim_continuation",
        AsyncMock(return_value=SimpleNamespace(status="draft_generation", generated_resume_id=None)),
    )
    monkeypatch.setattr(generation.session_store, "bind_continuation_run", AsyncMock())
    monkeypatch.setattr(generation.session_store, "update", updates)
    submit = AsyncMock()
    monkeypatch.setattr(generation, "submit_user_answers", submit)

    with pytest.raises(generation.ResumeGenerationConflict) as exc_info:
        await generation.ResumeGenerationUseCases().submit_generation_answers(
            request=SimpleNamespace(
                session_id="generation-1",
                answers={"q": "answer"},
                api_config=SimpleNamespace(model_dump=lambda: {"fast": {"model": "mock"}}),
            ),
            user_id="owner-1",
        )

    assert exc_info.value.message == "任务已取消"
    assert submit.await_count == 0
    assert any(call.kwargs["status"] == "cancelled" for call in updates.await_args_list)
