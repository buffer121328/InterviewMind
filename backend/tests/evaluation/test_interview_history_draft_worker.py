"""历史面试评测草稿 Worker 的安全、部分失败与预算边界。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.schemas.evaluations import InterviewEvaluationDraftAnnotation


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session-owner",
        user_id="owner-a",
        title="后端工程师一面",
        status="completed",
        resume_content="安全简历",
        job_description="安全岗位描述",
        company_info="示例公司",
        interview_plan=[{"question": "如何处理限流？", "category": "backend"}],
        question_count=1,
        max_questions=1,
        round_index=1,
        round_type="tech_initial",
        series_id="series-1",
    )


def _attempt(attempt_id: int, *, answer: str = "使用令牌桶") -> SimpleNamespace:
    return SimpleNamespace(
        id=attempt_id,
        user_id="owner-a",
        session_id="session-owner",
        turn_key=f"turn-{attempt_id}",
        asked_question="如何处理限流？",
        user_answer=answer,
        sequence=1,
        evaluation={"score": 8},
        created_at=datetime(2026, 8, 1, 12, 0, 0),
    )


def _annotation(attempt_id: int, *, explanation: str = "安全说明") -> InterviewEvaluationDraftAnnotation:
    return InterviewEvaluationDraftAnnotation(
        case_key=f"case-{attempt_id}",
        category="interview_turn",
        expected_facts=["回答提到了令牌桶"],
        forbidden_claims=[],
        quality_rubric={"groundedness": "仅依据回答"},
        tags=["history"],
        severity="medium",
        explanation=explanation,
    )


class _FakeUnitOfWork:
    db = object()

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _payload(attempt_ids: list[int]) -> dict:
    return {
        "_agent_run_id": "internal-run-id",
        "attempt_ids": attempt_ids,
        "capability": "interview_turn",
        "api_config": {
            "fast": {
                "model": "deepseek-v4-flash",
                "base_url": "https://example.invalid/v1",
            }
        },
    }


@pytest.mark.asyncio
async def test_worker_returns_needs_review_and_ignores_internal_run_field(monkeypatch):
    from ai.workflows.agent_runs.tasks.evaluation import interview_history_draft as task

    rows = {11: (_session(), _attempt(11))}

    class Repository:
        async def get_interview_history_attempts(self, _db, **_kwargs):
            return rows

    async def draft(**_kwargs):
        return _annotation(11), {"model": "deepseek-v4-flash", "fallback_index": 0}

    stages: list[str] = []
    metrics: list[dict] = []

    async def progress(stage: str):
        stages.append(stage)

    monkeypatch.setattr(task, "EvaluationRepository", Repository)
    monkeypatch.setattr(task, "UnitOfWork", _FakeUnitOfWork)
    monkeypatch.setattr(task, "order_drafting_model_references", lambda _config: [{"model": "deepseek-v4-flash"}])
    monkeypatch.setattr(task, "_draft_annotation", draft)
    monkeypatch.setattr(task, "record_model_event", lambda **event: metrics.append(event))

    result = await task.execute_interview_evaluation_draft(_payload([11]), "owner-a", progress)

    assert result["status"] == "needs_review"
    assert result["valid_count"] == 1
    assert result["failed_count"] == 0
    assert result["cases"][0]["model"] == {"model": "deepseek-v4-flash", "fallback_index": 0}
    assert stages == ["loading_sources", "redacting", "drafting", "validating", "needs_review"]
    assert metrics == [
        {
            "event_type": "interview_evaluation_draft.summary",
            "operation": "interview_history_draft",
            "status": "needs_review",
            "item_count": 1,
            "result_count": 1,
            "source_breakdown": {"valid": 1, "rejected": 0, "redaction_failed": 0},
        }
    ]


@pytest.mark.asyncio
async def test_worker_retry_merges_retained_parent_cases_in_original_order(monkeypatch):
    from ai.workflows.agent_runs.tasks.evaluation import interview_history_draft as task

    rows = {12: (_session(), _attempt(12))}
    retained = {
        "attempt_id": 11,
        "session_id": "session-owner",
        "source_hash": "a" * 64,
        "question": "如何处理限流？",
        "answer": "使用令牌桶",
        "frozen_input": {"messages": [{"role": "user", "content": "使用令牌桶"}]},
        "evidence_refs": ["interview-session:session-owner", "interview-attempt:11"],
        "validation_status": "valid",
        "annotation": _annotation(11).model_dump(mode="json"),
        "failure_reason": None,
        "model": {"model": "deepseek-v4-flash", "fallback_index": 0},
    }

    class Repository:
        async def get_interview_history_attempts(self, _db, **_kwargs):
            return rows

    async def draft(**_kwargs):
        return _annotation(12), {"model": "deepseek-v4-flash", "fallback_index": 0}

    async def progress(_stage: str):
        return None

    monkeypatch.setattr(task, "EvaluationRepository", Repository)
    monkeypatch.setattr(task, "UnitOfWork", _FakeUnitOfWork)
    monkeypatch.setattr(task, "order_drafting_model_references", lambda _config: [{"model": "deepseek-v4-flash"}])
    monkeypatch.setattr(task, "_draft_annotation", draft)
    payload = _payload([12]) | {
        "_case_order": [11, 12],
        "_retained_cases": [retained],
    }

    result = await task.execute_interview_evaluation_draft(payload, "owner-a", progress)

    assert [item["attempt_id"] for item in result["cases"]] == [11, 12]
    assert result["selected_count"] == 2
    assert result["valid_count"] == 2


@pytest.mark.asyncio
async def test_worker_keeps_partial_success_for_malformed_output_and_timeout(monkeypatch):
    from ai.workflows.agent_runs.tasks.evaluation import interview_history_draft as task

    rows = {
        11: (_session(), _attempt(11)),
        12: (_session(), _attempt(12)),
        13: (_session(), _attempt(13)),
    }

    class Repository:
        async def get_interview_history_attempts(self, _db, **_kwargs):
            return rows

    async def draft(*, snapshot, **_kwargs):
        if snapshot.attempt_id == 12:
            raise ValueError("malformed structured output")
        if snapshot.attempt_id == 13:
            raise TimeoutError("draft budget exhausted")
        return _annotation(snapshot.attempt_id), {"model": "deepseek-v4-flash", "fallback_index": 0}

    async def progress(_stage: str):
        return None

    monkeypatch.setattr(task, "EvaluationRepository", Repository)
    monkeypatch.setattr(task, "UnitOfWork", _FakeUnitOfWork)
    monkeypatch.setattr(task, "order_drafting_model_references", lambda _config: [{"model": "deepseek-v4-flash"}])
    monkeypatch.setattr(task, "_draft_annotation", draft)

    result = await task.execute_interview_evaluation_draft(_payload([11, 12, 13]), "owner-a", progress)

    assert result["valid_count"] == 1
    assert result["failed_count"] == 2
    by_id = {item["attempt_id"]: item for item in result["cases"]}
    assert by_id[11]["validation_status"] == "valid"
    assert by_id[12]["failure_reason"] == "malformed structured output"
    assert by_id[13]["failure_reason"] == "draft budget exhausted"


@pytest.mark.asyncio
async def test_worker_rejects_sensitive_model_output_without_losing_source_evidence(monkeypatch):
    from ai.workflows.agent_runs.tasks.evaluation import interview_history_draft as task

    rows = {11: (_session(), _attempt(11))}

    class Repository:
        async def get_interview_history_attempts(self, _db, **_kwargs):
            return rows

    async def draft(**_kwargs):
        return _annotation(11, explanation="联系 alice@example.com"), {
            "model": "deepseek-v4-flash",
            "fallback_index": 0,
        }

    async def progress(_stage: str):
        return None

    monkeypatch.setattr(task, "EvaluationRepository", Repository)
    monkeypatch.setattr(task, "UnitOfWork", _FakeUnitOfWork)
    monkeypatch.setattr(task, "order_drafting_model_references", lambda _config: [{"model": "deepseek-v4-flash"}])
    monkeypatch.setattr(task, "_draft_annotation", draft)

    result = await task.execute_interview_evaluation_draft(_payload([11]), "owner-a", progress)
    case = result["cases"][0]

    assert case["validation_status"] == "failed"
    assert case["annotation"] is None
    assert case["model"] == {}
    assert case["failure_reason"] == "sensitive_output_rejected"
    assert case["evidence_refs"] == ["interview-session:session-owner", "interview-attempt:11"]
    assert "alice@example.com" not in str(result)


@pytest.mark.asyncio
async def test_drafting_fails_closed_when_no_candidate_credential_is_usable(monkeypatch):
    from ai.workflows.agent_runs.tasks.evaluation import interview_history_draft as task
    from ai.workflows.evaluation.interview_history import build_source_snapshot

    class Store:
        async def get(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(task, "get_model_credential_store", lambda: Store())
    snapshot = build_source_snapshot(
        session=_session(), attempt=_attempt(11), capability="interview_turn"
    )

    with pytest.raises(RuntimeError, match="没有可用"):
        await task._draft_annotation(
            snapshot=snapshot,
            references=[{"model": "deepseek-v4-flash"}],
            user_id="owner-a",
            deadline=SimpleNamespace(),
        )
