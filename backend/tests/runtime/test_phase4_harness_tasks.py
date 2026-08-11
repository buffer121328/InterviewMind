"""Phase 04 非交互任务 Harness 迁移契约。"""

from __future__ import annotations

import pytest

from ai.runtime.harness.catalog import AgentCatalog, CatalogValidationError
from ai.runtime.harness.contracts import DeferredExecutionResult, ExecutionContext
from ai.runtime.harness.registry import CallableExecutionAdapter, ExecutionAdapterRegistry
from ai.workflows.agent_tasks.adapters import (
    AbilityProfileExecutionAdapter,
    EvaluationSuiteExecutionAdapter,
    InterviewReportExecutionAdapter,
    JobAssetsExecutionAdapter,
    JobRecommendationCaptureExecutionAdapter,
    ProductionTaskExecutionAdapter,
    ResumeOptimizeExecutionAdapter,
    ResumeWorkspaceExecutionAdapter,
)
from ai.workflows.agent_tasks.registry import get_production_adapter_registry
from app.domain.agent_definitions import AgentDefinition, get_agent_definitions


def _definition(**overrides) -> AgentDefinition:
    values = {
        "name": "demo_agent",
        "version": "1",
        "task_type": "demo_task",
        "title": "Demo",
        "steps": (("queued", "等待"), ("running", "执行")),
        "execution_modes": ("queued", "inline"),
        "adapter_key": "demo_task",
        "migration_state": "harness",
        "evaluation_enabled": False,
        "side_effect_policy": "local_write",
        "graph_name": None,
        "graph_reference_mode": "diagnostic",
        "prompt_name": None,
        "prompt_version": None,
        "run_gate_policy": "global",
    }
    values.update(overrides)
    return AgentDefinition(**values)


async def _runner(_payload, _context):
    return {"success": True}


def _registry() -> ExecutionAdapterRegistry:
    registry = ExecutionAdapterRegistry()
    registry.register(CallableExecutionAdapter(key="demo_task", runner=_runner))
    return registry


def _context(*, progress=None) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_type="resume_optimize",
        agent_name="resume_optimizer",
        agent_version="1",
        user_id="user-1",
        session_id="session-1",
        owner_scope="user:user-1",
        execution_mode="queued",
        environment="production",
        side_effect_policy="local_write",
        progress=progress,
    )


def test_phase4_registry_registers_each_migrated_task_explicitly() -> None:
    expected = {
        "resume_optimize": ResumeOptimizeExecutionAdapter,
        "resume_workspace": ResumeWorkspaceExecutionAdapter,
        "interview_report": InterviewReportExecutionAdapter,
        "ability_profile": AbilityProfileExecutionAdapter,
        "job_recommendation_capture": JobRecommendationCaptureExecutionAdapter,
        "job_assets": JobAssetsExecutionAdapter,
        "evaluation_suite": EvaluationSuiteExecutionAdapter,
    }

    registry = get_production_adapter_registry()

    assert set(registry.keys()) == {*expected, "interview_start"}
    for task_type, adapter_type in expected.items():
        adapter = registry.get(task_type)
        assert isinstance(adapter.adapter, ProductionTaskExecutionAdapter)
        assert isinstance(adapter.adapter, adapter_type)
        assert adapter.key == task_type


def test_catalog_rejects_incompatible_worker_limit_policy() -> None:
    registry = _registry()

    with pytest.raises(CatalogValidationError, match="worker_limit.*queued"):
        AgentCatalog(
            definitions=(_definition(execution_modes=("inline",), run_gate_policy="worker_limit"),),
            adapters=registry,
            prompt_refs=frozenset(),
            graph_names=frozenset(),
        ).validate()


def test_catalog_rejects_external_effect_evaluation_policy() -> None:
    registry = _registry()

    with pytest.raises(CatalogValidationError, match="external_effect.*evaluation"):
        AgentCatalog(
            definitions=(_definition(evaluation_enabled=True, side_effect_policy="external_effect"),),
            adapters=registry,
            prompt_refs=frozenset(),
            graph_names=frozenset(),
        ).validate()


def test_phase4_definitions_keep_stream_and_session_outside_harness() -> None:
    definitions = {item.task_type: item for item in get_agent_definitions()}

    assert definitions["interview_turn"].migration_state == "legacy"
    assert definitions["voice_interview_turn"].migration_state == "legacy"
    assert definitions["resume_generation"].migration_state == "legacy"
    assert definitions["interview_start"].migration_state == "harness"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type",
    (ResumeOptimizeExecutionAdapter, ResumeWorkspaceExecutionAdapter),
)
async def test_resume_adapters_preserve_owner_progress_and_deferred_result(adapter_type) -> None:
    stages: list[str] = []
    captured = {}

    async def progress(stage: str) -> None:
        stages.append(stage)

    async def persist(_session):
        return {"success": True}

    deferred = DeferredExecutionResult(persist=persist)

    async def runner(payload, user_id, progress):
        captured.update({"payload": payload, "user_id": user_id})
        await progress("saving_result")
        return deferred

    adapter = adapter_type(executor=runner)
    result = await adapter.run(
        {"resume_content": "redacted", "_agent_run_id": "run-1"},
        _context(progress=progress),
    )

    assert result is deferred
    assert captured["user_id"] == "user-1"
    assert captured["payload"]["_agent_run_id"] == "run-1"
    assert stages == ["saving_result"]


@pytest.mark.asyncio
async def test_job_assets_inline_run_does_not_acquire_global_gate(monkeypatch) -> None:
    from ai.workflows import agent_runs as workflow

    calls: list[str] = []
    run = type("Run", (), {"id": "run-1", "status": "running"})()

    class FailingGate:
        async def acquire(self):
            calls.append("acquire")
            raise AssertionError("job_assets must bypass the global gate")

    class Service:
        async def create_inline_or_get(self, **_kwargs):
            return run, True

        async def succeed(self, _run_id, _result):
            calls.append("succeed")

        async def fail(self, _run_id, _message):
            raise AssertionError("success path must not fail")

        async def get(self, _run_id, _user_id):
            return run

    async def execute(*_args, **_kwargs):
        return {"success": True}

    monkeypatch.setattr(workflow, "task_queue_enabled", lambda: False)
    monkeypatch.setattr(workflow, "get_run_gate", lambda: FailingGate())
    monkeypatch.setattr(workflow, "execute_registered_task", execute)
    monkeypatch.setattr(workflow, "serialize_run", lambda _run: {"status": "succeeded"})
    use_cases = workflow.AgentRunUseCases()
    use_cases._service = Service()

    await use_cases.create_queued_run(
        task_type="job_assets",
        payload={"job_id": 1},
        user_id="user-1",
        idempotency_key="job-assets-inline",
    )

    assert calls == ["succeed"]
