"""面试报告预算监测聚合与 owner 隔离的回归测试。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def _event(
    event_type: str,
    stage: str,
    created_at: datetime,
    event_index: int,
    **payload,
):
    return SimpleNamespace(
        id=event_index,
        run_id="run-report",
        event_index=event_index,
        event_type=event_type,
        stage=stage,
        created_at=created_at,
        payload=payload,
    )


def _run(*, status: str = "running"):
    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id="run-report",
        user_id="user-1",
        task_type="interview_report",
        agent_name="interview_report",
        status=status,
        stage="reviewing",
        created_at=started_at - timedelta(seconds=1),
        updated_at=started_at + timedelta(seconds=3),
        started_at=started_at,
        finished_at=None,
    )


def test_budget_monitor_keeps_running_failed_and_fallback_stages_without_raw_payload():
    from ai.runtime.agent_runs.performance import build_run_budget_monitor

    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    events = [
        _event(
            "llm.request.started",
            "session_report.review.technical_depth",
            started_at,
            1,
            input_chars=1200,
            estimated_input_tokens=300,
            deadline_ms=360000,
            deadline_remaining_ms=360000,
            attempt=1,
            fallback_index=0,
            model_name="reviewer-primary",
            model_provider="provider-a",
            source_breakdown={"resume": 800, "job_description": 400},
            source_token_breakdown={"resume": 200, "job_description": 100},
            source_raw_breakdown={"resume": 1000, "job_description": 400},
            source_raw_token_breakdown={"resume": 250, "job_description": 100},
            truncated_sources=["resume"],
        ),
        _event(
            "llm.request.failed",
            "session_report.review.technical_depth",
            started_at + timedelta(milliseconds=2400),
            2,
            input_chars=1200,
            estimated_input_tokens=300,
            model_duration_ms=2400,
            deadline_ms=360000,
            deadline_remaining_ms=357600,
            failure_type="timeout",
            error_category="timeout",
            error_message="PRIVATE_PROMPT_AND_PROVIDER_ERROR",
        ),
        _event(
            "llm.request.started",
            "session_report.review.technical_depth",
            started_at + timedelta(milliseconds=2500),
            3,
            input_chars=1200,
            estimated_input_tokens=300,
            deadline_ms=360000,
            deadline_remaining_ms=357500,
            attempt=2,
            fallback_index=1,
            model_name="reviewer-fallback",
            model_provider="provider-b",
            source_breakdown={"resume": 800, "job_description": 400},
            source_token_breakdown={"resume": 200, "job_description": 100},
            source_raw_breakdown={"resume": 1000, "job_description": 400},
            source_raw_token_breakdown={"resume": 250, "job_description": 100},
            truncated_sources=["resume"],
        ),
        _event(
            "context.assembled",
            "session_report.reviewer_context",
            started_at + timedelta(milliseconds=2700),
            4,
            input_chars=1600,
            estimated_input_tokens=400,
            duration_ms=80,
            status="completed",
            source_breakdown={"qa_history": 1200, "resume": 400},
            source_token_breakdown={"qa_history": 300, "resume": 100},
        ),
    ]

    snapshot = build_run_budget_monitor(
        _run(),
        events,
        now=started_at + timedelta(milliseconds=3500),
    )

    assert snapshot["run_id"] == "run-report"
    assert snapshot["status"] == "running"
    assert snapshot["is_active"] is True
    assert snapshot["elapsed_ms"] == 3500
    assert snapshot["deadline_ms"] == 360000
    assert snapshot["totals"]["estimated_input_tokens"] == 1000
    assert snapshot["totals"]["model_estimated_input_tokens"] == 600
    assert snapshot["totals"]["context_estimated_input_tokens"] == 400
    assert snapshot["totals"]["context_protection_count"] == 1
    assert snapshot["totals"]["model_duration_ms"] == 2400
    assert snapshot["totals"]["failed_count"] == 1
    assert snapshot["totals"]["retry_count"] == 1
    assert snapshot["totals"]["fallback_count"] == 1
    assert snapshot["totals"]["input_tokens"] is None

    reviewer = next(
        stage for stage in snapshot["stages"]
        if stage["stage"] == "session_report.review.technical_depth"
    )
    assert reviewer["status"] == "running"
    assert reviewer["elapsed_ms"] == 1000
    assert reviewer["failure_types"] == ["timeout"]
    assert reviewer["primary_failure"] == "timeout"
    assert reviewer["warning_types"] == ["context_protection"]
    assert reviewer["primary_warning"] == "context_protection"
    assert reviewer["context_protection_sources"] == ["resume"]
    assert reviewer["source_breakdown"]["resume"] == {
        "input_chars": 1600,
        "estimated_input_tokens": 400,
        "raw_input_chars": 2000,
        "estimated_raw_input_tokens": 500,
    }
    assert reviewer["attempt_count"] == 2
    assert reviewer["retry_count"] == 1
    assert reviewer["fallback_count"] == 1
    context = next(
        stage for stage in snapshot["stages"]
        if stage["stage"] == "session_report.reviewer_context"
    )
    assert context["status"] == "succeeded"
    assert context["kind"] == "context"
    assert context["estimated_input_tokens"] == 400
    assert context["duration_ms"] == 80
    assert context["source_breakdown"]["qa_history"] == {
        "input_chars": 1200,
        "estimated_input_tokens": 300,
    }
    assert snapshot["warning_types"] == ["context_protection"]
    serialized = str(snapshot)
    assert "PRIVATE_PROMPT" not in serialized
    assert "PRIVATE_PROVIDER_ERROR" not in serialized
    assert "error_message" not in serialized


def test_budget_monitor_reports_actual_usage_for_completed_stage():
    from ai.runtime.agent_runs.performance import build_run_budget_monitor

    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    run = _run(status="completed")
    run.finished_at = started_at + timedelta(milliseconds=900)
    run.updated_at = run.finished_at
    events = [
        _event(
            "llm.request.started",
            "session_report.narrative_composer",
            started_at,
            1,
            input_chars=2000,
            estimated_input_tokens=500,
            deadline_ms=360000,
            attempt=1,
            fallback_index=0,
        ),
        _event(
            "llm.request.completed",
            "session_report.narrative_composer",
            started_at + timedelta(milliseconds=900),
            2,
            input_tokens=450,
            output_tokens=120,
            total_tokens=570,
            model_duration_ms=900,
        ),
    ]

    snapshot = build_run_budget_monitor(run, events, now=run.finished_at)
    stage = snapshot["stages"][0]
    assert stage["status"] == "succeeded"
    assert stage["input_tokens"] == 450
    assert stage["output_tokens"] == 120
    assert stage["total_tokens"] == 570
    assert stage["model_duration_ms"] == 900
    assert snapshot["totals"]["total_tokens"] == 570
    assert snapshot["outcome"] == "succeeded"


def test_context_protection_is_a_warning_not_a_failure_for_successful_run():
    from ai.runtime.agent_runs.performance import build_run_budget_monitor

    started_at = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    run = _run(status="completed")
    run.finished_at = started_at + timedelta(milliseconds=20)
    events = [
        _event(
            "context.assembled",
            "interview_report.context_assembly",
            started_at,
            1,
            input_chars=4000,
            estimated_input_tokens=1000,
            truncated_sources=["resume"],
            status="completed",
        ),
    ]

    snapshot = build_run_budget_monitor(run, events, now=run.finished_at)

    assert snapshot["outcome"] == "succeeded"
    assert snapshot["primary_failure"] is None
    assert snapshot["failure_types"] == []
    assert snapshot["warning_types"] == ["context_protection"]
    assert snapshot["stages"][0]["status"] == "succeeded"
    assert snapshot["stages"][0]["primary_warning"] == "context_protection"


def test_report_context_retains_full_resume_within_total_limit():
    from ai.workflows.analysis.analysis_service import SessionReportAnalysisService

    context = SessionReportAnalysisService._assemble_report_context(
        resume="R" * 5000,
        job_description="J" * 2200,
        company_info="C" * 500,
        qa_text="Q" * 12_000,
        include_qa=True,
    )
    audit = {item["name"]: item for item in context.source_audit}

    assert audit["resume"]["included_chars"] == 5000
    assert audit["resume"]["truncated"] is False
    assert "resume" not in context.truncated_sources
    assert context.input_chars <= 40_000


def test_reviewer_context_monitor_records_safe_source_token_breakdown(monkeypatch):
    from ai.workflows.analysis.reviewers import contexts

    events = []
    monkeypatch.setattr(contexts, "record_model_event", lambda **event: events.append(event))

    result = contexts.build_reviewer_contexts(
        resume="Python 简历",
        job_description="后端 JD",
        company_info="示例公司",
        evidence=[{"question_id": "Q1", "candidate_claims": ["回答"]}],
        qa_history=[{"question": "如何设计缓存？", "answer": "使用分层缓存并说明失效策略。"}],
        answer_points_by_question={"Q1": ["回答要点"]},
        monitor_stage="session_report.reviewer_context",
    )

    assert set(result) == {
        "technical_depth", "communication", "job_fit", "factual_risk",
    }
    job_fit = next(
        event for event in events
        if event["stage"] == "session_report.reviewer_context.job_fit"
    )
    assert job_fit["source_token_breakdown"]["resume"] > 0
    assert job_fit["source_token_breakdown"]["job_description"] > 0
    assert job_fit["source_token_breakdown"]["evidence"] > 0
    technical = next(
        event for event in events
        if event["stage"] == "session_report.reviewer_context.technical_depth"
    )
    assert technical["source_token_breakdown"]["qa_history"] > 0
    assert "如何设计缓存？" not in str(technical)
    assert "Python 简历" not in str(job_fit)
    assert "回答要点" not in str(technical)
    assert "如何设计缓存？" in result["technical_depth"]
    assert "使用分层缓存并说明失效策略。" in result["technical_depth"]
    assert "回答要点" in result["technical_depth"]


@pytest.mark.asyncio
async def test_budget_api_is_owner_scoped_and_hides_missing_runs(monkeypatch):
    from fastapi import HTTPException

    from app.api import agent_runs

    calls = []

    async def fake_query(*, user_id: str, run_id: str):
        calls.append((user_id, run_id))
        return {"run_id": run_id, "status": "running", "stages": [], "totals": {}}

    monkeypatch.setattr(agent_runs, "query_run_budget", fake_query)
    response = await agent_runs.get_agent_run_budget("run-report", user_id="user-1")
    assert response["run_id"] == "run-report"
    assert calls == [("user-1", "run-report")]

    async def missing_query(*, user_id: str, run_id: str):
        return None

    monkeypatch.setattr(agent_runs, "query_run_budget", missing_query)
    with pytest.raises(HTTPException) as raised:
        await agent_runs.get_agent_run_budget("other-user-run", user_id="user-1")
    assert raised.value.status_code == 404
    assert raised.value.detail == "任务不存在或无权访问"
