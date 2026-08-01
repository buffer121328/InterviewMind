"""评测 Reporting 子域用例：总览、趋势、回归告警与报告导出。

同时承载治理指标纯函数，供本模块与 Gate 子域共用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import get_settings
from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from evaluation.reporting import build_run_report, render_run_report_html

from ai.workflows.evaluation.serializers import _case_run, _run
from ai.workflows.evaluation.service import EvaluationUseCaseError


class ReportingUseCasesMixin:
    """Reporting 子域应用用例：聚合指标、趋势点、回归与导出。"""

    async def overview(self, *, user_id: str) -> dict[str, Any]:
        """聚合运行、语义、专项质量、人工队列和效率指标。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows, total = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            calibrations = await self.repository.list_calibrations(
                uow.db, user_id=user_id
            )
            succeeded = [row for row in rows if row.status == "succeeded"]
            runtime = [row for row in rows if row.summary.get("runtime_success")]
            semantic = [row for row in rows if row.summary.get("semantic_success")]
            complete = [row for row in succeeded if row.summary.get("complete_success")]
            hard_passed = [row for row in succeeded if row.summary.get("hard_gate_passed")]
            latest = succeeded[0] if succeeded else None
            runtime_success_rate = _weighted_ratio(
                rows, "runtime_success_count", "completed_count"
            )
            semantic_success_rate = _weighted_ratio(
                rows, "semantic_success_count", "completed_count"
            )
            complete_success_rate = _weighted_ratio(
                rows, "complete_success_count", "completed_count"
            )
            hard_gate_pass_rate = _weighted_success_rate(
                rows,
                failure_key="hard_gate_failure_count",
                total_key="completed_count",
            )
            return {
                "run_count": total,
                "runtime_success_rate": (
                    runtime_success_rate
                    if runtime_success_rate is not None
                    else len(runtime) / total if total else None
                ),
                "semantic_success_rate": (
                    semantic_success_rate
                    if semantic_success_rate is not None
                    else len(semantic) / total if total else None
                ),
                "semantic_evaluated_rate": _weighted_ratio(
                    rows, "semantic_evaluated_count", "completed_count"
                ),
                "complete_success_rate": (
                    complete_success_rate
                    if complete_success_rate is not None
                    else len(complete) / total if total else None
                ),
                "hard_gate_pass_rate": (
                    hard_gate_pass_rate
                    if hard_gate_pass_rate is not None
                    else len(hard_passed) / len(succeeded) if succeeded else None
                ),
                "factual_support_rate": _metric_average(
                    succeeded, ("factual", "support", "faithful")
                ),
                "tool_call_accuracy": _metric_average(
                    succeeded, ("tool", "function_call")
                ),
                "judge_human_agreement": _latest_agreement(calibrations),
                "pending_review_count": sum(
                    int(row.summary.get("needs_review_count") or 0) for row in rows
                ),
                "regression_count": sum(
                    int(row.summary.get("regression_count") or 0) for row in rows
                ),
                "p95_latency_ms": (
                    latest.summary.get("p95_latency_ms") if latest else None
                ),
                "token_delta_percent": (
                    dict(latest.summary.get("baseline_comparison") or {}).get(
                        "token_total_delta_percent"
                    )
                    if latest
                    else None
                ),
                "trace_completeness_rate": _weighted_ratio(
                    rows, "trace_complete_count", "completed_count"
                ),
                "trace_incomplete_count": sum(
                    int(row.summary.get("trace_incomplete_count") or 0) for row in rows
                ),
                "tool_failure_rate": _weighted_ratio(
                    rows,
                    "tool_call_failed_count",
                    "tool_execution_attempt_count",
                    fallback_denominator_key="tool_call_total",
                ),
                "tool_execution_success_rate": _weighted_ratio(
                    rows,
                    "tool_call_completed_count",
                    "tool_execution_attempt_count",
                    fallback_denominator_key="tool_call_total",
                ),
                "tool_blocked_rate": _weighted_ratio(
                    rows, "tool_call_blocked_count", "tool_call_total"
                ),
                "tool_retry_rate": _weighted_ratio(
                    rows,
                    "tool_call_retry_count",
                    "tool_execution_attempt_count",
                ),
                "tool_p95_duration_ms": (
                    latest.summary.get("tool_p95_duration_ms") if latest else None
                ),
                "dependency_failure_rate": _weighted_ratio(
                    rows, "external_io_failed_count", "external_io_total"
                ),
                "external_io_timeout_rate": _weighted_ratio(
                    rows, "external_io_timeout_count", "external_io_total"
                ),
                "retrieval_empty_rate": _weighted_ratio(
                    rows,
                    "retrieval_empty_count",
                    "retrieval_total",
                    fallback_numerator_key="retrieval_empty_case_count",
                    fallback_denominator_key="retrieval_observed_case_count",
                ),
                "retrieval_success_rate": _weighted_ratio(
                    rows, "retrieval_success_count", "retrieval_total"
                ),
                "retrieval_adopted_rate": _weighted_ratio(
                    rows,
                    "retrieval_adopted_count",
                    "retrieval_adopted_observed_count",
                ),
                "memory_search_hit_rate": _weighted_ratio(
                    rows, "memory_search_hit_count", "memory_search_total"
                ),
                "memory_adopted_rate": _weighted_ratio(
                    rows,
                    "memory_adopted_count",
                    "memory_adopted_observed_count",
                ),
                "memory_write_duplication_rate": _weighted_ratio(
                    rows,
                    "memory_write_duplicate_count",
                    "memory_write_observed_count",
                ),
                "external_effect_count": sum(
                    int(row.summary.get("external_effect_total") or 0) for row in rows
                ),
                "external_effect_blocked_count": sum(
                    int(row.summary.get("external_effect_blocked_count") or 0)
                    for row in rows
                ),
                "approval_event_count": sum(
                    int(row.summary.get("approval_event_total") or 0) for row in rows
                ),
                "approval_violation_count": sum(
                    int(row.summary.get("approval_violation_count") or 0)
                    for row in rows
                ),
                "langfuse_reported_case_count": sum(
                    int(row.summary.get("langfuse_reported_case_count") or 0)
                    for row in rows
                ),
                "langfuse_failed_case_count": sum(
                    int(row.summary.get("langfuse_failed_case_count") or 0)
                    for row in rows
                ),
            }

    async def trends(
        self,
        *,
        user_id: str,
        agent_name: str | None = None,
        agent_version: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        model_config_hash: str | None = None,
        dataset_version: str | None = None,
        environment: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> dict[str, Any]:
        """返回按创建时间排序的版本、质量、延迟和 Token 趋势点。"""

        self._ensure_center_enabled()
        created_from = _without_timezone(created_from)
        created_to = _without_timezone(created_to)
        async with UnitOfWork(async_session) as uow:
            rows, _ = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            rows = [
                row
                for row in rows
                if (agent_name is None or row.agent_name == agent_name)
                and (agent_version is None or row.agent_version == agent_version)
                and (prompt_name is None or row.prompt_name == prompt_name)
                and (prompt_version is None or row.prompt_version == prompt_version)
                and (
                    model_config_hash is None
                    or row.model_config_hash == model_config_hash
                )
                and (
                    dataset_version is None
                    or row.dataset_version == dataset_version
                )
                and (environment is None or environment == "evaluation")
                and (created_from is None or row.created_at >= created_from)
                and (created_to is None or row.created_at <= created_to)
            ]
            return {
                "items": [
                    _trend_point(row)
                    for row in reversed(rows)
                ]
            }

    async def regressions(self, *, user_id: str) -> dict[str, Any]:
        """返回已由运行聚合确认的回归告警。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows, _ = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            items = [
                {
                    "run_id": row.id,
                    "baseline_run_id": row.baseline_run_id,
                    "agent_name": row.agent_name,
                    "agent_version": row.agent_version,
                    "prompt_name": row.prompt_name,
                    "prompt_version": row.prompt_version,
                    "model_config_hash": row.model_config_hash,
                    "dataset_version": row.dataset_version,
                    "severity": (
                        "critical"
                        if int(row.summary.get("hard_gate_failure_count") or 0) > 0
                        else row.summary.get("regression_severity", "warning")
                    ),
                    "regression_count": row.summary.get("regression_count", 0),
                    "failed_case_count": row.summary.get("failed_count", 0),
                    "hard_gate_failure_count": row.summary.get(
                        "hard_gate_failure_count", 0
                    ),
                    "hard_gate_blocked": int(
                        row.summary.get("hard_gate_failure_count") or 0
                    )
                    > 0,
                    "metric_deltas": dict(
                        dict(row.summary.get("baseline_comparison") or {}).get(
                            "metric_deltas"
                        )
                        or {}
                    ),
                    "complete_success_rate_delta": dict(
                        row.summary.get("baseline_comparison") or {}
                    ).get("complete_success_rate_delta"),
                    "p95_latency_ms_delta": dict(
                        row.summary.get("baseline_comparison") or {}
                    ).get("p95_latency_ms_delta"),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
                if int(row.summary.get("regression_count") or 0) > 0
            ]
            return {"items": items, "total": len(items)}

    async def export_report(
        self, *, user_id: str, run_id: str, output_format: str
    ) -> dict[str, Any] | str:
        """导出 owner-scoped JSON 或独立 HTML 报告。"""

        self._ensure_center_enabled()
        if output_format not in {"json", "html"}:
            raise EvaluationUseCaseError("报告格式仅支持 json 或 html", 422)
        async with UnitOfWork(async_session) as uow:
            run = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if run is None:
                self._not_found("评测运行不存在或无权访问")
            case_rows = await self.repository.list_case_runs(
                uow.db, run_id=run_id, user_id=user_id
            )
            cases = []
            for row in case_rows:
                item = _case_run(row)
                item["record"] = row.record_sanitized
                cases.append(item)
            report = build_run_report(_run(run), cases)
        if output_format == "html":
            return render_run_report_html(report)
        return report


def _weighted_ratio(
    rows: list[Any],
    numerator_key: str,
    denominator_key: str,
    *,
    fallback_numerator_key: str | None = None,
    fallback_denominator_key: str | None = None,
) -> float | None:
    """按运行计数加权计算比率，并仅对缺少新字段的历史摘要使用兼容键。"""

    numerator = 0
    denominator = 0
    observed = False
    for row in rows:
        summary = row.summary
        if numerator_key in summary:
            row_numerator_key = numerator_key
        elif fallback_numerator_key and fallback_numerator_key in summary:
            row_numerator_key = fallback_numerator_key
        else:
            continue
        row_denominator_key = (
            denominator_key
            if denominator_key in summary
            else fallback_denominator_key or denominator_key
        )
        observed = True
        numerator += int(summary.get(row_numerator_key) or 0)
        denominator += int(summary.get(row_denominator_key) or 0)
    return numerator / denominator if observed and denominator else None


def _weighted_success_rate(
    rows: list[Any], *, failure_key: str, total_key: str
) -> float | None:
    """仅用同时具有新失败计数和总数的运行计算加权成功率。"""

    failures = 0
    total = 0
    observed = False
    for row in rows:
        summary = row.summary
        if failure_key not in summary or total_key not in summary:
            continue
        observed = True
        failures += int(summary.get(failure_key) or 0)
        total += int(summary.get(total_key) or 0)
    return (total - failures) / total if observed and total else None


def _metric_average(rows: list[Any], keywords: tuple[str, ...]) -> float | None:
    """从运行汇总中按指标关键词计算非空均值。"""

    values = [
        float(value)
        for row in rows
        for name, value in dict(row.summary.get("metrics") or {}).items()
        if value is not None and any(keyword in name.lower() for keyword in keywords)
    ]
    return sum(values) / len(values) if values else None


def _latest_agreement(rows: list[Any]) -> float | None:
    """优先返回最近 Calibration 的 Weighted Kappa，其次 Spearman/Pearson。"""

    for row in rows:
        statistics = dict(row.statistics or {})
        for name in ("weighted_kappa", "spearman", "pearson", "exact_agreement"):
            value = statistics.get(name)
            if value is not None:
                return float(value)
    return None


def _passes_threshold(value: Any, config: Any) -> bool:
    """兼容旧 float 阈值与带比较方向的新阈值对象。"""

    actual = float(value)
    if isinstance(config, dict):
        threshold = float(config.get("value"))
        comparison = str(config.get("comparison") or "gte")
    else:
        threshold = float(config)
        comparison = "gte"
    if comparison == "lte":
        return actual <= threshold
    if comparison == "eq":
        return actual == threshold
    return actual >= threshold


def _is_unacceptable_regression(delta: Any, config: Any) -> bool:
    """判断相对基线的指标变化是否超出方向化容忍度。"""

    actual_delta = float(delta)
    if isinstance(config, dict):
        tolerance = abs(float(config.get("value")))
        comparison = str(config.get("comparison") or "gte")
    else:
        tolerance = abs(float(config))
        comparison = "gte"
    if comparison == "lte":
        return actual_delta > tolerance
    if comparison == "eq":
        return abs(actual_delta) > tolerance
    return actual_delta < -tolerance


def _trend_point(row: Any) -> dict[str, Any]:
    """把一次运行转换为可筛选、可绘图的版本趋势点。"""

    metrics = [
        float(value)
        for value in dict(row.summary.get("metrics") or {}).values()
        if value is not None
    ]
    average_score = sum(metrics) / len(metrics) if metrics else None
    minimum_score = min(metrics) if metrics else None
    score_spread = max(metrics) - min(metrics) if metrics else None
    return {
        "run_id": row.id,
        "created_at": row.created_at.isoformat(),
        "environment": "evaluation",
        "agent_name": row.agent_name,
        "agent_version": row.agent_version,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "model_config_hash": row.model_config_hash,
        "dataset_version": row.dataset_version,
        "average_score": average_score,
        "minimum_score": minimum_score,
        "score_spread": score_spread,
        "sample_count": int(row.summary.get("completed_count") or 0),
        "complete_success_rate": row.summary.get("complete_success_rate"),
        "p50_latency_ms": row.summary.get("p50_latency_ms"),
        "p95_latency_ms": row.summary.get("p95_latency_ms"),
        "token_total": row.summary.get("token_total"),
        "p50_tokens": row.summary.get("p50_tokens"),
        "p95_tokens": row.summary.get("p95_tokens"),
    }


def _without_timezone(value: datetime | None) -> datetime | None:
    """数据库当前使用 naive datetime，查询过滤时统一去掉时区信息。"""

    return value.replace(tzinfo=None) if value and value.tzinfo else value
