"""Evaluation Run 的确定性 JSON/HTML 报告生成器。"""

from __future__ import annotations

from collections import defaultdict
from html import escape
from statistics import median
from typing import Any, Iterable


def _percentile(values: list[float], percentile: float) -> float | None:
    """使用线性插值计算小样本也稳定的百分位数。"""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def build_run_report(run: dict[str, Any], cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """汇总 all-pass@N、延迟、Token、硬门禁与恢复指标。"""

    rows = list(cases)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("case_id"))].append(row)
    all_pass_groups = [
        all(
            _case_complete_success(item)
            for item in group
        )
        for group in grouped.values()
    ]
    latencies = [float(row.get("latency_ms") or 0) for row in rows]
    token_totals = [
        float((row.get("token_usage") or {}).get("total_tokens") or 0)
        for row in rows
    ]
    records = [row.get("record") or {} for row in rows]
    retry_count = sum(int(record.get("retry_count") or 0) for record in records)
    recovery_count = sum(int(record.get("recovery_count") or 0) for record in records)
    fallback_count = sum(
        sum(
            1
            for call in record.get("model_calls") or []
            if int(call.get("fallback_index") or 0) > 0
        )
        for record in records
    )
    hard_gate_failure_count = sum(
        row.get("hard_gate_passed") is False for row in rows
    )
    run_summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    return {
        "schema_version": "1",
        "run": run,
        "metrics": {
            "case_run_count": len(rows),
            "unique_case_count": len(grouped),
            "all_pass_at_n": (
                sum(all_pass_groups) / len(all_pass_groups)
                if all_pass_groups
                else None
            ),
            "hard_gate_failure_count": hard_gate_failure_count,
            "p50_latency_ms": median(latencies) if latencies else None,
            "p95_latency_ms": _percentile(latencies, 0.95),
            "token_total": sum(token_totals),
            "p50_tokens": median(token_totals) if token_totals else None,
            "p95_tokens": _percentile(token_totals, 0.95),
            "retry_count": retry_count,
            "recovery_count": recovery_count,
            "fallback_count": fallback_count,
            "needs_review_count": sum(bool(row.get("needs_review")) for row in rows),
            "runtime_success_rate": run_summary.get("runtime_success_rate"),
            "semantic_evaluated_rate": run_summary.get("semantic_evaluated_rate"),
            "semantic_success_rate": run_summary.get("semantic_success_rate"),
            "complete_success_rate": run_summary.get("complete_success_rate"),
            "trace_completeness_rate": run_summary.get("trace_completeness_rate"),
            "tool_execution_success_rate": run_summary.get(
                "tool_execution_success_rate"
            ),
            "tool_failure_rate": run_summary.get("tool_failure_rate"),
            "tool_blocked_rate": run_summary.get("tool_blocked_rate"),
            "tool_retry_rate": run_summary.get("tool_retry_rate"),
            "tool_p95_duration_ms": run_summary.get("tool_p95_duration_ms"),
            "dependency_failure_rate": run_summary.get("dependency_failure_rate"),
            "external_io_timeout_rate": run_summary.get(
                "external_io_timeout_rate"
            ),
            "retrieval_success_rate": run_summary.get("retrieval_success_rate"),
            "retrieval_empty_rate": run_summary.get("retrieval_empty_rate"),
            "retrieval_adopted_rate": run_summary.get("retrieval_adopted_rate"),
            "memory_search_hit_rate": run_summary.get("memory_search_hit_rate"),
            "memory_adopted_rate": run_summary.get("memory_adopted_rate"),
            "memory_write_duplication_rate": run_summary.get(
                "memory_write_duplication_rate"
            ),
        },
        "cases": rows,
    }


def _case_complete_success(row: dict[str, Any]) -> bool:
    """优先读取新 outcome；历史记录退回业务终态与硬门禁兼容判断。"""

    record = row.get("record")
    if isinstance(record, dict):
        outcome = record.get("outcome")
        if isinstance(outcome, dict) and isinstance(outcome.get("complete_success"), bool):
            return bool(outcome["complete_success"])
    return row.get("status") == "succeeded" and row.get("hard_gate_passed") is True


def render_run_report_html(report: dict[str, Any]) -> str:
    """把安全 JSON 报告渲染为无脚本、可下载的独立 HTML。"""

    run = report.get("run") or {}
    metrics = report.get("metrics") or {}
    case_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row.get('case_id') or ''))}</td>"
        f"<td>{escape(str(row.get('status') or ''))}</td>"
        f"<td>{escape(str(row.get('hard_gate_passed')))}</td>"
        f"<td>{escape(str(row.get('latency_ms') or 0))}</td>"
        f"<td>{escape(str(row.get('overall_score')))}</td>"
        "</tr>"
        for row in report.get("cases") or []
    )
    metric_rows = "".join(
        f"<tr><th>{escape(str(name))}</th><td>{escape(str(value))}</td></tr>"
        for name, value in metrics.items()
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Evaluation Report</title>
<style>body{{font-family:system-ui;margin:32px;color:#172033}}table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{border:1px solid #d8dee9;padding:8px;text-align:left}}th{{background:#f5f7fa}}h1,h2{{color:#172033}}</style></head>
<body><h1>Agent 评测报告</h1><p>Run: {escape(str(run.get('id') or ''))} · Agent: {escape(str(run.get('agent_name') or ''))}</p>
<h2>汇总</h2><table>{metric_rows}</table>
<h2>案例</h2><table><thead><tr><th>Case</th><th>Status</th><th>Hard Gate</th><th>Latency (ms)</th><th>Semantic quality (0-1)</th></tr></thead><tbody>{case_rows}</tbody></table>
</body></html>"""
