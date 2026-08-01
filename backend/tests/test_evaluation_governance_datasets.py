"""案例分类、候选数据集、评测报告、线上抽样与 Prompt 发布治理测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.workflows.evaluation.service import EvaluationUseCaseError
from app.db.repositories.evaluation.repository import (
    EvaluationRepository,
    _candidate_governance_metadata,
)
from app.db.models.evaluation import EvaluationAnnotationModel
from app.schemas.evaluations import (
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

    from app.db.repositories.evaluation import repository as repository_module

    repository = EvaluationRepository()
    case_run = SimpleNamespace(
        id="case-run-1",
        case_id="case-1",
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

    monkeypatch.setattr(repository_module, "encrypt_payload", lambda value: value)
    stored = repository._case_model("dataset-1", candidate)
    assert stored.expected_encrypted["evidence_refs"] == candidate.evidence_refs


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
def test_evaluation_router_exposes_report_candidate_and_online_governance() -> None:
    """闭环 API 必须包含报告、失败沉淀与线上抽样入口。"""

    from app.api.evaluations import router

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
