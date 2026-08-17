"""`interview_start` queued、inline 与 evaluation 纵向样板契约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.runtime.harness.contracts import ExecutionContext
from ai.workflows.agent_runs.adapters import InterviewStartExecutionAdapter
from app.domain.agent_definitions import get_agent_definition


def _context(*, environment: str, execution_mode: str) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_type="interview_start",
        agent_name="interview_starter",
        agent_version="1",
        user_id="eval-user:run-1" if environment == "evaluation" else "user-1",
        session_id="eval-session:run-1" if environment == "evaluation" else "session-1",
        owner_scope="eval:run-1" if environment == "evaluation" else "user:user-1",
        execution_mode=execution_mode,
        environment=environment,
        memory_namespace="eval:memory:run-1" if environment == "evaluation" else None,
        artifact_namespace="eval:artifact:run-1" if environment == "evaluation" else None,
        external_tools_enabled=False,
        side_effect_policy="local_write",
    )


@pytest.mark.asyncio
async def test_interview_start_adapter_keeps_production_executor_result() -> None:
    calls = []

    async def production_runner(payload, user_id, progress):
        calls.append((payload, user_id, progress))
        return {"success": True, "first_question": "请介绍项目"}

    async def evaluation_runner(_payload, _context):
        raise AssertionError("production context must not use evaluation runner")

    adapter = InterviewStartExecutionAdapter(
        production_runner=production_runner,
        evaluation_runner=evaluation_runner,
    )
    result = await adapter.run(
        {"thread_id": "session-1", "mode": "mock"},
        _context(environment="production", execution_mode="inline"),
    )

    assert result == {"success": True, "first_question": "请介绍项目"}
    assert calls[0][1] == "user-1"


@pytest.mark.asyncio
async def test_interview_start_adapter_evaluation_is_non_persistent_and_isolated() -> None:
    seen = {}

    async def production_runner(_payload, _user_id, _progress):
        raise AssertionError("evaluation context must not create a production session")

    async def evaluation_runner(payload, context):
        seen.update({"payload": payload, "context": context})
        return [{"content": "评测首题"}]

    adapter = InterviewStartExecutionAdapter(
        production_runner=production_runner,
        evaluation_runner=evaluation_runner,
    )
    result = await adapter.run(
        {"resume": "脱敏简历", "expected_output": "不得作为 actual"},
        _context(environment="evaluation", execution_mode="evaluation"),
    )

    assert result == [{"content": "评测首题"}]
    assert seen["context"].user_id.startswith("eval-user:")
    assert seen["context"].session_id.startswith("eval-session:")
    assert seen["context"].external_tools_enabled is False


@pytest.mark.asyncio
async def test_default_interview_start_evaluation_runner_forces_save_to_db_false(
    monkeypatch,
) -> None:
    captured = {}

    async def generate_interview_plan(**kwargs):
        captured.update(kwargs)
        return [{"content": "真实 adapter 输出"}]

    monkeypatch.setattr(
        "ai.agents.interview.planning.planner.generate_interview_plan",
        generate_interview_plan,
    )
    result = await InterviewStartExecutionAdapter().run(
        {"resume": "脱敏简历", "generate_hints": True},
        _context(environment="evaluation", execution_mode="evaluation"),
    )

    assert result == [{"content": "真实 adapter 输出"}]
    assert captured["save_to_db"] is False
    assert captured["session_id"] == "eval-session:run-1"
    assert captured["owner_id"] == "eval-user:run-1"
    assert captured["cache_scope"] == "eval-session:run-1"


@pytest.mark.fast
def test_eval_interview_planner_view_uses_authoritative_versions() -> None:
    from evaluation.runners.production import build_production_agent_registry

    definition = get_agent_definition("interview_start")
    adapter = build_production_agent_registry().get("interview_planner")

    assert adapter.version == definition.version
    assert adapter.prompt_name == "interview.planner"
    assert adapter.prompt_version == "3"


@pytest.mark.asyncio
async def test_queue_disabled_interview_start_uses_inline_harness_and_keeps_response(monkeypatch) -> None:
    from ai.workflows.agent_runs import use_cases as workflow

    calls = []

    class FakeLease:
        async def release(self):
            calls.append("released")

    class FakeGate:
        async def acquire(self):
            return FakeLease()

    async def get_session(*_args, **_kwargs):
        return None

    async def execute(_self, task_type, payload, user_id, progress):
        calls.append((task_type, payload, user_id, progress))
        return {"success": True, "first_question": "首题"}

    use_cases = workflow.AgentRunUseCases()
    use_cases._session_repo = SimpleNamespace(get_session=get_session)
    monkeypatch.setattr(workflow, "task_queue_enabled", lambda: False)
    monkeypatch.setattr(workflow, "get_run_gate", lambda: FakeGate())
    monkeypatch.setattr(workflow.AgentRunUseCases, "_run_inline_task", execute)

    response = await use_cases.create_interview_start(
        payload={"thread_id": "session-1", "mode": "mock"},
        user_id="user-1",
        idempotency_key="same-key",
    )

    assert response.body == {
        "task_type": "interview_start",
        "status": "succeeded",
        "result": {"success": True, "first_question": "首题"},
    }
    assert calls[0][0] == "interview_start"
    assert calls[-1] == "released"


@pytest.mark.fast
def test_interview_start_definition_keeps_prompt_v3_for_run_created_event() -> None:
    definition = get_agent_definition("interview_start")

    assert definition.name == "interview_starter"
    assert definition.version == "1"
    assert definition.prompt_name == "interview.planner"
    assert definition.prompt_version == "3"
