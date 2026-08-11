"""提供后端逻辑相关后端功能。"""

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any


def _runtime_percentile(values: Sequence[int], fraction: float) -> int | None:
    """使用最近秩计算运行时事件的小样本百分位。"""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def _terminal_runtime_events(
    events: Sequence[Mapping[str, Any]],
    *,
    prefix: str,
) -> dict[str, Mapping[str, Any]]:
    """按 call ID 保留最后一个终态，避免重试事件被重复计算为多个调用。"""

    terminal_statuses = {"completed", "failed", "blocked", "skipped"}
    terminals: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if not str(event.get("event_type") or "").startswith(prefix):
            continue
        if event.get("status") not in terminal_statuses:
            continue
        call_id = str(event.get("call_id") or event.get("event_id") or "")
        if call_id:
            terminals[call_id] = event
    return terminals


def summarize_tool_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """按逻辑 Tool 调用汇总终态、审批风险、耗时和不完整调用。"""

    tool_events = [
        event
        for event in events
        if str(event.get("event_type") or "").startswith("tool.")
    ]
    call_ids = {str(event.get("call_id")) for event in tool_events if event.get("call_id")}
    terminals = _terminal_runtime_events(tool_events, prefix="tool.")
    durations = [
        int(event["duration_ms"])
        for event in terminals.values()
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    slowest = max(
        (
            event
            for event in terminals.values()
            if isinstance(event.get("duration_ms"), (int, float))
        ),
        key=lambda event: int(event.get("duration_ms") or 0),
        default=None,
    )
    return {
        "total": len(call_ids),
        "completed": sum(event.get("status") == "completed" for event in terminals.values()),
        "failed": sum(event.get("status") == "failed" for event in terminals.values()),
        "blocked": sum(event.get("status") == "blocked" for event in terminals.values()),
        "skipped": sum(event.get("status") == "skipped" for event in terminals.values()),
        "incomplete": max(0, len(call_ids) - len(terminals)),
        "approval_required": len(
            {
                str(event.get("call_id"))
                for event in tool_events
                if event.get("requires_confirmation")
            }
        ),
        "external_effect_count": len(
            {
                str(event.get("call_id"))
                for event in tool_events
                if event.get("tool_effect") == "external"
            }
        ),
        "p50_duration_ms": _runtime_percentile(durations, 0.50),
        "p95_duration_ms": _runtime_percentile(durations, 0.95),
        "slowest_tool": slowest.get("tool_name") if slowest else None,
    }


def summarize_external_io_events(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """汇总外部依赖调用的终态、超时和耗时。"""

    io_events = [
        event
        for event in events
        if str(event.get("event_type") or "").startswith("external_io.")
    ]
    call_ids = {str(event.get("call_id")) for event in io_events if event.get("call_id")}
    terminals = _terminal_runtime_events(io_events, prefix="external_io.")
    durations = [
        int(event["duration_ms"])
        for event in terminals.values()
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    return {
        "total": len(call_ids),
        "completed": sum(event.get("status") == "completed" for event in terminals.values()),
        "failed": sum(event.get("status") == "failed" for event in terminals.values()),
        "skipped": sum(event.get("status") == "skipped" for event in terminals.values()),
        "incomplete": max(0, len(call_ids) - len(terminals)),
        "timeout": sum(
            event.get("error_category") == "external_io_timeout"
            for event in terminals.values()
        ),
        "p50_duration_ms": _runtime_percentile(durations, 0.50),
        "p95_duration_ms": _runtime_percentile(durations, 0.95),
    }


def summarize_approval_events(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """汇总审批请求和决定，不暴露审批人身份。"""

    approval_events = [
        event
        for event in events
        if str(event.get("event_type") or "").startswith("approval.")
    ]
    return {
        "requested": sum(event.get("status") == "pending" for event in approval_events),
        "approved": sum(event.get("status") == "approved" for event in approval_events),
        "rejected": sum(event.get("status") == "rejected" for event in approval_events),
    }


def summarize_model_events(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 Agent 汇总 P50/P95、超时率、重试率和 fallback 率。"""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("agent_name") or "unknown"), []).append(event)

    def percentile(values: list[int], fraction: float) -> int | None:
        """使用最近秩计算小样本可解释百分位。"""
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, ceil(len(ordered) * fraction) - 1))
        return ordered[index]

    summaries: dict[str, dict[str, Any]] = {}
    for agent_name, agent_events in grouped.items():
        started = [item for item in agent_events if item.get("event_type") == "llm.request.started"]
        terminal = [
            item
            for item in agent_events
            if item.get("event_type") in {
                "llm.request.completed",
                "llm.request.failed",
                "llm.request.skipped",
            }
        ]
        durations = [
            int(item["model_duration_ms"])
            for item in terminal
            if isinstance(item.get("model_duration_ms"), (int, float))
        ]
        timeout_count = sum(item.get("failure_type") == "timeout" for item in terminal)
        retry_count = sum(int(item.get("attempt") or 1) > 1 for item in started)
        fallback_count = sum(int(item.get("fallback_index") or 0) > 0 for item in started)
        denominator = max(1, len(started))
        summaries[agent_name] = {
            "call_count": len(started),
            "completed_count": sum(item.get("event_type") == "llm.request.completed" for item in terminal),
            "failed_count": sum(item.get("event_type") != "llm.request.completed" for item in terminal),
            "p50_model_duration_ms": percentile(durations, 0.50),
            "p95_model_duration_ms": percentile(durations, 0.95),
            "timeout_rate": min(timeout_count, denominator) / denominator,
            "retry_rate": retry_count / denominator,
            "fallback_rate": fallback_count / denominator,
        }
    return summaries


def summarize_governance_window(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """汇总治理窗口相关后端逻辑。"""
    started = [event for event in events if event.get("event_type") == "llm.request.started"]
    terminal = [
        event
        for event in events
        if event.get("event_type") in {
            "llm.request.completed",
            "llm.request.failed",
            "llm.request.skipped",
        }
    ]
    durations = sorted(
        int(event["total_duration_ms"])
        for event in terminal
        if isinstance(event.get("total_duration_ms"), (int, float))
    )
    p95_index = max(0, min(len(durations) - 1, ceil(len(durations) * 0.95) - 1))
    denominator = max(1, len(started))
    audited_count = sum(
        isinstance(event.get("input_chars"), (int, float))
        and isinstance(event.get("input_fingerprint"), str)
        and isinstance(event.get("source_breakdown"), Mapping)
        for event in started
    )
    forbidden_fields = {
        "api_key",
        "authorization",
        "cookie",
        "job_description",
        "memory",
        "prompt",
        "resume",
        "token",
        "user_answer",
    }
    return {
        "call_count": len(started),
        "p95_total_duration_ms": durations[p95_index] if durations else None,
        "timeout_rate": sum(
            event.get("failure_type") == "timeout"
            or event.get("error_category") == "external_io_timeout"
            for event in terminal
        ) / denominator,
        "average_fallback_count": sum(
            int(event.get("fallback_index") or 0) > 0
            for event in started
        ) / denominator,
        "context_audit_coverage": audited_count / denominator,
        "unsafe_field_count": sum(
            bool(forbidden_fields.intersection(event))
            for event in events
        ),
    }


def compare_governance_windows(
    baseline_events: Sequence[Mapping[str, Any]],
    current_events: Sequence[Mapping[str, Any]],
    *,
    voice_baseline_chars: int,
    voice_current_chars: int,
    resume_baseline_chars: int,
    resume_current_chars: int,
) -> dict[str, Any]:
    """比较治理窗口相关后端逻辑。"""
    baseline = summarize_governance_window(baseline_events)
    current = summarize_governance_window(current_events)

    def reduction(before: int | float | None, after: int | float | None) -> float:
        """处理归约相关后端逻辑。"""
        before_value = float(before or 0)
        after_value = float(after or 0)
        if before_value <= 0:
            return 1.0 if after_value <= 0 else -1.0
        return (before_value - after_value) / before_value

    improvements = {
        "p95_total_duration_reduction": reduction(
            baseline["p95_total_duration_ms"],
            current["p95_total_duration_ms"],
        ),
        "timeout_rate_reduction": reduction(
            baseline["timeout_rate"],
            current["timeout_rate"],
        ),
        "average_fallback_reduction": reduction(
            baseline["average_fallback_count"],
            current["average_fallback_count"],
        ),
        "voice_context_reduction": reduction(
            voice_baseline_chars,
            voice_current_chars,
        ),
        "resume_repeated_input_reduction": reduction(
            resume_baseline_chars,
            resume_current_chars,
        ),
    }
    targets = {
        "p95_total_duration": improvements["p95_total_duration_reduction"] >= 0.30,
        "timeout_rate": improvements["timeout_rate_reduction"] >= 0.70,
        "average_fallback_count": improvements["average_fallback_reduction"] >= 0.50,
        "voice_context": improvements["voice_context_reduction"] >= 0.60,
        "resume_repeated_input": improvements["resume_repeated_input_reduction"] >= 0.50,
        "context_audit_coverage": current["context_audit_coverage"] == 1.0,
        "sensitive_event_fields": current["unsafe_field_count"] == 0,
    }
    return {
        "baseline": baseline,
        "current": current,
        "improvements": improvements,
        "targets": targets,
        "passed": all(targets.values()),
    }
