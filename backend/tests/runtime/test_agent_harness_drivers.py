"""Agent Harness driver 生命周期和隔离策略测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ai.runtime.harness.catalog import AgentCatalog
from ai.runtime.harness.contracts import DeferredExecutionResult, HarnessEvent
from ai.runtime.harness.drivers import EvaluationDriver, InlineDriver, QueuedDriver
from ai.runtime.harness.events import BestEffortEventSink
from ai.runtime.harness.registry import CallableExecutionAdapter, ExecutionAdapterRegistry
from app.domain.agent_definitions import AgentDefinition


def _catalog(runner, *, evaluation_enabled: bool = True) -> AgentCatalog:
    definition = AgentDefinition(
        name="demo_agent",
        version="7",
        task_type="demo_task",
        title="Demo",
        steps=(("queued", "等待"), ("running", "执行")),
        execution_modes=("queued", "inline"),
        adapter_key="demo_adapter",
        migration_state="harness",
        evaluation_enabled=evaluation_enabled,
        side_effect_policy="local_write",
        graph_reference_mode="diagnostic",
        run_gate_policy="none",
    )
    registry = ExecutionAdapterRegistry()
    registry.register(CallableExecutionAdapter(key="demo_adapter", runner=runner))
    catalog = AgentCatalog(
        definitions=(definition,),
        adapters=registry,
        prompt_refs=frozenset(),
        graph_names=frozenset(),
    )
    catalog.validate()
    return catalog


@pytest.mark.asyncio
async def test_inline_driver_builds_bounded_production_context() -> None:
    seen = {}

    async def runner(payload, context):
        seen.update({"payload": payload, "context": context})
        return {"ok": True}

    result = await InlineDriver(_catalog(runner)).run(
        task_type="demo_task",
        payload={"private": "not-copied-to-context"},
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
    )

    assert result == {"ok": True}
    context = seen["context"]
    assert context.environment == "production"
    assert context.execution_mode == "inline"
    assert context.owner_scope == "user:user-1"
    assert context.external_tools_enabled is False
    assert not hasattr(context, "payload")
    assert "not-copied-to-context" not in repr(context)


@pytest.mark.asyncio
async def test_evaluation_driver_uses_isolated_namespaces_and_blocks_external_tools() -> None:
    seen = {}

    async def runner(payload, context):
        seen["context"] = context
        return {"actual": payload["input"]}

    result = await EvaluationDriver(_catalog(runner)).run(
        task_type="demo_task",
        payload={"input": "real-output"},
        run_id="eval-run-1",
        user_id="eval-user:eval-run-1",
        session_id="eval-session:eval-run-1",
        memory_namespace="eval:memory:eval-run-1",
        artifact_namespace="eval:artifact:eval-run-1",
    )

    assert result == {"actual": "real-output"}
    context = seen["context"]
    assert context.environment == "evaluation"
    assert context.execution_mode == "evaluation"
    assert context.external_tools_enabled is False
    assert context.memory_namespace.startswith("eval:")
    assert context.artifact_namespace.startswith("eval:")


@pytest.mark.asyncio
async def test_best_effort_event_sink_preserves_result_when_one_sink_fails() -> None:
    received = []

    async def failing_sink(_event):
        raise RuntimeError("telemetry unavailable")

    async def recording_sink(event):
        received.append(event)

    async def runner(_payload, context):
        await context.emit(HarnessEvent(event_type="adapter.completed", stage="running"))
        return {"ok": True}

    sink = BestEffortEventSink((failing_sink, recording_sink))
    result = await InlineDriver(_catalog(runner)).run(
        task_type="demo_task",
        payload={},
        user_id="user-1",
        event_sink=sink,
    )

    assert result == {"ok": True}
    assert [event.event_type for event in received] == ["adapter.completed"]
    assert sink.error_types == ("RuntimeError",)


class _FakeService:
    def __init__(self, *, result_kind: str = "normal", cancel_requested: bool = False):
        self.result_kind = result_kind
        self.cancel_requested = cancel_requested
        self.calls = []
        self.run = SimpleNamespace(
            id="run-1",
            task_type="demo_task",
            user_id="user-1",
            session_id="session-1",
        )

    async def get_task_type_for_worker(self, run_id):
        self.calls.append(("task_type", run_id))
        return "demo_task"

    async def claim(self, run_id):
        self.calls.append(("claim", run_id))
        return self.run, {"value": 3}

    async def mark_stage(self, run_id, stage):
        self.calls.append(("stage", run_id, stage))

    async def touch(self, run_id):
        self.calls.append(("touch", run_id))

    async def is_cancel_requested(self, run_id):
        self.calls.append(("cancel_check", run_id))
        return self.cancel_requested

    async def succeed(self, run_id, result):
        self.calls.append(("succeed", run_id, result))

    async def succeed_with_result_writer(self, run_id, writer):
        self.calls.append(("succeed_deferred", run_id, await writer(object())))

    async def mark_cancelled(self, run_id):
        self.calls.append(("cancelled", run_id))

    async def requeue(self, run_id):
        self.calls.append(("requeue", run_id))

    async def fail(self, run_id, message):
        self.calls.append(("fail", run_id, message))


@pytest.mark.asyncio
@pytest.mark.parametrize("deferred", [False, True])
async def test_queued_driver_claims_once_and_preserves_result_contract(deferred: bool) -> None:
    service = _FakeService()

    async def runner(payload, context):
        assert payload == {"value": 3, "_agent_run_id": "run-1"}
        await context.mark_progress("running")
        if deferred:
            async def persist(_session):
                return {"persisted": True}

            return DeferredExecutionResult(persist=persist)
        return {"value": 3}

    await QueuedDriver(
        catalog=_catalog(runner),
        service=service,
        heartbeat_seconds=3600,
        cancel_poll_seconds=3600,
    ).run("run-1")

    assert [call for call in service.calls if call[0] == "claim"] == [("claim", "run-1")]
    expected = "succeed_deferred" if deferred else "succeed"
    assert any(call[0] == expected for call in service.calls)
    assert not any(call[0] == "fail" for call in service.calls)


@pytest.mark.asyncio
async def test_queued_driver_sanitizes_failure() -> None:
    service = _FakeService()

    async def runner(_payload, _context):
        raise RuntimeError("api_key=sk-12345678901234567890")

    await QueuedDriver(
        catalog=_catalog(runner),
        service=service,
        heartbeat_seconds=3600,
        cancel_poll_seconds=3600,
    ).run("run-1")

    failure = next(call for call in service.calls if call[0] == "fail")
    assert "sk-" not in failure[2]
    assert "REDACTED" in failure[2]


@pytest.mark.asyncio
async def test_queued_driver_cooperatively_cancels_running_adapter() -> None:
    service = _FakeService(cancel_requested=True)
    started = asyncio.Event()

    async def runner(_payload, _context):
        started.set()
        await asyncio.Future()

    driver = QueuedDriver(
        catalog=_catalog(runner),
        service=service,
        heartbeat_seconds=3600,
        cancel_poll_seconds=0,
    )
    await driver.run("run-1")

    assert started.is_set()
    assert ("cancelled", "run-1") in service.calls
    assert not any(call[0] in {"fail", "requeue"} for call in service.calls)


@pytest.mark.asyncio
async def test_inline_agent_run_owner_persists_sanitized_failure(monkeypatch) -> None:
    from ai.workflows import agent_runs as workflow

    failed = []
    run = SimpleNamespace(id="inline-run-1", status="running")

    class FakeLease:
        async def release(self):
            return None

    class FakeGate:
        async def acquire(self):
            return FakeLease()

    class FakeService:
        async def create_inline_or_get(self, **_kwargs):
            return run, True

        async def fail(self, run_id, message):
            failed.append((run_id, message))

    async def execute(*_args, **_kwargs):
        raise RuntimeError("api_key=sk-12345678901234567890")

    monkeypatch.setattr(workflow, "task_queue_enabled", lambda: False)
    monkeypatch.setattr(workflow, "get_run_gate", lambda: FakeGate())
    monkeypatch.setattr(workflow, "execute_registered_task", execute)
    use_cases = workflow.AgentRunUseCases()
    use_cases._service = FakeService()

    with pytest.raises(RuntimeError):
        await use_cases.create_queued_run(
            task_type="resume_workspace",
            payload={"resume_content": "private"},
            user_id="user-1",
            idempotency_key="inline-failure",
        )

    assert failed[0][0] == "inline-run-1"
    assert "sk-" not in failed[0][1]
    assert "REDACTED" in failed[0][1]
