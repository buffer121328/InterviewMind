"""Shared immutable baseline comparison for evaluation-run summaries."""

from __future__ import annotations

from typing import Any

from evaluation.metrics import metric_delta_is_regression


def build_baseline_comparison(
    *,
    current_summary: dict[str, Any],
    current_dataset_version: str,
    current_agent_name: str,
    current_model_config_hash: str,
    baseline_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare a current aggregate to a compatible immutable baseline."""

    reasons: list[str] = []
    if baseline_snapshot.get("dataset_version") != current_dataset_version:
        reasons.append("dataset_version_mismatch")
    if baseline_snapshot.get("agent_name") != current_agent_name:
        reasons.append("agent_name_mismatch")
    result: dict[str, Any] = {
        "comparable": not reasons,
        "incomparable_reasons": reasons,
        "baseline_run_id": baseline_snapshot.get("run_id"),
        "current_model_config_hash": current_model_config_hash,
        "baseline_model_config_hash": baseline_snapshot.get("model_config_hash"),
    }
    if reasons:
        result["regression_count"] = 0
        return result

    baseline_summary = dict(baseline_snapshot.get("summary") or {})
    baseline_metrics = dict(baseline_summary.get("metrics") or {})
    current_metrics = dict(current_summary.get("metrics") or {})
    metric_deltas = {
        name: float(current_metrics[name]) - float(value)
        for name, value in baseline_metrics.items()
        if name in current_metrics and value is not None
    }
    complete_delta = (
        float(current_summary["complete_success_rate"])
        - float(baseline_summary.get("complete_success_rate") or 0)
        if current_summary.get("complete_success_rate") is not None
        else None
    )
    latency_delta = (
        float(current_summary["p95_latency_ms"])
        - float(baseline_summary.get("p95_latency_ms") or 0)
        if current_summary.get("p95_latency_ms") is not None
        else None
    )
    baseline_tokens = float(baseline_summary.get("token_total") or 0)
    token_delta = (
        (float(current_summary.get("token_total") or 0) - baseline_tokens)
        / baseline_tokens
        if baseline_tokens > 0
        else None
    )
    regression_count = sum(
        metric_delta_is_regression(name, delta)
        for name, delta in metric_deltas.items()
    )
    regression_count += complete_delta is not None and complete_delta < 0
    result.update(
        {
            "metric_deltas": metric_deltas,
            "complete_success_rate_delta": complete_delta,
            "p95_latency_ms_delta": latency_delta,
            "token_total_delta_percent": token_delta,
            "regression_count": int(regression_count),
        }
    )
    return result

