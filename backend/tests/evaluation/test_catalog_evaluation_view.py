"""Catalog-derived production evaluation view contracts."""

from typing import Any

import pytest
from ai.runtime.harness.catalog import AgentCatalog
from ai.runtime.harness.registry import (
    CallableExecutionAdapter,
    ExecutionAdapterRegistry,
)
from app.domain.agent_definitions import AgentDefinition
from evaluation.extractors.runtime import EvaluationTraceCollector
from evaluation.runners import (
    AgentAdapterRegistry,
    AgentEvalRunner,
    CatalogEvaluationAdapter,
    CatalogEvaluationView,
    EvaluationCaseAdapterSpec,
    EvaluationCaseSpec,
    EvaluationConfigurationError,
    EvaluationExecutionContext,
)


async def _production_marker(_payload: dict[str, Any], _context) -> dict[str, bool]:
    return {"production": True}


def _catalog() -> AgentCatalog:
    definition = AgentDefinition(
        name="demo_agent",
        version="7",
        task_type="demo_task",
        title="Demo",
        steps=(("queued", "等待"), ("running", "执行")),
        prompt_name="demo.prompt",
        prompt_version="4",
        execution_modes=("inline",),
        adapter_key="demo_adapter",
        evaluation_enabled=True,
        side_effect_policy="read_only",
        graph_reference_mode="diagnostic",
        run_gate_policy="none",
    )
    adapters = ExecutionAdapterRegistry()
    adapters.register(
        CallableExecutionAdapter(key="demo_adapter", runner=_production_marker)
    )
    return AgentCatalog(
        definitions=(definition,),
        adapters=adapters,
        prompt_refs=frozenset({("demo.prompt", "4")}),
        graph_names=frozenset(),
    )


@pytest.mark.asyncio
async def test_catalog_view_records_authoritative_identity_and_actual_output(monkeypatch):
    monkeypatch.setattr("observability.get_langfuse_client", lambda: None)
    seen: dict[str, Any] = {}

    async def case_runner(payload, context, trace, production_adapter):
        seen.update(
            {
                "environment": context.environment,
                "namespace": context.evaluation_session_id,
                "adapter_key": production_adapter.key,
            }
        )
        trace.record_event(
            stage="running_cases",
            event_type="model.request.completed",
            status="completed",
        )
        return {"actual": payload["value"]}

    view = CatalogEvaluationView(
        catalog=_catalog(),
        case_adapters={
            "demo": EvaluationCaseAdapterSpec(
                task_type="demo_task",
                runner=case_runner,
                required_trace_categories=("runtime", "model"),
            )
        },
    )
    entry = view.resolve("demo")
    assert entry.task_type == "demo_task"
    assert entry.production_adapter_key == "demo_adapter"
    assert entry.definition.version == "7"
    assert entry.definition.prompt_name == "demo.prompt"
    assert entry.definition.prompt_version == "4"

    eval_registry = AgentAdapterRegistry()
    eval_registry.register(CatalogEvaluationAdapter(capability_name="demo", view=view))
    result = await AgentEvalRunner(adapter_registry=eval_registry).run_case(
        case=EvaluationCaseSpec(
            case_id="case-1",
            dataset_version="dataset-v1",
            input_payload={"value": "actual"},
            expected_output={"actual": "expected"},
        ),
        agent_name="demo",
        model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner",
        run_id="outer-run:case-1",
    )

    assert result.record.final_output == {"actual": "actual"}
    assert result.record.agent_version == "7"
    assert result.record.prompt_name == "demo.prompt"
    assert result.record.prompt_version == "4"
    assert seen == {
        "environment": "evaluation",
        "namespace": "eval-session:outer-run:case-1",
        "adapter_key": "demo_adapter",
    }
    assert result.record.observability.trace_completeness.missing_categories == ()


@pytest.mark.fast
def test_catalog_view_fails_closed_without_explicit_case_adapter():
    view = CatalogEvaluationView(catalog=_catalog(), case_adapters={})

    with pytest.raises(EvaluationConfigurationError, match="case adapter"):
        view.resolve("demo")


@pytest.mark.fast
def test_catalog_view_fails_closed_when_catalog_identity_drifts():
    class DriftedCatalog:
        def resolve(self, *_args, **_kwargs):
            raise ValueError("prompt version drift")

    view = CatalogEvaluationView(
        catalog=DriftedCatalog(),
        case_adapters={
            "demo": EvaluationCaseAdapterSpec(
                task_type="demo_task",
                runner=lambda *_args: None,
            )
        },
    )

    with pytest.raises(EvaluationConfigurationError, match="not eligible"):
        view.resolve("demo")


@pytest.mark.fast
def test_trace_completeness_reports_bounded_missing_categories_and_sink_failure():
    trace = EvaluationTraceCollector(evaluation_namespace="eval:run-1")
    trace.record_event(stage="starting", event_type="case.started")
    trace.record_event(stage="running", event_type="model.request.completed")
    trace.mark_runtime_sink_error("RuntimeSinkError")

    completeness = trace.trace_completeness(
        agent_version="7",
        prompt_name="demo.prompt",
        prompt_version="4",
        model_config_hash="sha256:model",
        agent_run_id="case-run-1",
        tracing_disabled=True,
        required_categories=(
            "runtime",
            "model",
            "tool",
            "retrieval",
            "memory",
            "external_io",
        ),
    )

    assert completeness.complete is False
    assert completeness.category_counts["runtime"] == 2
    assert completeness.category_counts["model"] == 1
    assert completeness.missing_categories == ("tool", "retrieval", "memory", "external_io")
    assert "runtime_sink" in completeness.missing


@pytest.mark.asyncio
async def test_compatibility_registry_keeps_names_but_rejects_parallel_fallbacks():
    from evaluation.runners import build_production_agent_registry

    registry = build_production_agent_registry()
    planner = registry.get("interview_planner")
    assert planner.version == "1"
    assert planner.prompt_name == "interview.planner"
    assert planner.prompt_version == "3"
    assert planner.production_adapter_key == "interview_start"

    resume_optimizer = registry.get("resume_optimizer")
    assert resume_optimizer.prompt_name == "resume.match_analyst"
    assert resume_optimizer.prompt_version == "1"
    assert resume_optimizer.production_adapter_key == "resume_optimize"
