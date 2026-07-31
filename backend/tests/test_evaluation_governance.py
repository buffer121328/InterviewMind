"""评测报告、线上抽样、方向化门禁和 Prompt 发布治理测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.workflows.evaluation.service import (
    EvaluationUseCaseError,
    _latest_agreement,
    _metric_average,
    _is_unacceptable_regression,
    _passes_threshold,
    _trend_point,
    _weighted_success_rate,
)
from app.db.repositories.evaluation.repository import (
    EvaluationRepository,
    _candidate_governance_metadata,
)
from app.db.models.evaluation import EvaluationAnnotationModel
from app.schemas.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationCandidateDatasetRequest,
    EvaluationCaseCreateRequest,
    EvaluationGatePolicyCreateRequest,
)
from evaluation.online import sampling_decision, sanitize_production_trace
from evaluation.outcomes import classify_case_outcome
from evaluation.reporting import build_run_report, render_run_report_html
from evaluation.runners import AgentEvalRunner, EvaluationCaseSpec
from evaluation.schemas import EvalObservabilitySummary, EvalTraceCompleteness, ScoreSource


@pytest.mark.fast
def test_directional_gate_thresholds_cover_mae_and_zero_tolerance() -> None:
    """门禁必须支持越大越好、越小越好和零容忍指标。"""

    assert _passes_threshold(0.9, {"value": 0.8, "comparison": "gte"})
    assert _passes_threshold(0.05, {"value": 0.1, "comparison": "lte"})
    assert _passes_threshold(0, {"value": 0, "comparison": "eq"})
    assert _is_unacceptable_regression(-0.03, {"value": 0.02, "comparison": "gte"})
    assert _is_unacceptable_regression(0.03, {"value": 0.02, "comparison": "lte"})


@pytest.mark.fast
def test_weighted_success_rate_ignores_legacy_rows_without_failure_counts() -> None:
    """历史摘要缺少新失败计数时应回退旧口径，不能被误算为零失败样本。"""

    rows = [
        SimpleNamespace(
            summary={"completed_count": 2, "hard_gate_failure_count": 1}
        ),
        SimpleNamespace(summary={"completed_count": 10, "hard_gate_passed": True}),
    ]

    assert _weighted_success_rate(
        rows,
        failure_key="hard_gate_failure_count",
        total_key="completed_count",
    ) == pytest.approx(0.5)


@pytest.mark.fast
def test_overview_and_trend_helpers_keep_quality_sources_observable() -> None:
    """总览与趋势必须暴露专项质量、样本、波动、延迟和 Token。"""

    run = SimpleNamespace(
        id="run-1",
        created_at=datetime(2026, 7, 30, 9, 0, 0),
        agent_name="interview_planner",
        agent_version="v2",
        prompt_name="interview-plan",
        prompt_version="7",
        model_config_hash="sha256:model",
        dataset_version="locked-v3",
        summary={
            "metrics": {
                "factual.support": 0.9,
                "tool.name_and_key_parameter_accuracy": 0.8,
            },
            "completed_count": 20,
            "complete_success_rate": 0.75,
            "p50_latency_ms": 100,
            "p95_latency_ms": 300,
            "token_total": 4000,
            "p50_tokens": 180,
            "p95_tokens": 260,
        },
    )

    assert _metric_average([run], ("factual",)) == pytest.approx(0.9)
    point = _trend_point(run)
    assert point["sample_count"] == 20
    assert point["average_score"] == pytest.approx(0.85)
    assert point["minimum_score"] == pytest.approx(0.8)
    assert point["score_spread"] == pytest.approx(0.1)
    assert point["p95_latency_ms"] == 300
    assert point["p95_tokens"] == 260

    calibration = SimpleNamespace(
        statistics={"weighted_kappa": 0.82, "spearman": 0.91}
    )
    assert _latest_agreement([calibration]) == pytest.approx(0.82)


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


@pytest.mark.asyncio
async def test_case_run_filters_are_owner_scoped_and_use_only_sanitized_tool_calls(
    monkeypatch,
) -> None:
    """案例筛选必须先校验 owner，且工具名只能读取脱敏 record 的结构化字段。"""

    from ai.workflows.evaluation import service as service_module

    class FakeUnitOfWork:
        """提供 service 测试所需的最小异步 UoW。"""

        def __init__(self, _factory) -> None:
            self.db = object()

        async def __aenter__(self):
            """进入无持久化副作用的测试事务。"""

            return self

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            """结束测试事务且不吞异常。"""

            return False

    rows = [
        SimpleNamespace(
            id="case-run-1",
            evaluation_run_id="run-1",
            case_id="case-1",
            repetition_index=0,
            status="failed",
            trace_id="trace-1",
            latency_ms=10,
            token_usage={},
            hard_gate_passed=False,
            overall_score=0.2,
            error_category="dependency_failure",
            needs_review=True,
            record_sanitized={
                "tool_calls": [{
                    "tool_name": "search_question_bank",
                    "effect": "external",
                    "status": "blocked",
                    "approval_status": "pending",
                }],
                "approvals": [{"status": "pending"}],
                "retrievals": [{"empty_result": True, "result_count": 0}],
                "observability": {
                    "trace_completeness": {"complete": False}
                },
                "input_summary": {"query": "redacted"},
            },
        ),
        SimpleNamespace(
            id="case-run-2",
            evaluation_run_id="run-1",
            case_id="case-2",
            repetition_index=0,
            status="failed",
            trace_id="trace-2",
            latency_ms=20,
            token_usage={},
            hard_gate_passed=False,
            overall_score=0.3,
            error_category="dependency_failure",
            needs_review=True,
            record_sanitized={
                "tool_calls": [],
                "arguments_summary": {"tool_name": "search_question_bank"},
            },
        ),
    ]
    repository = SimpleNamespace(
        get_run=AsyncMock(side_effect=lambda _db, *, run_id, user_id: (
            SimpleNamespace(id=run_id) if user_id == "owner-a" else None
        )),
        list_case_runs=AsyncMock(return_value=rows),
    )
    monkeypatch.setattr(service_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(
        service_module.EvaluationUseCases,
        "_ensure_center_enabled",
        lambda _self: None,
    )
    use_cases = service_module.EvaluationUseCases(repository=repository)

    result = await use_cases.list_case_runs(
        user_id="owner-a",
        run_id="run-1",
        status="failed",
        error_category="dependency_failure",
        tool_name="search_question_bank",
        tool_effect="external",
        tool_status="blocked",
        approval_status="pending",
        has_external_side_effect=True,
        trace_incomplete=True,
        retrieval_empty=True,
        needs_review=True,
        hard_gate_passed=False,
    )

    assert result["total"] == 1
    assert result["items"][0]["id"] == "case-run-1"
    assert "record_sanitized" not in result["items"][0]
    repository.list_case_runs.assert_awaited_once_with(
        repository.list_case_runs.await_args.args[0],
        run_id="run-1",
        user_id="owner-a",
    )

    with pytest.raises(EvaluationUseCaseError) as exc_info:
        await use_cases.list_case_runs(user_id="owner-b", run_id="run-1")
    assert exc_info.value.status_code == 404
    assert repository.list_case_runs.await_count == 1


@pytest.mark.asyncio
async def test_overview_governance_rates_are_owner_scoped_and_weighted(monkeypatch) -> None:
    """总览治理指标使用当前 owner 的运行计数加权，空分母保持无数据语义。"""

    from ai.workflows.evaluation import service as service_module

    class FakeUnitOfWork:
        """提供 overview 测试所需的最小异步 UoW。"""

        def __init__(self, _factory) -> None:
            self.db = object()

        async def __aenter__(self):
            """进入无持久化副作用的测试事务。"""

            return self

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            """结束测试事务且不吞异常。"""

            return False

    rows = [
        SimpleNamespace(
            status="succeeded",
            summary={
                "runtime_success": True,
                "semantic_success": True,
                "complete_success": True,
                "hard_gate_passed": True,
                "completed_count": 2,
                "trace_complete_count": 1,
                "trace_incomplete_count": 1,
                "tool_call_total": 4,
                "tool_call_completed_count": 3,
                "tool_call_failed_count": 1,
                "tool_p95_duration_ms": 50,
                "external_effect_total": 2,
                "external_effect_blocked_count": 1,
                "approval_violation_count": 1,
                "external_io_total": 2,
                "external_io_failed_count": 1,
                "external_io_timeout_count": 1,
                "approval_event_total": 2,
                "retrieval_observed_case_count": 2,
                "retrieval_empty_case_count": 1,
                "langfuse_reported_case_count": 1,
                "langfuse_failed_case_count": 1,
                "metrics": {},
            },
        ),
        SimpleNamespace(
            status="failed",
            summary={
                "runtime_success": False,
                "semantic_success": False,
                "completed_count": 1,
                "trace_complete_count": 1,
                "trace_incomplete_count": 0,
                "tool_call_total": 0,
                "tool_call_completed_count": 0,
                "tool_call_failed_count": 0,
                "external_io_total": 0,
                "external_io_failed_count": 0,
                "approval_event_total": 1,
                "metrics": {},
            },
        ),
    ]
    repository = SimpleNamespace(
        list_runs=AsyncMock(return_value=(rows, 2)),
        list_calibrations=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(service_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(
        service_module.EvaluationUseCases,
        "_ensure_center_enabled",
        lambda _self: None,
    )
    use_cases = service_module.EvaluationUseCases(repository=repository)

    overview = await use_cases.overview(user_id="owner-a")

    assert overview["trace_completeness_rate"] == pytest.approx(2 / 3)
    assert overview["trace_incomplete_count"] == 1
    assert overview["tool_failure_rate"] == pytest.approx(0.25)
    assert overview["tool_execution_success_rate"] == pytest.approx(0.75)
    assert overview["tool_p95_duration_ms"] == 50
    assert overview["dependency_failure_rate"] == pytest.approx(0.5)
    assert overview["external_io_timeout_rate"] == pytest.approx(0.5)
    assert overview["retrieval_empty_rate"] == pytest.approx(0.5)
    assert overview["external_effect_count"] == 2
    assert overview["external_effect_blocked_count"] == 1
    assert overview["approval_event_count"] == 3
    assert overview["approval_violation_count"] == 1
    assert overview["langfuse_reported_case_count"] == 1
    assert overview["langfuse_failed_case_count"] == 1
    repository.list_runs.assert_awaited_once_with(
        repository.list_runs.await_args.args[0],
        user_id="owner-a",
        limit=500,
        offset=0,
    )


@pytest.mark.asyncio
async def test_gate_result_persists_hard_gate_evidence_refs(monkeypatch) -> None:
    """发布门禁的不可变结果必须保留失败硬门禁对应的安全 evidence refs。"""

    from ai.workflows.evaluation import service as service_module

    class FakeUnitOfWork:
        """为 Gate 检查提供无持久化副作用的异步事务边界。"""

        def __init__(self, _factory) -> None:
            self.db = object()

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    run = SimpleNamespace(
        id="run-1",
        suite_id="suite-1",
        summary={
            "completed_count": 1,
            "hard_gate_failure_count": 1,
            "metrics": {},
            "hard_gates": {
                "hard_gate.unapproved_external_action": False,
            },
            "hard_gate_evidence": {
                "hard_gate.unapproved_external_action": [
                    "tool-call:call-1:approval"
                ],
            },
        },
    )
    policy = SimpleNamespace(
        id="policy-1",
        minimum_sample_size=1,
        metric_thresholds={},
        regression_tolerances={},
        hard_gates=["hard_gate.unapproved_external_action"],
    )

    async def save_gate_result(_db, **kwargs):
        """返回与 Repository 不可变写入相同形状的测试结果。"""

        return SimpleNamespace(
            id="gate-result-1",
            passed=kwargs["passed"],
            blocked_by=kwargs["blocked_by"],
            details=kwargs["details"],
        )

    repository = SimpleNamespace(
        get_run=AsyncMock(return_value=run),
        get_suite=AsyncMock(
            return_value=SimpleNamespace(gate_policy_id="policy-1")
        ),
        get_gate_policy=AsyncMock(return_value=policy),
        save_gate_result=AsyncMock(side_effect=save_gate_result),
    )
    monkeypatch.setattr(service_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(
        service_module.EvaluationUseCases,
        "_ensure_center_enabled",
        lambda _self: None,
    )

    result = await service_module.EvaluationUseCases(
        repository=repository
    ).gate_check(user_id="owner-1", run_id="run-1")

    assert result["passed"] is False
    assert "hard_gate.unapproved_external_action" in result["blocked_by"]
    assert result["details"]["hard_gate_evidence"] == {
        "hard_gate.unapproved_external_action": ["tool-call:call-1:approval"]
    }


@pytest.mark.fast
def test_gate_policy_schema_accepts_directional_and_legacy_thresholds() -> None:
    """现有 float 策略保持兼容，新策略可声明比较方向。"""

    request = EvaluationGatePolicyCreateRequest(
        name="production",
        version="v1",
        metric_thresholds={
            "quality": 0.8,
            "mae": {"value": 0.1, "comparison": "lte"},
        },
    )

    assert request.metric_thresholds["quality"] == 0.8
    assert request.metric_thresholds["mae"].comparison == "lte"  # type: ignore[union-attr]


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
