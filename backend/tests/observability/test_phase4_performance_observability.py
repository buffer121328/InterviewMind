"""Phase 4 contracts for local model metrics, aggregation, and integrity gates."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from ai.runtime.agent_runs.performance import (
    build_model_performance_daily_trend,
    build_performance_model_options,
    build_performance_daily_trend,
    summarize_model_metric_events,
)
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
    assert summary["total_tokens"] == 15
    assert summary["authoritative_truncation_rate"] == 0
    assert summary["overflow_strategy_counts"] == {"lossless_segments_or_derived_ir": 1}


def test_performance_summary_ignores_unreported_cache_state() -> None:
    """Provider events without cache_hit are not treated as cache misses."""
    summary = summarize_model_metric_events([
        {"event_type": "llm.request.completed", "cache_hit": True, "input_tokens": 4, "output_tokens": 2},
        {"event_type": "llm.request.completed", "cache_hit": False, "input_tokens": 5, "output_tokens": 3},
        {"event_type": "llm.request.completed", "input_tokens": 6, "output_tokens": 4},
    ])

    assert summary["cache_hit_rate"] == pytest.approx(0.5)
    assert summary["total_tokens"] == 24

    no_cache_summary = summarize_model_metric_events([
        {"event_type": "llm.request.completed", "input_tokens": 1, "output_tokens": 1},
    ])
    assert no_cache_summary["cache_hit_rate"] is None


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
    from ai.workflows.agent_runs.tasks.evaluation.evaluation_suite import build_baseline_comparison

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
    from ai.workflows.agent_runs.tasks.evaluation.evaluation_suite import build_baseline_comparison

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


def test_performance_daily_trend_uses_china_standard_time_and_safe_counters() -> None:
    """The overview buckets UTC metrics into the product calendar without raw payload output."""
    events = [
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 15, 16, 43, 41),
            payload={"attempt": 1, "fallback_index": 0},
        ),
        SimpleNamespace(
            event_type="llm.request.failed",
            created_at=datetime(2026, 8, 15, 16, 44, 0),
            payload={"failure_type": "timeout"},
        ),
    ]

    assert build_performance_daily_trend(events) == [{
        "date": "2026-08-16",
        "logical_call_count": 1,
        "physical_request_count": 1,
        "retry_count": 0,
        "fallback_count": 0,
        "timeout_count": 1,
        "p95_model_duration_ms": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": None,
    }]


def test_performance_daily_trend_aggregates_stability_and_token_series() -> None:
    """Daily trends expose safe retry, fallback, latency, and token aggregates."""
    events = [
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 16, 1, 0),
            payload={"attempt": 1, "fallback_index": 0},
        ),
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 16, 1, 1),
            payload={"attempt": 2, "fallback_index": 0},
        ),
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 16, 1, 2),
            payload={"attempt": 1, "fallback_index": 1},
        ),
        SimpleNamespace(
            event_type="llm.request.completed",
            created_at=datetime(2026, 8, 16, 1, 3),
            payload={"model_duration_ms": 100, "input_tokens": 10, "output_tokens": 4},
        ),
        SimpleNamespace(
            event_type="llm.request.completed",
            created_at=datetime(2026, 8, 16, 1, 4),
            payload={"model_duration_ms": 300, "input_tokens": 20, "output_tokens": 6},
        ),
        SimpleNamespace(
            event_type="llm.request.failed",
            created_at=datetime(2026, 8, 16, 1, 5),
            payload={"failure_type": "timeout", "model_duration_ms": 200},
        ),
    ]

    assert build_performance_daily_trend(events) == [{
        "date": "2026-08-16",
        "logical_call_count": 1,
        "physical_request_count": 3,
        "retry_count": 1,
        "fallback_count": 1,
        "timeout_count": 1,
        "p95_model_duration_ms": 300,
        "input_tokens": 30,
        "output_tokens": 10,
        "total_tokens": 40,
    }]


def test_model_daily_trend_exposes_safe_named_models_and_groups_the_rest() -> None:
    """The overview keeps named top models, groups lower-volume models, and omits raw payload data."""
    models = [
        ("doubao-seed-1-6-250615", "volcengine", 6),
        ("gpt-4.1-mini", "openai", 5),
        ("qwen-plus", "dashscope", 4),
        ("claude-sonnet-4", "anthropic", 3),
        ("deepseek-v3", "deepseek", 2),
        ("glm-4.5", "zhipu", 1),
    ]
    events = [
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 16, 1, 0),
            payload={
                "model_name": model_name,
                "model_provider": provider,
                "attempt": 1,
                "fallback_index": 0,
                "prompt": "must not reach the trend response",
            },
        )
        for model_name, provider, calls in models
        for _ in range(calls)
    ]
    events.append(SimpleNamespace(
        event_type="llm.request.completed",
        created_at=datetime(2026, 8, 16, 1, 1),
        payload={
            "model_name": "doubao-seed-1-6-250615",
            "model_provider": "volcengine",
            "input_tokens": 12,
            "output_tokens": 8,
            "response": "must not reach the trend response",
        },
    ))

    assert build_performance_model_options(events) == [
        {"model_name": model_name, "model_provider": provider}
        for model_name, provider, _ in models
    ]

    trend = build_model_performance_daily_trend(events)
    assert [(point["model_name"], point["logical_call_count"]) for point in trend] == [
        ("doubao-seed-1-6-250615", 6),
        ("gpt-4.1-mini", 5),
        ("qwen-plus", 4),
        ("claude-sonnet-4", 3),
        ("deepseek-v3", 2),
        ("其他模型", 1),
    ]
    assert trend[0]["model_provider"] == "volcengine"
    assert trend[-1]["model_provider"] is None
    assert trend[0]["input_tokens"] == 12
    assert trend[0]["output_tokens"] == 8
    assert all(set(point) == {
        "date", "model_name", "model_provider", "logical_call_count",
        "physical_request_count", "retry_count", "fallback_count",
        "timeout_count", "p95_model_duration_ms", "input_tokens",
        "output_tokens", "total_tokens",
    } for point in trend)


def test_model_daily_trend_can_be_limited_to_one_actual_model() -> None:
    """A selected model produces only that model's safe aggregate series."""
    events = [
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 16, 1, 0),
            payload={"model_name": "doubao-seed-1-6-250615", "model_provider": "volcengine", "attempt": 1},
        ),
        SimpleNamespace(
            event_type="llm.request.started",
            created_at=datetime(2026, 8, 16, 1, 1),
            payload={"model_name": "gpt-4.1-mini", "model_provider": "openai", "attempt": 1},
        ),
    ]

    assert build_model_performance_daily_trend(
        events, model_name="doubao-seed-1-6-250615"
    ) == [{
        "date": "2026-08-16",
        "model_name": "doubao-seed-1-6-250615",
        "model_provider": "volcengine",
        "logical_call_count": 1,
        "physical_request_count": 1,
        "retry_count": 0,
        "fallback_count": 0,
        "timeout_count": 0,
        "p95_model_duration_ms": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": None,
    }]
