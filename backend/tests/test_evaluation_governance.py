"""评测报告、线上抽样、方向化门禁和 Prompt 发布治理测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.workflows.evaluation.service import (
    EvaluationUseCaseError,
    _latest_agreement,
    _metric_average,
    _is_unacceptable_regression,
    _passes_threshold,
    _trend_point,
)
from app.db.models.evaluation import EvaluationAnnotationModel
from app.schemas.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationGatePolicyCreateRequest,
)
from evaluation.online import sampling_decision, sanitize_production_trace
from evaluation.reporting import build_run_report, render_run_report_html


@pytest.mark.fast
def test_directional_gate_thresholds_cover_mae_and_zero_tolerance() -> None:
    """门禁必须支持越大越好、越小越好和零容忍指标。"""

    assert _passes_threshold(0.9, {"value": 0.8, "comparison": "gte"})
    assert _passes_threshold(0.05, {"value": 0.1, "comparison": "lte"})
    assert _passes_threshold(0, {"value": 0, "comparison": "eq"})
    assert _is_unacceptable_regression(-0.03, {"value": 0.02, "comparison": "gte"})
    assert _is_unacceptable_regression(0.03, {"value": 0.02, "comparison": "lte"})


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
