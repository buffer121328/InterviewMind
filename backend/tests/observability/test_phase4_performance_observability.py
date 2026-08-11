"""Phase 4 contracts for local model metrics, aggregation, and integrity gates."""

from types import SimpleNamespace

import pytest

from ai.runtime.agent_runs.performance import summarize_model_metric_events
from observability.observation import AgentObservation, _persist_agent_observation


def test_performance_summary_distinguishes_logical_and_physical_requests() -> None:
    """Retries and fallback increase physical requests without inflating logical calls."""
    summary = summarize_model_metric_events([
        {"event_type": "llm.request.started", "attempt": 1, "fallback_index": 0, "authoritative_source_truncated": False, "overflow_strategy": "lossless_segments_or_derived_ir"},
        {"event_type": "llm.request.failed", "attempt": 1, "fallback_index": 0, "failure_type": "timeout", "timeout_scope": "model", "model_duration_ms": 100},
        {"event_type": "llm.request.started", "attempt": 2, "fallback_index": 0},
        {"event_type": "llm.request.failed", "attempt": 2, "fallback_index": 0, "model_duration_ms": 200},
        {"event_type": "llm.request.started", "attempt": 1, "fallback_index": 1},
        {"event_type": "llm.request.completed", "attempt": 1, "fallback_index": 1, "model_duration_ms": 300, "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 4},
    ], run_statuses=["succeeded", "failed"])

    assert summary["logical_call_count"] == 1
    assert summary["physical_request_count"] == 3
    assert summary["call_amplification"] == 3
    assert summary["p50_model_duration_ms"] == 200
    assert summary["p95_model_duration_ms"] == 300
    assert summary["retry_rate"] == pytest.approx(1 / 3)
    assert summary["fallback_rate"] == pytest.approx(1 / 3)
    assert summary["timeout_rate"] == pytest.approx(1 / 3)
    assert summary["authoritative_truncation_rate"] == 0
    assert summary["overflow_strategy_counts"] == {"lossless_segments_or_derived_ir": 1}


def test_performance_summary_preserves_no_data_integrity_semantics() -> None:
    """No authoritative samples must not be reported as a measured zero truncation rate."""
    summary = summarize_model_metric_events([], run_statuses=[])
    assert summary["authoritative_context_sample_count"] == 0
    assert summary["authoritative_truncation_rate"] is None
    assert summary["run_success_rate"] is None


@pytest.mark.asyncio
async def test_local_metrics_persist_when_langfuse_is_disabled(monkeypatch) -> None:
    """Local performance metrics do not depend on an external Langfuse client."""
    calls: list[dict] = []

    class Service:
        async def record_observation(self, run_id: str, **kwargs) -> None:
            calls.append({"run_id": run_id, **kwargs})

    monkeypatch.setattr("observability._get_agent_run_service", lambda: Service())
    observation = AgentObservation(
        enabled=False,
        input_payload={},
        trace_id="local-observation",
        run_id="run-1",
        model_events=[{"event_type": "llm.request.completed", "input_tokens": 1}],
    )

    await _persist_agent_observation(observation)

    assert calls == [{
        "run_id": "run-1",
        "observation_id": "local-observation",
        "trace_id": None,
        "model_events": [{"event_type": "llm.request.completed", "input_tokens": 1}],
    }]


def test_evaluation_blocks_authoritative_context_truncation() -> None:
    """The release metric is a zero-tolerance hard gate, not a display-only rate."""
    from evaluation.metrics import metric_definition
    from evaluation.schemas import AgentEvalRecord, EvalRunEvent
    from evaluation.runtime_metrics import build_runtime_metric_scores

    record = AgentEvalRecord(
        case_id="case-1", dataset_version="dataset-1", agent_name="agent",
        agent_version="1", model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner", evaluation_namespace="eval:phase4",
        input_summary={}, final_output={}, final_status="succeeded", latency_ms=10,
        events=(
            EvalRunEvent(sequence=1, stage="compose", event_type="llm.request.started", status="completed", payload_summary={"attempt": 1, "fallback_index": 0, "authoritative_source_truncated": True, "overflow_strategy": "head"}),
            EvalRunEvent(sequence=2, stage="compose", event_type="llm.request.completed", status="completed", payload_summary={"duration_ms": 10}),
        ),
    )
    scores = {score.metric_name: score for score in build_runtime_metric_scores(record)}
    definition = metric_definition("context.authoritative_truncation_rate")

    assert definition is not None and definition.hard_gate is True
    assert scores["context.authoritative_truncation_rate"].status.value == "failed"
    assert scores["model.call_amplification"].value == 1


def test_fixed_dataset_baseline_comparison_rejects_incomparable_runs() -> None:
    """Dataset or Agent mismatches are explicit and never reported as improvements."""
    from ai.workflows.agent_tasks.evaluation_suite import build_baseline_comparison

    comparison = build_baseline_comparison(
        current_summary={"metrics": {"quality": 1.0}, "complete_success_rate": 1.0, "p95_latency_ms": 10, "token_total": 10},
        current_dataset_version="v2", current_agent_name="planner",
        current_model_config_hash="sha256:new",
        baseline_snapshot={"run_id": "base", "dataset_version": "v1", "agent_name": "planner", "model_config_hash": "sha256:old", "summary": {"metrics": {"quality": 0.5}}},
    )

    assert comparison["comparable"] is False
    assert comparison["incomparable_reasons"] == ["dataset_version_mismatch"]
    assert "metric_deltas" not in comparison


def test_fixed_dataset_baseline_comparison_reports_real_deltas() -> None:
    """Comparable fixed-dataset runs expose measured deltas and both config hashes."""
    from ai.workflows.agent_tasks.evaluation_suite import build_baseline_comparison

    comparison = build_baseline_comparison(
        current_summary={"metrics": {"model.timeout_rate": 0.0}, "complete_success_rate": 1.0, "p95_latency_ms": 80, "token_total": 80},
        current_dataset_version="phase4-contract-v1", current_agent_name="planner",
        current_model_config_hash="sha256:candidate",
        baseline_snapshot={"run_id": "baseline", "dataset_version": "phase4-contract-v1", "agent_name": "planner", "model_config_hash": "sha256:baseline", "summary": {"metrics": {"model.timeout_rate": 0.5}, "complete_success_rate": 0.5, "p95_latency_ms": 100, "token_total": 100}},
    )

    assert comparison["comparable"] is True
    assert comparison["metric_deltas"] == {"model.timeout_rate": -0.5}
    assert comparison["p95_latency_ms_delta"] == -20
    assert comparison["token_total_delta_percent"] == pytest.approx(-0.2)
    assert comparison["current_model_config_hash"] == "sha256:candidate"
