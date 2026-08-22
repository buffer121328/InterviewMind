"""评测报告与门禁共用的纯统计辅助函数。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


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
        threshold_value = config.get("value")
        if threshold_value is None:
            return False
        threshold = float(threshold_value)
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
        tolerance_value = config.get("value")
        if tolerance_value is None:
            return True
        tolerance = abs(float(tolerance_value))
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
