"""案例分类、候选数据集、评测报告、线上抽样与 Prompt 发布治理测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.workflows.evaluation.service import EvaluationUseCaseError
from app.db.repositories.evaluation.repository import EvaluationRepository
from app.db.repositories.evaluation.helpers import _candidate_governance_metadata
from app.db.models.evaluation import EvaluationAnnotationModel
from app.schemas.evaluation.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationCandidateDatasetRequest,
    EvaluationCaseCreateRequest,
)
from evaluation.online import sampling_decision, sanitize_production_trace
from evaluation.outcomes import classify_case_outcome
from evaluation.reporting import build_run_report, render_run_report_html
from evaluation.runners import AgentEvalRunner, EvaluationCaseSpec
from evaluation.schemas import EvalObservabilitySummary, EvalTraceCompleteness, ScoreSource


@pytest.mark.fast
def test_trace_incomplete_case_requires_manual_review() -> None:
    """即使业务成功且硬门禁通过，关键 Trace 缺失也不能静默离开复核队列。"""

    case = EvaluationCaseSpec(
        case_id="case-trace",
        dataset_version="v1",
        input_payload={"safe": True},
    )
    record = AgentEvalRunner.minimal_record_for_test(
        case=case, actual_output={"answer": "ok"}
    )
    semantic_score = AgentEvalRunner.passing_score_for_test(
        source=ScoreSource.DETERMINISTIC
    )
    incomplete = classify_case_outcome(record, [semantic_score])
    complete_record = record.model_copy(
        update={
            "observability": EvalObservabilitySummary(
                trace_completeness=EvalTraceCompleteness(
                    complete=True,
                    score=1.0,
                )
            )
        }
    )
    complete = classify_case_outcome(complete_record, [semantic_score])

    assert incomplete.review_required
    assert "trace_incomplete" in incomplete.review_reasons
    assert not complete.review_required


@pytest.mark.fast
def test_candidate_governance_metadata_uses_only_structured_safe_evidence() -> None:
    """失败沉淀只派生结构化治理标签和稳定引用，不复制轨迹正文。"""

    tags, evidence_refs = _candidate_governance_metadata(
        record={
            "tool_calls": [
                {
                    "tool_name": "boss_apply",
                    "effect": "external",
                    "error_category": "tool_execution_error",
                    "evidence_refs": ["tool-call:call-1", "raw evidence text"],
                    "arguments_summary": {"job_description": "不得复制的正文"},
                }
            ],
            "approvals": [
                {
                    "status": "rejected",
                    "evidence_refs": ["approval:approval-1"],
                }
            ],
            "retrievals": [{"empty_result": True, "result_count": 0}],
            "observability": {"trace_completeness": {"complete": False}},
        },
        error_category="dependency_failure",
        scores=[
            SimpleNamespace(
                status="failed",
                hard_gate=True,
                metric_name="hard_gate.unapproved_external_action",
                evidence_refs=[
                    "tool-call:call-1:approval",
                    "api_key=sk-not-safe-1234567890",
                ],
            )
        ],
    )

    assert {
        "tool:boss_apply",
        "effect:external",
        "approval:rejected",
        "retrieval:observed",
        "retrieval:empty",
        "trace:incomplete",
        "error:tool_execution_error",
        "error:dependency_failure",
        "gate:hard_gate.unapproved_external_action",
    } <= set(tags)
    assert evidence_refs == [
        "tool-call:call-1",
        "approval:approval-1",
        "tool-call:call-1:approval",
    ]


@pytest.mark.fast
def test_evaluation_case_rejects_sensitive_candidate_evidence_refs() -> None:
    """Candidate Dataset 的证据字段不能成为凭据或自由文本写入通道。"""

    with pytest.raises(ValidationError, match="unsafe evaluation evidence reference"):
        EvaluationCaseCreateRequest(
            case_key="case-1",
            category="regression",
            input={"topic": "safe"},
            evidence_refs=["api_key=sk-not-safe-1234567890"],
        )


@pytest.mark.asyncio
async def test_candidate_dataset_preserves_safe_tags_and_evidence_refs(monkeypatch) -> None:
    """从失败案例创建新版本时自动保存治理 tags，并把 evidence refs 加密进期望载荷。"""

    from app.db.repositories.evaluation import candidate_dataset_repository as repository_module

    repository = EvaluationRepository()
    case_run = SimpleNamespace(
        id="case-run-1",
        case_id="case-1",
        status="failed",
        hard_gate_passed=False,
        review_status="rejected",
        error_category="dependency_failure",
        record_sanitized={
            "tool_calls": [
                {
                    "tool_name": "search_question_bank",
                    "effect": "external",
                    "status": "failed",
                    "evidence_refs": ["tool-call:call-1"],
                }
            ],
            "approvals": [{"status": "approved"}],
            "retrievals": [{"empty_result": True, "result_count": 0}],
            "observability": {"trace_completeness": {"complete": False}},
        },
    )
    source_case = SimpleNamespace(
        id="case-1",
        case_key="source-case",
        input_encrypted="encrypted-input",
        expected_encrypted="encrypted-expected",
    )
    score = SimpleNamespace(
        status="failed",
        hard_gate=True,
        metric_name="hard_gate.unapproved_external_action",
        evidence_refs=["tool-call:call-1:approval"],
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=source_case),
        scalars=AsyncMock(return_value=[score]),
    )
    repository.get_case_run = AsyncMock(return_value=case_run)
    repository.get_dataset_by_name_version = AsyncMock(return_value=None)
    captured: dict[str, object] = {}
    created = SimpleNamespace(id="dataset-1")

    async def fake_create_dataset(_session, *, user_id, request):
        """捕获 Repository 构造出的不可变 Candidate Dataset 请求。"""

        captured.update(user_id=user_id, request=request)
        return created

    repository.create_dataset = fake_create_dataset
    monkeypatch.setattr(
        repository_module,
        "decrypt_payload",
        lambda value: (
            {"topic": "safe-input"}
            if value == "encrypted-input"
            else {
                "expected_output": {"answer": "safe"},
                "evidence_refs": ["event:source-case"],
            }
        ),
    )

    result = await repository.create_candidate_dataset_from_case_run(
        session,
        user_id="owner-1",
        case_run_id="case-run-1",
        request=EvaluationCandidateDatasetRequest(
            name="candidate-regression",
            version="v1",
            tags=["manual-confirmed"],
        ),
    )

    assert result is created
    dataset_request = captured["request"]
    candidate = dataset_request.cases[0]
    assert {
        "candidate",
        "regression",
        "manual-confirmed",
        "tool:search_question_bank",
        "effect:external",
        "approval:approved",
        "retrieval:empty",
        "trace:incomplete",
        "error:dependency_failure",
        "gate:hard_gate.unapproved_external_action",
    } <= set(candidate.tags)
    assert candidate.evidence_refs == [
        "event:source-case",
        "tool-call:call-1",
        "tool-call:call-1:approval",
    ]

    from app.db.repositories.evaluation import repository as aggregate_repository_module

    monkeypatch.setattr(aggregate_repository_module, "encrypt_payload", lambda value: value)
    stored = repository._case_model("dataset-1", candidate)
    assert stored.expected_encrypted["evidence_refs"] == candidate.evidence_refs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "hard_gate_passed", "review_status", "score_status"),
    [
        ("succeeded", True, "pending", "passed"),
        ("succeeded", True, "approved", "passed"),
        ("succeeded", True, "waived", "passed"),
        ("failed", False, "rerun_requested", "failed"),
        ("succeeded", True, "rejected", "passed"),
    ],
)
async def test_candidate_dataset_requires_confirmed_automatic_failure(
    status: str,
    hard_gate_passed: bool,
    review_status: str,
    score_status: str,
) -> None:
    """成功、待处理或没有自动失败事实的案例都不能伪装成回归案例。"""

    repository = EvaluationRepository()
    repository.get_case_run = AsyncMock(
        return_value=SimpleNamespace(
            id="case-run-1",
            case_id="case-1",
            status=status,
            hard_gate_passed=hard_gate_passed,
            review_status=review_status,
            error_category=None,
            record_sanitized={},
        )
    )
    session = SimpleNamespace(
        scalars=AsyncMock(
            return_value=[
                SimpleNamespace(
                    status=score_status,
                    source="deterministic",
                    hard_gate=not hard_gate_passed,
                    metric_name="quality.semantic",
                    evidence_refs=[],
                )
            ]
        ),
        scalar=AsyncMock(),
    )

    with pytest.raises(ValueError, match="人工确认不通过|自动失败"):
        await repository.create_candidate_dataset_from_case_run(
            session,
            user_id="owner-1",
            case_run_id="case-run-1",
            request=EvaluationCandidateDatasetRequest(name="regression", version="v1"),
        )

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_dataset_confirmation_is_idempotent() -> None:
    """同一失败案例的重复确认返回已有来源版本，不重复复制案例。"""

    repository = EvaluationRepository()
    existing = SimpleNamespace(
        id="dataset-existing",
        source="confirmed_failure:case-run-1",
    )
    repository.get_case_run = AsyncMock(
        return_value=SimpleNamespace(
            id="case-run-1",
            case_id="case-1",
            status="failed",
            hard_gate_passed=False,
            review_status="rejected",
            error_category="runtime_error",
            record_sanitized={},
        )
    )
    repository.get_dataset_by_name_version = AsyncMock(return_value=existing)
    repository.create_dataset = AsyncMock(side_effect=AssertionError("must reuse"))
    session = SimpleNamespace(
        scalars=AsyncMock(
            return_value=[
                SimpleNamespace(
                    status="failed",
                    source="deterministic",
                    hard_gate=True,
                    metric_name="runtime.success",
                    evidence_refs=[],
                )
            ]
        ),
        scalar=AsyncMock(),
    )

    result = await repository.create_candidate_dataset_from_case_run(
        session,
        user_id="owner-1",
        case_run_id="case-run-1",
        request=EvaluationCandidateDatasetRequest(name="regression", version="v1"),
    )

    assert result is existing
    session.scalar.assert_not_awaited()


@pytest.mark.fast
def test_blind_review_contract_and_model_columns_are_persisted() -> None:
    """双人盲测身份与盲化状态必须进入追加式审计模型。"""

    request = EvaluationAnnotationCreateRequest(
        rubric_version="v1",
        annotation_type="binary",
        metric_name="quality",
        value=True,
        reviewer_key="reviewer-a",
        blind=True,
    )

    assert request.reviewer_key == "reviewer-a"
    assert {"reviewer_key", "blind"} <= set(
        EvaluationAnnotationModel.__table__.columns.keys()
    )


@pytest.mark.fast
def test_report_contains_all_pass_latency_tokens_and_recovery() -> None:
    """JSON 与 HTML 报告保留 all-pass@N、P50/P95、Token 和恢复统计。"""

    report = build_run_report(
        {"id": "run-1", "agent_name": "interview_planner"},
        [
            {
                "case_id": "case-a",
                "status": "succeeded",
                "hard_gate_passed": True,
                "latency_ms": 100,
                "overall_score": 0.9,
                "token_usage": {"total_tokens": 10},
                "record": {"recovery_count": 1},
            },
            {
                "case_id": "case-a",
                "status": "failed",
                "hard_gate_passed": True,
                "latency_ms": 300,
                "overall_score": 0.5,
                "token_usage": {"total_tokens": 20},
                "record": {},
            },
        ],
    )

    assert report["metrics"]["all_pass_at_n"] == 0
    assert report["metrics"]["p50_latency_ms"] == 200
    assert report["metrics"]["p95_latency_ms"] == 290
    assert report["metrics"]["token_total"] == 30
    assert "Agent 评测报告" in render_run_report_html(report)


@pytest.mark.fast
def test_online_sampling_is_deterministic_and_trace_is_sanitized() -> None:
    """廉价规则 100% 执行，风险抽样稳定且凭据不会进入候选记录。"""

    first = sampling_decision(trace_id="trace-1", risk_level="high")
    second = sampling_decision(trace_id="trace-1", risk_level="high")
    trace = sanitize_production_trace(
        {"authorization": "Bearer secret", "message": "api_key=sk-12345678901234567890"}
    )

    assert first == second
    assert first["deterministic"] is True
    assert trace["authorization"] == "[REDACTED]"
    assert "sk-" not in trace["message"]


@pytest.mark.fast
def test_online_sample_use_case_returns_sanitized_stable_decision(monkeypatch) -> None:
    """API 用例必须连接已有抽样领域逻辑，而不是调用缺失方法。"""

    from ai.workflows.evaluation import service as service_module
    from ai.workflows.evaluation.service import EvaluationUseCases
    from app.schemas.evaluation.evaluations import EvaluationOnlineSampleRequest

    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            evaluation_center_enabled=True,
            evaluation_online_sampling_enabled=True,
        ),
    )
    request = EvaluationOnlineSampleRequest(
        trace_id="trace-stable",
        risk_level="high",
        trace={
            "authorization": "Bearer secret",
            "message": "api_key=sk-12345678901234567890",
        },
    )

    first = EvaluationUseCases(repository=SimpleNamespace()).online_sample(request=request)
    second = EvaluationUseCases(repository=SimpleNamespace()).online_sample(request=request)

    assert first == second
    assert first["decision"]["deterministic"] is True
    assert first["trace"]["authorization"] == "[REDACTED]"
    assert "sk-" not in first["trace"]["message"]


@pytest.mark.fast
def test_online_sample_use_case_rejects_when_disabled(monkeypatch) -> None:
    """在线抽样关闭时返回受控错误，不得退化为 AttributeError/500。"""

    from ai.workflows.evaluation import service as service_module
    from ai.workflows.evaluation.service import EvaluationUseCases
    from app.schemas.evaluation.evaluations import EvaluationOnlineSampleRequest

    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            evaluation_center_enabled=True,
            evaluation_online_sampling_enabled=False,
        ),
    )

    with pytest.raises(EvaluationUseCaseError, match="在线抽样") as exc_info:
        EvaluationUseCases(repository=SimpleNamespace()).online_sample(
            request=EvaluationOnlineSampleRequest(
                trace_id="trace-disabled", risk_level="low", trace={}
            )
        )

    assert exc_info.value.status_code == 403


@pytest.mark.fast
def test_evaluation_router_exposes_report_candidate_and_online_governance() -> None:
    """闭环 API 必须包含报告、失败沉淀与线上抽样入口。"""

    from app.api.evaluation.evaluations import router

    paths = {route.path for route in router.routes}
    assert "/api/evaluations/runs/{run_id}/report" in paths
    assert "/api/evaluations/case-runs/{case_run_id}/candidate-dataset" in paths
    assert "/api/evaluations/online-samples/evaluate" in paths


@pytest.mark.fast
def test_prompt_promotion_is_blocked_before_remote_write(monkeypatch) -> None:
    """强制门禁失败时不得调用 Langfuse production label 写操作。"""

    from app.api.langfuse_prompts import evaluation_use_cases, router

    gate = AsyncMock(
        side_effect=EvaluationUseCaseError("blocked", status_code=409)
    )
    update_labels = AsyncMock(return_value=SimpleNamespace())
    service = SimpleNamespace(update_labels=update_labels)
    monkeypatch.setattr(evaluation_use_cases, "validate_prompt_promotion", gate)
    monkeypatch.setattr("app.api.langfuse_prompts._service", lambda: service)
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).put(
        "/api/langfuse/prompts/production",
        json={"name": "interview.system", "version": 2, "evaluation_run_id": "erun-1"},
    )

    assert response.status_code == 409
    assert update_labels.await_count == 0


@pytest.mark.asyncio
@pytest.mark.fast
async def test_dataset_parent_is_flushed_before_case_rows_are_added():
    """The dataset FK parent must exist before encrypted child cases are flushed."""
    from app.schemas.evaluation.evaluations import EvaluationDatasetCreateRequest

    order: list[str] = []

    class FakeSession:
        def add(self, value):
            order.append("case" if getattr(value, "kind", None) == "case" else "dataset")

        async def flush(self):
            order.append("flush")

    class TestRepository(EvaluationRepository):
        @staticmethod
        def _case_model(_dataset_id, _case):
            return SimpleNamespace(kind="case")

    request = EvaluationDatasetCreateRequest(
        name="transaction-order",
        version="v1",
        cases=[
            EvaluationCaseCreateRequest(
                case_key="case-1",
                category="reliability",
                input={"prompt": "safe"},
            )
        ],
    )

    await TestRepository().create_dataset(FakeSession(), user_id="user-1", request=request)

    assert order == ["dataset", "flush", "case", "flush"]
