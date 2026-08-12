"""评测门禁阈值、owner 作用域服务用例与 Gate 结果持久化治理测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai.workflows.evaluation.analytics import (
    _is_unacceptable_regression,
    _latest_agreement,
    _metric_average,
    _passes_threshold,
    _trend_point,
    _weighted_success_rate,
)
from ai.workflows.evaluation.contracts import EvaluationUseCaseError
from app.schemas.evaluations import EvaluationGatePolicyCreateRequest


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
