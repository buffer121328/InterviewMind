"""Contracts for product-facing task call-chain health summaries."""

from datetime import UTC, datetime
from types import SimpleNamespace

from ai.runtime.agent_runs.performance import build_task_health_summaries
from app.clock import utc_isoformat

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def run(run_id: str, *, status: str = "succeeded", task_type: str = "interview_turn"):
    return SimpleNamespace(
        id=run_id,
        task_type=task_type,
        agent_name="interview_agent",
        status=status,
        stage="answer",
        trace_id=f"trace-{run_id}",
        created_at=NOW,
        finished_at=NOW if status in {"succeeded", "failed", "cancelled"} else None,
    )


def metric(
    run_id: str,
    event_type: str,
    *,
    payload: dict | None = None,
    stage: str = "answer",
    created_at: datetime = NOW,
):
    return SimpleNamespace(
        run_id=run_id,
        event_type=event_type,
        payload=payload or {},
        stage=stage,
        created_at=created_at,
    )


def test_task_health_uses_final_task_status_and_ignores_non_llm_telemetry() -> None:
    summaries = build_task_health_summaries(
        [run("healthy")],
        [
            metric("healthy", "prompt.rendered"),
            metric("healthy", "embedding.request.completed"),
            metric("healthy", "llm.request.started", payload={"attempt": 1, "fallback_index": 0}),
            metric("healthy", "llm.request.completed", payload={"model_provider": "openai", "model_name": "gpt-5"}),
        ],
    )

    assert summaries == [{
        "run_id": "healthy",
        "trace_id": "trace-healthy",
        "task_type": "interview_turn",
        "agent_name": "interview_agent",
        "task_status": "succeeded",
        "stage": "answer",
        "primary_stage": "answer",
        "outcome": "succeeded",
        "primary_issue": None,
        "model_provider": "openai",
        "model_name": "gpt-5",
        "logical_call_count": 1,
        "physical_attempt_count": 1,
        "failed_attempt_count": 0,
        "timeout_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "skipped_count": 0,
        "context_protection_count": 0,
        "created_at": utc_isoformat(NOW),
        "finished_at": utc_isoformat(NOW),
        "last_model_event_at": utc_isoformat(NOW),
    }]


def test_task_health_marks_successful_task_with_timeout_fallback_as_recovered() -> None:
    summaries = build_task_health_summaries(
        [run("recovered", task_type="interview_report")],
        [
            metric("recovered", "llm.request.started", payload={"attempt": 1, "fallback_index": 0}),
            metric("recovered", "llm.request.failed", payload={"attempt": 1, "failure_type": "timeout"}, stage="session_report.narrative_composer"),
            metric("recovered", "llm.request.started", payload={"attempt": 2, "fallback_index": 1}),
            metric("recovered", "llm.request.completed", payload={"attempt": 2, "fallback_index": 1}, stage="session_report.narrative_composer"),
        ],
    )

    summary = summaries[0]
    assert summary["outcome"] == "recovered"
    assert summary["primary_issue"] == "timeout"
    assert summary["primary_stage"] == "session_report.narrative_composer"
    assert summary["logical_call_count"] == 1
    assert summary["physical_attempt_count"] == 2
    assert summary["failed_attempt_count"] == 1
    assert summary["timeout_count"] == 1
    assert summary["retry_count"] == 1
    assert summary["fallback_count"] == 1


def test_task_health_preserves_final_failure_and_active_work_without_event_rows() -> None:
    summaries = build_task_health_summaries(
        [run("failed", status="failed"), run("active", status="running")],
        [
            metric("failed", "llm.request.skipped", payload={"failure_type": "timeout"}, stage="session_report.narrative_composer"),
            metric("active", "llm.request.started", payload={"attempt": 1, "fallback_index": 0}),
        ],
    )

    failed, active = summaries
    assert failed["outcome"] == "failed"
    assert failed["primary_issue"] == "timeout"
    assert failed["skipped_count"] == 1
    assert active["outcome"] == "active"
    assert active["logical_call_count"] == 1
    assert active["failed_attempt_count"] == 0


def test_task_health_excludes_runs_that_only_have_prompt_or_embedding_events() -> None:
    summaries = build_task_health_summaries(
        [run("non-llm")],
        [
            metric("non-llm", "prompt.rendered"),
            metric("non-llm", "embedding.request.started"),
            metric("non-llm", "embedding.request.failed"),
        ],
    )

    assert summaries == []
