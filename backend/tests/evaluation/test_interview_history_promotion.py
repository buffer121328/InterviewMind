"""历史面试问答晋升为评测数据集的验收契约。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai.workflows.evaluation.interview_history import (
    build_source_snapshot,
    merge_reviewed_case,
    order_drafting_model_references,
    redact_interview_source,
    source_content_hash,
)
from app.schemas.evaluations import (
    InterviewEvaluationConfirmRequest,
    InterviewEvaluationDraftAnnotation,
    InterviewEvaluationDraftCase,
    InterviewEvaluationDraftRequest,
    InterviewEvaluationDraftResult,
    InterviewEvaluationRetryRequest,
    InterviewEvaluationReviewCase,
)


def _session(**overrides):
    values = {
        "session_id": "session-owner",
        "user_id": "owner-a",
        "title": "后端工程师一面",
        "status": "completed",
        "resume_content": "Alice alice@example.com 13800138000 /Users/alice/resume.pdf",
        "job_description": "负责 Python 服务，Authorization: Bearer top-secret-token",
        "company_info": "Example Inc.",
        "interview_plan": [
            {"question": "请介绍你如何处理服务限流？", "category": "backend"},
            {"question": "如何排查慢查询？", "category": "database"},
        ],
        "question_count": 2,
        "max_questions": 2,
        "round_index": 1,
        "round_type": "tech_initial",
        "series_id": "series-1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _attempt(**overrides):
    values = {
        "id": 11,
        "user_id": "owner-a",
        "session_id": "session-owner",
        "turn_key": "turn-1",
        "asked_question": "请介绍你如何处理服务限流？",
        "user_answer": "我会按租户设置令牌桶；联系邮箱 alice@example.com。",
        "sequence": 1,
        "evaluation": {"score": 8},
        "created_at": datetime(2026, 8, 1, 12, 0, 0),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.fast
def test_source_snapshot_is_server_owned_redacted_and_stable():
    session = _session()
    attempt = _attempt()

    snapshot = build_source_snapshot(session=session, attempt=attempt, capability="interview_turn")

    assert snapshot.attempt_id == 11
    assert snapshot.session_id == "session-owner"
    assert snapshot.input["current_question_index"] == 0
    assert snapshot.input["messages"][-1]["content"].endswith("[REDACTED_EMAIL]。")
    assert snapshot.input["resume_context"].count("[REDACTED_EMAIL]") == 1
    assert "[REDACTED_PHONE]" in snapshot.input["resume_context"]
    assert "[REDACTED_LOCAL_PATH]" in snapshot.input["resume_context"]
    assert "top-secret-token" not in str(snapshot.input)
    assert snapshot.evidence_refs == [
        "interview-session:session-owner",
        "interview-attempt:11",
    ]
    assert snapshot.source_hash == source_content_hash(session=session, attempt=attempt)


@pytest.mark.fast
def test_redaction_is_deterministic_and_covers_credentials_and_contact_data():
    source = {
        "authorization": "Bearer abcdefghijklmnop",
        "cookie": "sid=private-cookie",
        "notes": "api_key=sk-12345678901234567890 email bob@example.org phone +86 139-1234-5678",
        "path": "C:\\Users\\bob\\secret.txt",
    }

    first = redact_interview_source(source)
    second = redact_interview_source(source)

    assert first == second
    rendered = str(first)
    assert "private-cookie" not in rendered
    assert "sk-" not in rendered
    assert "bob@example.org" not in rendered
    assert "139-1234-5678" not in rendered
    assert "Users\\bob" not in rendered
    assert "[REDACTED_AUTHORIZATION]" in rendered
    assert "[REDACTED_COOKIE]" in rendered


@pytest.mark.fast
def test_draft_contract_rejects_plaintext_credentials_and_accepts_references():
    valid = InterviewEvaluationDraftRequest(
        attempt_ids=[11],
        capability="interview_turn",
        api_config={
            "fast_pool": [
                {
                    "credential_id": "deepseek-v4-flash",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://example.invalid/v1",
                    "provider": "deepseek",
                }
            ]
        },
    )
    assert valid.attempt_ids == [11]

    with pytest.raises(ValidationError):
        InterviewEvaluationDraftRequest(
            attempt_ids=[11],
            capability="interview_turn",
            api_config={"fast": {"model": "x", "api_key": "plaintext-secret"}},
        )


@pytest.mark.fast
def test_draft_and_confirmation_contracts_require_reviewed_valid_included_cases():
    annotation = InterviewEvaluationDraftAnnotation(
        case_key="interview-turn-11",
        category="interview_turn",
        expected_facts=["应识别回答中的限流策略"],
        forbidden_claims=["不得补造未提及的业务指标"],
        quality_rubric={"groundedness": "仅依据脱敏问答"},
        tags=["history"],
        severity="medium",
        explanation="根据源回答整理",
    )
    result = InterviewEvaluationDraftResult(
        capability="interview_turn",
        status="needs_review",
        selected_count=1,
        valid_count=1,
        failed_count=0,
        cases=[
            InterviewEvaluationDraftCase(
                attempt_id=11,
                session_id="session-owner",
                source_hash="a" * 64,
                question="问题",
                answer="回答",
                frozen_input={"messages": [{"role": "user", "content": "回答"}]},
                evidence_refs=["interview-attempt:11"],
                validation_status="valid",
                annotation=annotation,
            )
        ],
    )
    assert result.status == "needs_review"

    with pytest.raises(ValidationError):
        InterviewEvaluationConfirmRequest(
            name="history",
            version="v1",
            cases=[
                InterviewEvaluationReviewCase(
                    attempt_id=11,
                    reviewed=False,
                    included=True,
                    annotation=annotation,
                )
            ],
        )


def test_deepseek_flash_is_preferred_without_dropping_fast_fallbacks():
    calls: list[tuple[str, list[str]]] = []

    class Scheduler:
        def order(self, pool_name, configs):
            calls.append((pool_name, [item["model"] for item in configs]))
            return list(reversed(configs))

    ordered = order_drafting_model_references(
        {
            "fast_pool": [
                {"model": "qwen-turbo", "base_url": "https://qwen.invalid/v1"},
                {"model": "DeepSeek-V4-Flash", "base_url": "https://ds.invalid/v1"},
                {"model": "mimo-v2.5", "base_url": "https://mimo.invalid/v1"},
            ],
            "fast": {"model": "fast-default", "base_url": "https://fast.invalid/v1"},
            "smart": {"model": "expired-smart", "base_url": "https://smart.invalid/v1"},
        },
        scheduler=Scheduler(),
    )

    assert [item["model"] for item in ordered] == [
        "DeepSeek-V4-Flash",
        "mimo-v2.5",
        "qwen-turbo",
        "fast-default",
        "expired-smart",
    ]
    assert calls == [
        ("interview_evaluation_draft:deepseek_flash", ["DeepSeek-V4-Flash"]),
        ("fast_pool", ["qwen-turbo", "mimo-v2.5"]),
    ]


def test_server_merge_ignores_model_authored_input_and_uses_reviewed_fields():
    snapshot = build_source_snapshot(
        session=_session(resume_content="安全简历"),
        attempt=_attempt(user_answer="安全回答"),
        capability="interview_turn",
    )
    review = InterviewEvaluationReviewCase(
        attempt_id=11,
        reviewed=True,
        included=True,
        annotation=InterviewEvaluationDraftAnnotation(
            case_key="reviewed-11",
            category="interview_turn",
            expected_facts=["回答提到了令牌桶"],
            forbidden_claims=[],
            quality_rubric={"groundedness": "必须引用回答"},
            tags=["reviewed"],
            severity="high",
            explanation="人工已核对",
        ),
    )

    case = merge_reviewed_case(snapshot=snapshot, review=review, draft_run_id="run-123")

    assert case.input == snapshot.input
    assert case.case_key == "reviewed-11"
    assert "agent-run:run-123" in case.evidence_refs
    assert "human-reviewed" in case.tags


@pytest.mark.asyncio
async def test_source_listing_exposes_only_owner_safe_attempt_summaries(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.service import EvaluationUseCases

    session = _session(updated_at=datetime(2026, 8, 1, 13, 0, 0))
    attempt = _attempt()

    class Repository:
        async def list_interview_history_sessions(self, _db, **kwargs):
            assert kwargs["user_id"] == "owner-a"
            return [session], {session.session_id: [attempt]}, 1

    class FakeUnitOfWork:
        db = object()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    payload = await use_cases.list_interview_history_sources(
        user_id="owner-a", limit=20, offset=0
    )

    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["eligible"] is True
    assert item["attempts"] == [
        {
            "attempt_id": 11,
            "sequence": 1,
            "question": "请介绍你如何处理服务限流？",
            "created_at": "2026-08-01T12:00:00",
        }
    ]
    rendered = str(payload)
    assert "alice@example.com" not in rendered
    assert "令牌桶" not in rendered
    assert "job_description" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_overrides", "attempt_overrides", "reason"),
    [
        ({"status": "active"}, {}, "session_not_completed"),
        ({"interview_plan": None}, {}, "missing_interview_plan"),
        ({"resume_content": ""}, {}, "missing_resume_context"),
        ({"job_description": ""}, {}, "missing_job_context"),
        ({}, {"user_id": "owner-b"}, "owner_mismatch"),
        ({}, {"user_answer": ""}, "missing_answer"),
    ],
)
async def test_draft_submission_rejects_ineligible_sources_before_queue(
    monkeypatch, session_overrides, attempt_overrides, reason
):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.contracts import EvaluationUseCaseError
    from ai.workflows.evaluation.service import EvaluationUseCases

    session = _session(**session_overrides)
    attempt = _attempt(**attempt_overrides)

    class Repository:
        async def get_interview_history_attempts(self, _db, **_kwargs):
            return {11: (session, attempt)}

    class FakeUnitOfWork:
        db = object()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    queued = False

    async def unexpected_queue(**_kwargs):
        nonlocal queued
        queued = True
        raise AssertionError("model task must not be queued")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(
        use_case_module.agent_run_use_cases, "create_queued_run", unexpected_queue
    )
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)
    request = InterviewEvaluationDraftRequest(
        attempt_ids=[11],
        capability="interview_turn",
        api_config={
            "fast": {
                "model": "deepseek-v4-flash",
                "base_url": "https://example.invalid/v1",
            }
        },
    )

    with pytest.raises(EvaluationUseCaseError, match=reason):
        await use_cases.create_interview_history_draft(
            user_id="owner-a", request=request, idempotency_key="draft-1"
        )

    assert queued is False


@pytest.mark.asyncio
async def test_drafting_hydrates_only_candidates_that_are_actually_attempted(monkeypatch):
    from ai.workflows.agent_runs.tasks.evaluation import interview_history_draft as task

    looked_up: list[str] = []

    class Store:
        async def get(self, _user_id, model_name, **_kwargs):
            looked_up.append(model_name)
            return {
                "deepseek-v4-flash": None,
                "qwen-turbo": "qwen-key",
                "unused-smart": "smart-key",
            }.get(model_name)

    async def fake_invoke(**kwargs):
        assert kwargs["api_config"]["fast"]["model"] == "qwen-turbo"
        return InterviewEvaluationDraftAnnotation(
            case_key="case-11",
            category="interview_turn",
            expected_facts=[],
            forbidden_claims=[],
            quality_rubric={},
            tags=[],
            severity="medium",
            explanation="safe",
        )

    monkeypatch.setattr(task, "get_model_credential_store", lambda: Store())
    monkeypatch.setattr(task, "invoke_structured", fake_invoke)
    snapshot = build_source_snapshot(
        session=_session(resume_content="安全简历"),
        attempt=_attempt(user_answer="安全回答"),
        capability="interview_turn",
    )
    annotation, metadata = await task._draft_annotation(
        snapshot=snapshot,
        references=[
            {"model": "deepseek-v4-flash", "base_url": "https://ds.invalid/v1"},
            {"model": "qwen-turbo", "base_url": "https://qwen.invalid/v1"},
            {"model": "unused-smart", "base_url": "https://smart.invalid/v1"},
        ],
        user_id="owner-a",
        deadline=SimpleNamespace(),
    )

    assert annotation.case_key == "case-11"
    assert metadata["model"] == "qwen-turbo"
    assert metadata["fallback_index"] == 0
    assert looked_up == ["deepseek-v4-flash", "qwen-turbo"]


@pytest.mark.asyncio
async def test_promoted_interview_case_uses_evaluation_driver_isolation(monkeypatch):
    from evaluation.extractors.runtime import EvaluationTraceCollector
    from evaluation.runners import production
    from evaluation.runners.base import EvaluationExecutionContext

    seen: dict[str, object] = {}

    class Driver:
        async def run(self, **kwargs):
            seen.update(kwargs)
            return {"messages": [{"role": "assistant", "content": "safe"}]}

    monkeypatch.setattr(
        "ai.workflows.agent_runs.catalog.get_evaluation_driver", lambda: Driver()
    )
    context = EvaluationExecutionContext.for_run("promoted-run-1")
    trace = EvaluationTraceCollector(evaluation_namespace="eval:promoted-run-1")
    payload = {"session_id": "source-session-must-not-be-used", "messages": []}

    result = await production._run_interview_turn_case(
        payload,
        context,
        trace,
        SimpleNamespace(key="interview_turn"),
    )

    assert result["messages"][0]["content"] == "safe"
    assert seen["task_type"] == "interview_turn"
    assert seen["user_id"] == "eval-user:promoted-run-1"
    assert seen["session_id"] == "eval-session:promoted-run-1"
    assert seen["memory_namespace"] == "eval:memory:promoted-run-1"
    assert seen["artifact_namespace"] == "eval:artifact:promoted-run-1"
    assert seen["payload"] is payload


def _valid_draft_case_dict(source_hash: str) -> dict:
    return InterviewEvaluationDraftCase(
        attempt_id=11,
        session_id="session-owner",
        source_hash=source_hash,
        question="安全问题",
        answer="安全回答",
        frozen_input={"messages": [{"role": "user", "content": "安全回答"}]},
        evidence_refs=["interview-attempt:11"],
        validation_status="valid",
        annotation=InterviewEvaluationDraftAnnotation(
            case_key="case-11",
            category="interview_turn",
            expected_facts=[],
            forbidden_claims=[],
            quality_rubric={},
            tags=[],
            severity="medium",
            explanation="safe",
        ),
    ).model_dump(mode="json")


def _confirm_request() -> InterviewEvaluationConfirmRequest:
    return InterviewEvaluationConfirmRequest(
        name="history-dataset",
        version="v1",
        cases=[
            InterviewEvaluationReviewCase(
                attempt_id=11,
                reviewed=True,
                included=True,
                annotation=InterviewEvaluationDraftAnnotation(
                    case_key="case-11",
                    category="interview_turn",
                    expected_facts=[],
                    forbidden_claims=[],
                    quality_rubric={},
                    tags=[],
                    severity="medium",
                    explanation="reviewed",
                ),
            )
        ],
    )


@pytest.mark.asyncio
async def test_duplicate_confirmation_returns_same_dataset_without_second_write(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.service import EvaluationUseCases

    existing = SimpleNamespace(
        id="eds-existing",
        name="history-dataset",
        version="v1",
        status="draft",
        case_count=1,
        source="interview_history:draft-run-1",
        content_hash="hash",
        created_at=datetime(2026, 8, 1, 12, 0, 0),
        locked_at=None,
    )
    run = SimpleNamespace(
        id="draft-run-1",
        status="succeeded",
        result={"capability": "interview_turn", "cases": []},
    )

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Repository:
        async def get_dataset_by_name_version(self, _db, **_kwargs):
            return existing

        async def create_dataset(self, *_args, **_kwargs):
            raise AssertionError("duplicate confirmation must not write")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    result = await use_cases.confirm_interview_history_draft(
        user_id="owner-a",
        draft_run_id="draft-run-1",
        request=_confirm_request(),
    )

    assert result["id"] == "eds-existing"
    assert result["status"] == "draft"


@pytest.mark.asyncio
async def test_confirmation_rejects_name_version_owned_by_another_source(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.contracts import EvaluationUseCaseError
    from ai.workflows.evaluation.service import EvaluationUseCases

    existing = SimpleNamespace(
        id="eds-conflict",
        name="history-dataset",
        version="v1",
        source="manual",
    )
    run = SimpleNamespace(
        id="draft-run-1",
        status="succeeded",
        result={"capability": "interview_turn", "cases": []},
    )

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Repository:
        async def get_dataset_by_name_version(self, _db, **_kwargs):
            return existing

        async def create_dataset(self, *_args, **_kwargs):
            raise AssertionError("conflicting name/version must not write")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    with pytest.raises(EvaluationUseCaseError, match="名称和版本已存在"):
        await use_cases.confirm_interview_history_draft(
            user_id="owner-a",
            draft_run_id="draft-run-1",
            request=_confirm_request(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled"])
async def test_unfinished_cancelled_or_abandoned_draft_cannot_create_dataset(
    monkeypatch, status
):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.contracts import EvaluationUseCaseError
    from ai.workflows.evaluation.service import EvaluationUseCases

    run = SimpleNamespace(id="draft-run-1", status=status, result=None)

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Repository:
        async def create_dataset(self, *_args, **_kwargs):
            raise AssertionError("non-review draft must not create a dataset")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    with pytest.raises(EvaluationUseCaseError, match="尚未进入人工审阅状态"):
        await use_cases.confirm_interview_history_draft(
            user_id="owner-a",
            draft_run_id="draft-run-1",
            request=_confirm_request(),
        )


@pytest.mark.asyncio
async def test_confirmation_rejects_source_drift_before_dataset_write(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.contracts import EvaluationUseCaseError
    from ai.workflows.evaluation.service import EvaluationUseCases

    session = _session(resume_content="当前简历")
    attempt = _attempt(user_answer="当前回答")
    stale_hash = "f" * 64
    run = SimpleNamespace(
        id="draft-run-1",
        status="succeeded",
        result={
            "capability": "interview_turn",
            "cases": [_valid_draft_case_dict(stale_hash)],
        },
    )

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Repository:
        async def get_dataset_by_name_version(self, _db, **_kwargs):
            return None

        async def get_interview_history_attempts(self, _db, **_kwargs):
            return {11: (session, attempt)}

        async def create_dataset(self, *_args, **_kwargs):
            raise AssertionError("drifted source must not write")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    with pytest.raises(EvaluationUseCaseError, match="发生变化"):
        await use_cases.confirm_interview_history_draft(
            user_id="owner-a",
            draft_run_id="draft-run-1",
            request=_confirm_request(),
        )


@pytest.mark.asyncio
async def test_confirmation_rejects_failed_draft_case_without_partial_dataset(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.contracts import EvaluationUseCaseError
    from ai.workflows.evaluation.service import EvaluationUseCases

    session = _session(resume_content="安全简历")
    attempt = _attempt(user_answer="安全回答")
    source_hash = source_content_hash(session=session, attempt=attempt)
    failed = _valid_draft_case_dict(source_hash)
    failed["validation_status"] = "failed"
    failed["annotation"] = None
    failed["failure_reason"] = "schema_validation_failed"
    run = SimpleNamespace(
        id="draft-run-1",
        status="succeeded",
        result={"capability": "interview_turn", "cases": [failed]},
    )

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Repository:
        async def get_dataset_by_name_version(self, _db, **_kwargs):
            return None

        async def get_interview_history_attempts(self, _db, **_kwargs):
            return {11: (session, attempt)}

        async def create_dataset(self, *_args, **_kwargs):
            raise AssertionError("failed case must not partially write")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    use_cases = EvaluationUseCases(repository=Repository())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    with pytest.raises(EvaluationUseCaseError, match="尚未通过校验"):
        await use_cases.confirm_interview_history_draft(
            user_id="owner-a",
            draft_run_id="draft-run-1",
            request=_confirm_request(),
        )


@pytest.mark.asyncio
async def test_retry_selected_failed_cases_reuses_parent_capability(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.service import EvaluationUseCases

    run = SimpleNamespace(
        id="draft-run-1",
        user_id="owner-a",
        task_type="interview_evaluation_draft",
        status="succeeded",
        result={
            "capability": "interview_scoring",
            "cases": [
                {"attempt_id": 11, "validation_status": "valid"},
                {"attempt_id": 12, "validation_status": "failed"},
                {"attempt_id": 13, "validation_status": "failed"},
            ],
        },
    )

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    queued: dict = {}

    async def fake_queue(**kwargs):
        queued.update(kwargs)
        return SimpleNamespace(payload={"run_id": "draft-run-retry", "status": "queued"})

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(use_case_module.agent_run_use_cases, "create_queued_run", fake_queue)
    use_cases = EvaluationUseCases(repository=SimpleNamespace())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    result = await use_cases.retry_interview_history_draft_cases(
        user_id="owner-a",
        draft_run_id="draft-run-1",
        request=InterviewEvaluationRetryRequest(
            attempt_ids=[13, 12],
            api_config={"fast": {"model": "deepseek-v4-flash"}},
        ),
        idempotency_key=None,
    )

    assert result == {"run_id": "draft-run-retry", "status": "queued"}
    assert queued["payload"]["attempt_ids"] == [13, 12]
    assert queued["payload"]["capability"] == "interview_scoring"
    assert queued["payload"]["_case_order"] == [11, 12, 13]
    assert queued["payload"]["_retained_cases"] == [
        {"attempt_id": 11, "validation_status": "valid"}
    ]
    assert "draft-run-1" in queued["idempotency_key"]


@pytest.mark.asyncio
async def test_retry_rejects_cases_that_did_not_fail(monkeypatch):
    from ai.workflows.evaluation import interview_history_use_cases as use_case_module
    from ai.workflows.evaluation.contracts import EvaluationUseCaseError
    from ai.workflows.evaluation.service import EvaluationUseCases

    run = SimpleNamespace(
        id="draft-run-1",
        user_id="owner-a",
        task_type="interview_evaluation_draft",
        status="succeeded",
        result={
            "capability": "interview_turn",
            "cases": [{"attempt_id": 11, "validation_status": "valid"}],
        },
    )

    class DB:
        async def scalar(self, _statement):
            return run

    class FakeUnitOfWork:
        db = DB()

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def unexpected_queue(**_kwargs):
        raise AssertionError("non-failed cases must not be retried")

    monkeypatch.setattr(use_case_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(use_case_module.agent_run_use_cases, "create_queued_run", unexpected_queue)
    use_cases = EvaluationUseCases(repository=SimpleNamespace())
    monkeypatch.setattr(use_cases, "_ensure_center_enabled", lambda: None)

    with pytest.raises(EvaluationUseCaseError, match="仅可重试"):
        await use_cases.retry_interview_history_draft_cases(
            user_id="owner-a",
            draft_run_id="draft-run-1",
            request=InterviewEvaluationRetryRequest(
                attempt_ids=[11],
                api_config={"fast": {"model": "deepseek-v4-flash"}},
            ),
            idempotency_key="retry-1",
        )


@pytest.mark.fast
def test_evaluation_router_exposes_interview_history_promotion_endpoints():
    from app.api.evaluations import router

    paths = {route.path for route in router.routes}
    assert "/api/evaluations/interview-history/sources" in paths
    assert "/api/evaluations/interview-history/sources/{attempt_id}" in paths
    assert "/api/evaluations/interview-history/drafts" in paths
    assert "/api/evaluations/interview-history/drafts/{draft_run_id}" in paths
    assert (
        "/api/evaluations/interview-history/drafts/{draft_run_id}/retry-failed"
        in paths
    )
    assert (
        "/api/evaluations/interview-history/drafts/{draft_run_id}/confirm" in paths
    )
