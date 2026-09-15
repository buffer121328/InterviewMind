"""模型指标事件的聚合、序列化与性能查询。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.clock import utc_isoformat, utc_now
from app.db.models import AgentRunModel, ModelMetricEventModel, async_session


_PERFORMANCE_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def _number(value: Any) -> float:
    """把数值类型的值安全转为 float，其他类型返回 0.0。

    Args:
        value: 待转换的值。
    """
    return float(value) if isinstance(value, (int, float)) else 0.0


def _nonnegative_number(value: Any) -> float | None:
    """返回已上报的非负数值；缺失值不伪造成零。

    Args:
        value: 值。
    """

    if not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if normalized >= 0 else None


def _percentile(values: list[float], percentile: float) -> float | None:
    """按最近邻法计算有序样本的百分位数；空样本返回 None。

    Args:
        values: 样本值列表。
        percentile: 目标百分位（0~1）。
    """
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, ceil(percentile * len(ordered)) - 1))]


def summarize_model_metric_events(
    events: Iterable[dict[str, Any]], *, run_statuses: Iterable[str] = ()
) -> dict[str, Any]:
    """聚合模型指标事件，产出吞吐、时延、降级与上下文截断等汇总。

    Args:
        events: 模型指标事件 payload 字典序列。
        run_statuses: 关联 AgentRun 的状态序列，用于计算运行成功率。
    """
    rows = list(events)
    started = [row for row in rows if row.get("event_type") == "llm.request.started"]
    completed = [row for row in rows if row.get("event_type") == "llm.request.completed"]
    terminal = [row for row in rows if row.get("event_type") in {"llm.request.completed", "llm.request.failed"}]
    logical = [row for row in started if int(row.get("attempt") or 1) == 1 and int(row.get("fallback_index") or 0) == 0]
    fallback = [row for row in started if int(row.get("fallback_index") or 0) > 0]
    retries = [row for row in started if int(row.get("attempt") or 1) > 1]
    timeouts = [row for row in rows if row.get("event_type") in {"llm.request.failed", "llm.request.skipped"} and row.get("failure_type") == "timeout"]
    durations = [
        duration
        for row in terminal
        if (duration := _nonnegative_number(row.get("model_duration_ms"))) is not None
    ]
    authoritative = [row for row in rows if "authoritative_source_truncated" in row]
    overflow = Counter(str(row.get("overflow_strategy") or "unspecified") for row in authoritative)
    cache_statuses = Counter(
        str(row.get("prompt_cache_status"))
        for row in completed
        if str(row.get("prompt_cache_status") or "") in {"hit", "miss", "unsupported", "unreported"}
    )
    cache_samples = [
        row for row in completed
        if row.get("prompt_cache_status") in {"hit", "miss"}
        or isinstance(row.get("cache_hit"), bool)
    ]
    token_samples = [
        row
        for row in completed
        if isinstance(row.get("input_tokens"), (int, float))
        or isinstance(row.get("output_tokens"), (int, float))
    ]
    input_tokens = int(sum(_number(row.get("input_tokens")) for row in completed))
    output_tokens = int(sum(_number(row.get("output_tokens")) for row in completed))
    statuses = list(run_statuses)
    succeeded = sum(status == "succeeded" for status in statuses)
    return {
        "sample_event_count": len(rows),
        "run_count": len(statuses),
        "run_success_rate": succeeded / len(statuses) if statuses else None,
        "logical_call_count": len(logical),
        "physical_request_count": len(started),
        "call_amplification": len(started) / len(logical) if logical else None,
        "p50_model_duration_ms": _percentile(durations, 0.50),
        "p95_model_duration_ms": _percentile(durations, 0.95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens if token_samples else None,
        "cache_read_tokens": int(sum(_number(row.get("cache_read_tokens")) for row in completed)),
        "cache_hit_rate": (
            sum(
                row.get("prompt_cache_status") == "hit"
                or row.get("cache_hit") is True
                for row in cache_samples
            ) / len(cache_samples)
            if cache_samples else None
        ),
        "cache_status_counts": {
            status: int(cache_statuses.get(status, 0))
            for status in ("hit", "miss", "unsupported", "unreported")
        },
        "retry_rate": len(retries) / len(started) if started else None,
        "fallback_rate": len(fallback) / len(started) if started else None,
        "timeout_rate": len(timeouts) / len(terminal) if terminal else None,
        "authoritative_context_sample_count": len(authoritative),
        "authoritative_truncation_rate": sum(bool(row.get("authoritative_source_truncated")) for row in authoritative) / len(authoritative) if authoritative else None,
        "overflow_strategy_counts": dict(sorted(overflow.items())),
        "definitions": {
            "logical_call": "attempt=1 and fallback_index=0 started request",
            "physical_request": "every started provider request",
        },
    }


_MODEL_TREND_TOP_LIMIT = 5
_OTHER_MODELS_LABEL = "其他模型"


def _performance_day(created_at: Any) -> str | None:
    """将数据库 UTC 时间映射为性能中心使用的中国标准日期。

    Args:
        created_at: created 时间。
    """

    if not isinstance(created_at, datetime):
        return None
    utc_value = (
        created_at.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None
        else created_at.astimezone(timezone.utc)
    )
    return utc_value.astimezone(_PERFORMANCE_TIME_ZONE).date().isoformat()


def _event_payload(event: Any) -> dict[str, Any]:
    """读取模型事件的已脱敏载荷，非字典载荷按空值处理。"""

    raw_payload = event.get("payload", {}) if isinstance(event, dict) else getattr(event, "payload", {})
    return raw_payload if isinstance(raw_payload, dict) else {}


def _event_type(event: Any) -> str:
    """读取模型事件类型，兼容 ORM 行与纯函数测试输入。"""

    value = event.get("event_type") if isinstance(event, dict) else getattr(event, "event_type", "")
    return str(value or "")


def _event_model_identity(event: Any) -> tuple[str, str | None] | None:
    """返回安全持久化的模型名和 Provider；未标记模型不进入按模型趋势。"""

    payload = _event_payload(event)
    model_name = str(payload.get("model_name") or "").strip()
    if not model_name:
        return None
    model_provider = str(payload.get("model_provider") or "").strip() or None
    return model_name, model_provider


def _performance_trend_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """将一天或一个模型桶转换为不含原始载荷的安全指标。"""

    summary = summarize_model_metric_events(events)
    return {
        "logical_call_count": summary["logical_call_count"],
        "physical_request_count": summary["physical_request_count"],
        "retry_count": sum(
            event["event_type"] == "llm.request.started"
            and _event_int(event, "attempt", 1) > 1
            for event in events
        ),
        "fallback_count": sum(
            event["event_type"] == "llm.request.started"
            and _event_int(event, "fallback_index") > 0
            for event in events
        ),
        "timeout_count": sum(
            event["event_type"] in {"llm.request.failed", "llm.request.skipped"}
            and str(event.get("failure_type") or "").lower() in {"timeout", "deadline"}
            for event in events
        ),
        "p95_model_duration_ms": summary["p95_model_duration_ms"],
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "total_tokens": summary["total_tokens"],
    }


def _model_provider_label(providers: set[str]) -> str | None:
    """将同一模型的已知 Provider 压缩为可展示的安全标签。"""

    return "、".join(sorted(providers)) or None


def build_performance_model_options(events: Iterable[Any]) -> list[dict[str, str | None]]:
    """返回按逻辑调用量排序的可筛选模型名和 Provider，不暴露事件载荷。

    Args:
        events: 已完成 owner、时间和任务过滤的模型事件。
    """

    providers_by_model: dict[str, set[str]] = defaultdict(set)
    logical_calls: Counter[str] = Counter()
    for event in events:
        identity = _event_model_identity(event)
        if identity is None:
            continue
        model_name, model_provider = identity
        if model_provider:
            providers_by_model[model_name].add(model_provider)
        else:
            providers_by_model.setdefault(model_name, set())
        payload = _event_payload(event)
        if (
            _event_type(event) == "llm.request.started"
            and _event_int(payload, "attempt", 1) == 1
            and _event_int(payload, "fallback_index") == 0
        ):
            logical_calls[model_name] += 1

    return [
        {
            "model_name": model_name,
            "model_provider": _model_provider_label(providers_by_model[model_name]),
        }
        for model_name in sorted(
            providers_by_model,
            key=lambda name: (-logical_calls[name], name.casefold()),
        )
    ]


def build_performance_daily_trend(events: Iterable[Any]) -> list[dict[str, Any]]:
    """按产品时区生成不含原始 payload 的每日安全性能聚合。

    Args:
        events: 事件列表。
    """

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        created_at = event.get("created_at") if isinstance(event, dict) else getattr(event, "created_at", None)
        day = _performance_day(created_at)
        if day is None:
            continue
        buckets[day].append({**_event_payload(event), "event_type": _event_type(event)})

    return [
        {"date": day, **_performance_trend_metrics(buckets[day])}
        for day in sorted(buckets)
    ]


def build_model_performance_daily_trend(
    events: Iterable[Any], *, model_name: str | None = None,
) -> list[dict[str, Any]]:
    """按实际模型名生成每日安全调用趋势，默认保留前五个模型并归并其余模型。

    Args:
        events: 已完成 owner、时间和任务过滤的模型事件。
        model_name: 可选的实际模型名；给定后只输出该模型的聚合。
    """

    selected_model = str(model_name or "").strip() or None
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    providers_by_model: dict[str, set[str]] = defaultdict(set)
    for event in events:
        identity = _event_model_identity(event)
        if identity is None:
            continue
        current_model, model_provider = identity
        if selected_model and current_model != selected_model:
            continue
        created_at = event.get("created_at") if isinstance(event, dict) else getattr(event, "created_at", None)
        day = _performance_day(created_at)
        if day is None:
            continue
        if model_provider:
            providers_by_model[current_model].add(model_provider)
        else:
            providers_by_model.setdefault(current_model, set())
        buckets[(day, current_model)].append({
            **_event_payload(event),
            "event_type": _event_type(event),
        })

    logical_calls = {
        current_model: sum(
            _performance_trend_metrics(rows)["logical_call_count"]
            for (day, name), rows in buckets.items()
            if name == current_model
        )
        for current_model in providers_by_model
    }
    ranked_models = sorted(
        providers_by_model,
        key=lambda name: (-logical_calls[name], name.casefold()),
    )
    visible_models = ranked_models if selected_model else ranked_models[:_MODEL_TREND_TOP_LIMIT]
    other_models = set(ranked_models) - set(visible_models)

    trend: list[dict[str, Any]] = []
    days = sorted({day for day, _ in buckets})
    for day in days:
        for current_model in visible_models:
            rows = buckets.get((day, current_model))
            if rows:
                trend.append({
                    "date": day,
                    "model_name": current_model,
                    "model_provider": _model_provider_label(providers_by_model[current_model]),
                    **_performance_trend_metrics(rows),
                })
        other_rows = [
            event
            for current_model in other_models
            for event in buckets.get((day, current_model), [])
        ]
        if other_rows:
            trend.append({
                "date": day,
                "model_name": _OTHER_MODELS_LABEL,
                "model_provider": None,
                **_performance_trend_metrics(other_rows),
            })
    return trend


def serialize_model_metric_event(row: ModelMetricEventModel) -> dict[str, Any]:
    """把模型指标事件模型序列化为对外字典。

    Args:
        row: 模型指标事件数据库模型实例。
    """
    return {
        "event_id": str(row.id), "run_id": row.run_id, "trace_id": row.trace_id,
        "agent_name": row.agent_name, "task_type": row.task_type, "stage": row.stage,
        "event_type": row.event_type, "is_degradation": row.is_degradation,
        "payload": row.payload or {}, "timestamp": row.created_at.isoformat(),
    }


_ACTIVE_TASK_STATUSES = frozenset({
    "queued", "retrying", "running", "pause_requested", "paused",
    "awaiting_approval", "cancel_requested",
})
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled"})
_ISSUE_PRIORITY = (
    "timeout", "authentication", "rate_limit", "network", "request",
    "model_failure", "skipped", "fallback", "retry",
)
_WARNING_PRIORITY = ("context_protection",)


def _isoformat(value: Any) -> str | None:
    """按 API 约定安全地序列化数据库时间戳。

    Args:
        value: 值。
    """

    return utc_isoformat(value) if value is not None and hasattr(value, "isoformat") else None


def _event_int(payload: dict[str, Any], key: str, default: int = 0) -> int:
    """读取事件中的非负整数计数，避免异常遥测值污染摘要。

    Args:
        payload: 载荷字典。
        key: 键名。
        default: 默认值。
    """

    try:
        return max(0, int(payload.get(key) or default))
    except (TypeError, ValueError):
        return default


def _is_context_protection(payload: dict[str, Any]) -> bool:
    """判断事件是否记录了上下文保护/截断，而不返回原始上下文。

    Args:
        payload: 载荷字典。
    """

    return bool(payload.get("authoritative_source_truncated") or payload.get("truncated_sources"))


def _classify_event_issue(payload: dict[str, Any], event_type: str) -> str | None:
    """将模型事件映射为有限的产品诊断枚举。

    Args:
        payload: 载荷字典。
        event_type: 事件类型。
    """

    failure_type = str(payload.get("failure_type") or "").lower()
    category = str(payload.get("error_category") or payload.get("error_code") or "").lower()
    marker = f"{failure_type} {category}"
    if "timeout" in marker or "deadline" in marker:
        return "timeout"
    if "auth" in marker or "credential" in marker or "unauthor" in marker:
        return "authentication"
    if "rate" in marker or "quota" in marker or "limit" in marker:
        return "rate_limit"
    if "network" in marker or "connection" in marker or "dns" in marker:
        return "network"
    if event_type == "llm.request.failed":
        return "request" if "request" in marker or "validation" in marker else "model_failure"
    if event_type == "llm.request.skipped":
        return "skipped"
    if _event_int(payload, "fallback_index") > 0:
        return "fallback"
    if _event_int(payload, "attempt", 1) > 1:
        return "retry"
    return None


def _budget_event_value(event: Any, key: str) -> Any:
    """读取预算聚合所需的事件字段，兼容 ORM 行和纯字典输入。"""

    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key, None)


def _budget_timestamp(event: Any) -> datetime | None:
    """读取模型事件时间戳；无法识别的值不参与 elapsed 计算。"""

    value = _budget_event_value(event, "created_at")
    return value if isinstance(value, datetime) else None


def _budget_epoch_ms(value: Any) -> float | None:
    """把 naive/aware UTC 时间安全转成毫秒时间戳，便于跨数据库时区比较。"""

    if not isinstance(value, datetime):
        return None
    normalized = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return normalized.timestamp() * 1000


def _budget_elapsed_ms(start: Any, end: Any) -> int | None:
    """返回两个时间之间的非负毫秒差。"""

    start_ms = _budget_epoch_ms(start)
    end_ms = _budget_epoch_ms(end)
    if start_ms is None or end_ms is None:
        return None
    return max(0, int(end_ms - start_ms))


def _budget_number(value: Any) -> int | None:
    """读取有限非负数并转成整数；缺失 usage 保持 None。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    if normalized < 0 or normalized != normalized or normalized in {float("inf"), float("-inf")}:
        return None
    return int(normalized)


def _budget_sum_optional(values: Iterable[Any]) -> int | None:
    """对可选 usage 求和；没有任何有效值时返回 None 而不是 0。"""

    normalized = [_budget_number(value) for value in values]
    valid = [value for value in normalized if value is not None]
    return sum(valid) if valid else None


def _budget_stage_name(event: Any) -> str:
    """返回限制长度的阶段标识；空阶段统一归入未归属桶。"""

    payload = _event_payload(event)
    value = _budget_event_value(event, "stage") or payload.get("stage")
    normalized = str(value or "").strip()[:120]
    return normalized or "unattributed"


def _budget_status(event_type: str, payload: dict[str, Any]) -> str:
    """将事件类型映射为前端可理解的有限状态枚举。"""

    explicit = str(payload.get("status") or "").lower()
    if explicit in {"running", "succeeded", "failed", "skipped", "unknown"}:
        return explicit
    if event_type.endswith(".started"):
        return "running"
    if event_type.endswith(".completed") or event_type in {"context.assembled", "prompt.rendered"}:
        return "succeeded"
    if event_type.endswith(".failed"):
        return "failed"
    if event_type.endswith(".skipped"):
        return "skipped"
    return "unknown"


def _budget_event_terminal(event_type: str, status: str) -> bool:
    """判断事件是否代表一次阶段尝试的终点。"""

    return (
        status in {"succeeded", "failed", "skipped"}
        or event_type in {"context.assembled", "prompt.rendered"}
    )


def _budget_sort_key(event: Any) -> tuple[float, int]:
    """按落库时间和内部 id 排序，兼容多个 observation 的 event_index 重置。"""

    timestamp = _budget_epoch_ms(_budget_timestamp(event))
    raw_id = _budget_number(_budget_event_value(event, "id"))
    return (timestamp if timestamp is not None else float("inf"), raw_id or 0)


def _new_budget_stage(stage: str) -> dict[str, Any]:
    """创建阶段预算快照的安全字段骨架。"""

    return {
        "stage": stage,
        "kind": "other",
        "status": "unknown",
        "event_count": 0,
        "attempt_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "repair_count": 0,
        "usage_unavailable_count": 0,
        "input_chars": 0,
        "estimated_input_tokens": 0,
        "source_breakdown": {},
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "duration_ms": 0,
        "model_duration_ms": 0,
        "elapsed_ms": None,
        "deadline_ms": None,
        "deadline_remaining_ms": None,
        "failure_types": [],
        "primary_failure": None,
        "warning_types": [],
        "primary_warning": None,
        "context_protection_sources": [],
        "model_names": [],
        "final_model_name": None,
        "attempts": [],
        "_attempt_map": {},
        "_current_attempt_key": None,
        "first_event_at": None,
        "last_event_at": None,
        "_first_event_dt": None,
        "_last_event_dt": None,
        "_current_attempt_dt": None,
    }


def _budget_attempt_key(payload: dict[str, Any], *, fallback_key: str | None = None) -> str:
    """Build a bounded candidate key without retaining prompt or provider errors."""

    candidate = _budget_number(payload.get("candidate_index"))
    fallback = _budget_number(payload.get("fallback_index")) or 0
    model = str(payload.get("model_name") or "").strip()[:120]
    attempt = _budget_number(payload.get("attempt")) or 1
    if fallback_key and candidate is None and fallback == 0 and not model:
        return fallback_key
    return f"{candidate if candidate is not None else 'unknown'}:{fallback}:{model or 'unknown'}:{attempt}"


def _new_budget_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    """Create the safe public fields for one model candidate attempt."""

    candidate = _budget_number(payload.get("candidate_index"))
    fallback = _budget_number(payload.get("fallback_index")) or 0
    attempt = _budget_number(payload.get("attempt")) or 1
    model_name = str(payload.get("model_name") or "").strip()[:120] or None
    provider = str(payload.get("model_provider") or "").strip()[:80] or None
    return {
        "candidate_index": candidate,
        "fallback_index": fallback,
        "attempt": attempt,
        "model_name": model_name,
        "model_provider": provider,
        "status": "unknown",
        "failure_type": None,
        "failure_types": [],
        "repair_outcome": None,
        "usage_status": None,
        "duration_ms": None,
        "model_duration_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "started_at": None,
        "finished_at": None,
    }


def _budget_find_open_repair_attempt(
    stage_map: dict[str, dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Locate the newest open model call that a cross-stage repair concludes."""

    candidate = _budget_number(payload.get("candidate_index"))
    fallback = _budget_number(payload.get("fallback_index")) or 0
    attempt_number = _budget_number(payload.get("attempt")) or 1
    model_name = str(payload.get("model_name") or "").strip()[:120] or None
    for stage in reversed(list(stage_map.values())):
        for existing_attempt in reversed(stage["attempts"]):
            if existing_attempt.get("status") != "running":
                continue
            if existing_attempt.get("candidate_index") != candidate:
                continue
            if existing_attempt.get("fallback_index") != fallback:
                continue
            if existing_attempt.get("attempt") != attempt_number:
                continue
            if model_name and existing_attempt.get("model_name") != model_name:
                continue
            return existing_attempt
    return None


def _budget_attempt_issue(attempt: dict[str, Any], issue: str | None) -> None:
    """Attach only the bounded failure category to an attempt."""

    if issue and issue not in {"fallback", "retry"}:
        if issue not in attempt["failure_types"]:
            attempt["failure_types"].append(issue)
        attempt["failure_type"] = issue


def _budget_stage_kind(stage_name: str, event_type: str) -> str:
    """把阶段归为上下文、本地其他步骤或真实模型调用。"""

    if (
        event_type == "context.assembled"
        or ".reviewer_context" in stage_name
        or stage_name.endswith(".context_assembly")
    ):
        return "context"
    if event_type.startswith(("llm.request.", "embedding.request.")):
        return "model"
    return "other"


def _budget_merge_source_breakdown(
    stage: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """合并不含原文的来源字符数与估算 token，兼容缺少 token 的旧事件。"""

    included_chars = payload.get("source_breakdown")
    included_tokens = payload.get("source_token_breakdown")
    raw_chars = payload.get("source_raw_breakdown")
    raw_tokens = payload.get("source_raw_token_breakdown")
    chars = included_chars if isinstance(included_chars, dict) else {}
    tokens = included_tokens if isinstance(included_tokens, dict) else {}
    source_chars = raw_chars if isinstance(raw_chars, dict) else {}
    source_tokens = raw_tokens if isinstance(raw_tokens, dict) else {}
    for raw_name in list(dict.fromkeys([*chars, *tokens, *source_chars, *source_tokens]))[:32]:
        name = str(raw_name or "").strip()[:64]
        if not name:
            continue
        entry = stage["source_breakdown"].setdefault(
            name,
            {"input_chars": 0, "estimated_input_tokens": None},
        )
        input_chars = _budget_number(chars.get(raw_name))
        if input_chars is not None:
            entry["input_chars"] += input_chars
        estimated_tokens = _budget_number(tokens.get(raw_name))
        if estimated_tokens is not None:
            current = entry["estimated_input_tokens"] or 0
            entry["estimated_input_tokens"] = current + estimated_tokens
        source_input_chars = _budget_number(source_chars.get(raw_name))
        if source_input_chars is not None:
            entry["raw_input_chars"] = int(entry.get("raw_input_chars") or 0) + source_input_chars
        source_estimated_tokens = _budget_number(source_tokens.get(raw_name))
        if source_estimated_tokens is not None:
            current_raw = entry.get("estimated_raw_input_tokens") or 0
            entry["estimated_raw_input_tokens"] = current_raw + source_estimated_tokens


def _budget_append_unique(values: list[str], value: Any, *, limit: int = 8) -> None:
    """向安全枚举列表追加去重值并限制数量。"""

    normalized = str(value or "").strip()[:120]
    if normalized and normalized not in values and len(values) < limit:
        values.append(normalized)


def _budget_context_protection_sources(payload: dict[str, Any]) -> tuple[str, ...]:
    """返回触发保护的安全来源标识，绝不回传来源正文。"""

    sources: list[str] = []
    raw_sources = payload.get("truncated_sources")
    if isinstance(raw_sources, (list, tuple, set)):
        for source in raw_sources:
            _budget_append_unique(sources, source, limit=32)
    if payload.get("authoritative_source_truncated"):
        breakdown = payload.get("source_breakdown")
        if isinstance(breakdown, dict):
            for source in breakdown:
                _budget_append_unique(sources, source, limit=32)
        if not sources:
            _budget_append_unique(sources, "authoritative_context", limit=32)
    return tuple(sources)


def build_run_budget_monitor(
    run: Any,
    events: Iterable[Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """把单个 AgentRun 的模型事件聚合为不含原始 payload 的预算快照。

    该纯函数既服务 owner-scoped API，也允许用脱离数据库的事件样本测试运行中、
    失败和 fallback 状态。实际 usage 只来自终态事件，缺失时保留 None；输入字符数
    和估算 token 从 started/context 事件读取，原始 prompt 与错误正文永远不进入结果。
    """

    current_time = now or utc_now()
    ordered_events = sorted(list(events), key=_budget_sort_key)
    stage_map: dict[str, dict[str, Any]] = {}
    issue_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    latest_deadline_remaining: int | None = None
    deadline_values: list[int] = []

    for event in ordered_events:
        payload = _event_payload(event)
        event_type = _event_type(event)
        stage_name = _budget_stage_name(event)
        stage = stage_map.setdefault(stage_name, _new_budget_stage(stage_name))
        event_kind = _budget_stage_kind(stage_name, event_type)
        if event_kind != "other":
            stage["kind"] = event_kind
        created_at = _budget_timestamp(event)
        if created_at is not None:
            if first_event_at is None or (_budget_epoch_ms(created_at) or 0) < (_budget_epoch_ms(first_event_at) or 0):
                first_event_at = created_at
            if last_event_at is None or (_budget_epoch_ms(created_at) or 0) > (_budget_epoch_ms(last_event_at) or 0):
                last_event_at = created_at
            if stage["_first_event_dt"] is None:
                stage["_first_event_dt"] = created_at
                stage["first_event_at"] = _isoformat(created_at)
            stage["_last_event_dt"] = created_at
            stage["last_event_at"] = _isoformat(created_at)

        stage["event_count"] += 1
        status = _budget_status(event_type, payload)
        stage["status"] = status
        if event_type.startswith("llm.request."):
            is_repair = ".repair." in event_type
            attempt_map = stage["_attempt_map"]
            attempt = (
                _budget_find_open_repair_attempt(stage_map, payload)
                if is_repair and not event_type.endswith(".started")
                else None
            )
            key = _budget_attempt_key(
                payload,
                fallback_key=stage.get("_current_attempt_key") if is_repair else None,
            )
            if attempt is None and not payload.get("model_name"):
                candidate = _budget_number(payload.get("candidate_index"))
                fallback_index = _budget_number(payload.get("fallback_index")) or 0
                attempt_number = _budget_number(payload.get("attempt")) or 1
                matching_key = next(
                    (
                        existing_key
                        for existing_key, existing_attempt in attempt_map.items()
                        if existing_attempt.get("candidate_index") == candidate
                        and existing_attempt.get("fallback_index") == fallback_index
                        and existing_attempt.get("attempt") == attempt_number
                    ),
                    None,
                )
                if matching_key:
                    key = matching_key
            if attempt is None:
                attempt = attempt_map.get(key)
                if attempt is None:
                    attempt = _new_budget_attempt(payload)
                    attempt_map[key] = attempt
                    stage["attempts"].append(attempt)
            if not is_repair and event_type.endswith(".started"):
                stage["_current_attempt_key"] = key
            if payload.get("model_name") and not attempt.get("model_name"):
                attempt["model_name"] = str(payload["model_name"]).strip()[:120]
            if payload.get("model_provider") and not attempt.get("model_provider"):
                attempt["model_provider"] = str(payload["model_provider"]).strip()[:80]
            if created_at is not None:
                if event_type.endswith(".started") and not is_repair:
                    attempt["started_at"] = _isoformat(created_at)
                elif attempt.get("started_at") is None:
                    attempt["started_at"] = _isoformat(created_at)
                if _budget_event_terminal(event_type, status) or event_type.endswith(".repair.completed") or event_type.endswith(".repair.failed"):
                    attempt["finished_at"] = _isoformat(created_at)
            if is_repair:
                if event_type.endswith(".started"):
                    attempt["repair_outcome"] = "started"
                elif event_type.endswith(".completed"):
                    attempt["repair_outcome"] = "completed"
                    attempt["status"] = "succeeded"
                elif event_type.endswith(".failed"):
                    attempt["repair_outcome"] = "failed"
                    attempt["status"] = "failed"
                    _budget_attempt_issue(attempt, _classify_event_issue(payload, event_type))
            else:
                attempt["status"] = status
                issue = _classify_event_issue(payload, event_type)
                _budget_attempt_issue(attempt, issue)
                usage_status = str(payload.get("usage_status") or "").strip()[:32]
                if usage_status:
                    attempt["usage_status"] = usage_status
                for token_key in ("input_tokens", "output_tokens", "total_tokens"):
                    value = _budget_number(payload.get(token_key))
                    if value is not None:
                        attempt[token_key] = value
                model_duration = _budget_number(payload.get("model_duration_ms"))
                duration = model_duration if model_duration is not None else _budget_number(payload.get("duration_ms"))
                if duration is not None:
                    attempt["duration_ms"] = duration
                if model_duration is not None:
                    attempt["model_duration_ms"] = model_duration
        stage["deadline_ms"] = _budget_number(payload.get("deadline_ms")) or stage["deadline_ms"]
        remaining = _budget_number(payload.get("deadline_remaining_ms"))
        if remaining is not None:
            stage["deadline_remaining_ms"] = remaining
            latest_deadline_remaining = remaining
        if stage["deadline_ms"] is not None:
            deadline_values.append(stage["deadline_ms"])

        if event_type == "llm.request.repair.started":
            stage["repair_count"] += 1
        if (
            payload.get("usage_status") == "unavailable"
            and event_type in {"llm.request.failed", "llm.request.repair.failed", "llm.request.skipped"}
        ):
            stage["usage_unavailable_count"] += 1

        if event_type.endswith(".started"):
            stage["_current_attempt_dt"] = created_at or stage["_current_attempt_dt"]
            stage["attempt_count"] += 1
            attempt = _budget_number(payload.get("attempt")) or 1
            fallback_index = _budget_number(payload.get("fallback_index")) or 0
            if attempt > 1:
                stage["retry_count"] += 1
            if fallback_index > 0:
                stage["fallback_count"] += 1
            stage["input_chars"] += _budget_number(payload.get("input_chars")) or 0
            stage["estimated_input_tokens"] += _budget_number(payload.get("estimated_input_tokens")) or 0
            _budget_merge_source_breakdown(stage, payload)
        elif _budget_event_terminal(event_type, status):
            if status == "succeeded":
                stage["completed_count"] += 1
            elif status == "failed":
                stage["failed_count"] += 1
            elif status == "skipped":
                stage["skipped_count"] += 1
            if stage["attempt_count"] == 0:
                stage["attempt_count"] = 1
            if stage["attempt_count"] == 1 and not stage["input_chars"]:
                stage["input_chars"] += _budget_number(payload.get("input_chars")) or 0
                stage["estimated_input_tokens"] += _budget_number(payload.get("estimated_input_tokens")) or 0
                _budget_merge_source_breakdown(stage, payload)

            model_duration = _budget_number(payload.get("model_duration_ms"))
            duration = model_duration
            if duration is None:
                duration = _budget_number(payload.get("duration_ms"))
            if duration is not None:
                stage["duration_ms"] += duration
            if model_duration is not None:
                stage["model_duration_ms"] += model_duration

            actual_input = _budget_number(payload.get("input_tokens"))
            actual_output = _budget_number(payload.get("output_tokens"))
            actual_total = _budget_number(payload.get("total_tokens"))
            if actual_input is not None:
                stage["input_tokens"] = (stage["input_tokens"] or 0) + actual_input
            if actual_output is not None:
                stage["output_tokens"] = (stage["output_tokens"] or 0) + actual_output
            if actual_total is not None:
                stage["total_tokens"] = (stage["total_tokens"] or 0) + actual_total
            elif actual_input is not None or actual_output is not None:
                derived = (actual_input or 0) + (actual_output or 0)
                stage["total_tokens"] = (stage["total_tokens"] or 0) + derived

        if _is_context_protection(payload):
            if "context_protection" not in stage["warning_types"]:
                _budget_append_unique(stage["warning_types"], "context_protection")
                warning_counts["context_protection"] += 1
            for source in _budget_context_protection_sources(payload):
                _budget_append_unique(stage["context_protection_sources"], source, limit=32)
        issue = _classify_event_issue(payload, event_type)
        if issue and issue not in {"fallback", "retry"}:
            _budget_append_unique(stage["failure_types"], issue)
            issue_counts[issue] += 1
        model_name = str(payload.get("model_name") or "").strip()
        if model_name:
            _budget_append_unique(stage["model_names"], model_name)

    run_status = str(getattr(run, "status", "unknown") or "unknown")
    run_started_at = getattr(run, "started_at", None) or getattr(run, "created_at", None)
    run_finished_at = getattr(run, "finished_at", None)
    is_active = run_status in _ACTIVE_TASK_STATUSES
    stage_end_time = current_time if is_active else run_finished_at or current_time

    for stage in stage_map.values():
        if not is_active:
            if stage["status"] == "running":
                stage["status"] = "unknown"
            for attempt in stage["attempts"]:
                if attempt.get("status") == "running":
                    attempt["status"] = "unknown"
        first = stage.get("_first_event_dt")
        last = stage.get("_last_event_dt")
        if stage["status"] in {"running", "unknown"}:
            stage["elapsed_ms"] = _budget_elapsed_ms(
                stage.get("_current_attempt_dt") or first,
                stage_end_time,
            )
        else:
            stage["elapsed_ms"] = _budget_elapsed_ms(
                stage.get("_current_attempt_dt") or first,
                last,
            ) or stage["model_duration_ms"] or stage["duration_ms"] or None
        stage["primary_failure"] = next(
            (issue for issue in _ISSUE_PRIORITY if issue in stage["failure_types"]),
            stage["failure_types"][0] if stage["failure_types"] else None,
        )
        stage["primary_warning"] = next(
            (warning for warning in _WARNING_PRIORITY if warning in stage["warning_types"]),
            stage["warning_types"][0] if stage["warning_types"] else None,
        )
        stage["attempts"] = [
            {
                **attempt,
                "failure_types": list(attempt.get("failure_types") or []),
            }
            for attempt in stage["attempts"]
        ]
        stage["final_model_name"] = next(
            (
                attempt.get("model_name")
                for attempt in reversed(stage["attempts"])
                if attempt.get("status") == "succeeded" and attempt.get("model_name")
            ),
            None,
        )
        stage.pop("_attempt_map", None)
        stage.pop("_current_attempt_key", None)
        stage.pop("_first_event_dt", None)
        stage.pop("_last_event_dt", None)
        stage.pop("_current_attempt_dt", None)
        if stage["input_tokens"] is None and stage["output_tokens"] is not None:
            stage["total_tokens"] = None
        elif stage["total_tokens"] is None and stage["input_tokens"] is not None and stage["output_tokens"] is not None:
            stage["total_tokens"] = stage["input_tokens"] + stage["output_tokens"]

    run_elapsed = _budget_elapsed_ms(run_started_at, run_finished_at or current_time)
    if run_elapsed is None:
        run_elapsed = _budget_elapsed_ms(first_event_at, run_finished_at or current_time)
    primary_issue = next((issue for issue in _ISSUE_PRIORITY if issue_counts[issue]), None)
    if run_status in {"succeeded", "completed"}:
        outcome = "recovered" if issue_counts else "succeeded"
    elif run_status in _TERMINAL_FAILURE_STATUSES:
        outcome = "failed"
    elif is_active:
        outcome = "active"
    else:
        outcome = run_status

    stages = list(stage_map.values())
    context_stages = [stage for stage in stages if stage["kind"] == "context"]
    model_stages = [stage for stage in stages if stage["kind"] == "model"]
    totals = {
        "input_chars": sum(stage["input_chars"] for stage in stages),
        "estimated_input_tokens": sum(stage["estimated_input_tokens"] for stage in stages),
        "context_input_chars": sum(stage["input_chars"] for stage in context_stages),
        "context_estimated_input_tokens": sum(
            stage["estimated_input_tokens"] for stage in context_stages
        ),
        "model_input_chars": sum(stage["input_chars"] for stage in model_stages),
        "model_estimated_input_tokens": sum(
            stage["estimated_input_tokens"] for stage in model_stages
        ),
        "input_tokens": _budget_sum_optional(stage["input_tokens"] for stage in stages),
        "output_tokens": _budget_sum_optional(stage["output_tokens"] for stage in stages),
        "total_tokens": _budget_sum_optional(stage["total_tokens"] for stage in stages),
        "model_duration_ms": sum(stage["model_duration_ms"] for stage in stages),
        "duration_ms": sum(stage["duration_ms"] for stage in stages),
        "attempt_count": sum(stage["attempt_count"] for stage in stages),
        "completed_count": sum(stage["completed_count"] for stage in stages),
        "failed_count": sum(stage["failed_count"] for stage in stages),
        "skipped_count": sum(stage["skipped_count"] for stage in stages),
        "retry_count": sum(stage["retry_count"] for stage in stages),
        "fallback_count": sum(stage["fallback_count"] for stage in stages),
        "timeout_count": issue_counts["timeout"],
        "repair_count": sum(stage["repair_count"] for stage in stages),
        "usage_unavailable_count": sum(stage["usage_unavailable_count"] for stage in stages),
        "context_protection_count": warning_counts["context_protection"],
    }
    deadline_ms = max(deadline_values) if deadline_values else None
    deadline_remaining_ms = latest_deadline_remaining
    if deadline_remaining_ms is None and deadline_ms is not None and is_active and run_elapsed is not None:
        deadline_remaining_ms = max(0, deadline_ms - run_elapsed)

    return {
        "run_id": str(getattr(run, "id", "")),
        "task_type": str(getattr(run, "task_type", "unknown") or "unknown"),
        "agent_name": str(getattr(run, "agent_name", "unknown") or "unknown"),
        "status": run_status,
        "outcome": outcome,
        "stage": getattr(run, "stage", None),
        "is_active": is_active,
        "started_at": _isoformat(run_started_at),
        "finished_at": _isoformat(run_finished_at),
        "elapsed_ms": run_elapsed,
        "deadline_ms": deadline_ms,
        "deadline_remaining_ms": deadline_remaining_ms,
        "primary_failure": primary_issue,
        "failure_types": [issue for issue in _ISSUE_PRIORITY if issue_counts[issue]],
        "warning_types": [
            warning for warning in _WARNING_PRIORITY if warning_counts[warning]
        ],
        "last_updated_at": _isoformat(last_event_at or getattr(run, "updated_at", None)),
        "totals": totals,
        "stages": stages,
    }


async def query_run_budget(
    *, user_id: str, run_id: str, now: datetime | None = None,
) -> dict[str, Any] | None:
    """按 owner+run_id 查询模型事件并返回安全预算快照；不存在时返回 None。"""

    async with async_session() as session:
        run = await session.scalar(
            select(AgentRunModel).where(
                AgentRunModel.id == run_id,
                AgentRunModel.user_id == user_id,
            )
        )
        if run is None:
            return None
        events = list((await session.scalars(
            select(ModelMetricEventModel).where(
                ModelMetricEventModel.run_id == run_id,
                ModelMetricEventModel.user_id == user_id,
            ).order_by(
                ModelMetricEventModel.created_at.asc(),
                ModelMetricEventModel.id.asc(),
            )
        )).all())
    return build_run_budget_monitor(run, events, now=now)


def _task_outcome(status: str, issue_counts: Counter[str]) -> str:
    """按任务终态和模型调用摘要计算前端使用的任务结果。

    Args:
        status: 状态字符串。
        issue_counts: 传入的 issue_counts 值。
    """

    if status in {"succeeded", "completed"}:
        return "recovered" if issue_counts else "succeeded"
    if status in _TERMINAL_FAILURE_STATUSES:
        return "failed"
    return "active"


def _build_task_health(run: AgentRunModel, events: list[ModelMetricEventModel]) -> dict[str, Any]:
    """把一个 AgentRun 和其模型事件聚合为不含原始 payload 的安全摘要。

    Args:
        run: 运行记录。
        events: 事件列表。
    """

    issue_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    model_provider: str | None = None
    model_name: str | None = None
    trace_id = getattr(run, "trace_id", None)
    last_event = None
    primary_issue_stage: dict[str, str] = {}
    logical_call_count = 0
    physical_attempt_count = 0
    failed_attempt_count = 0
    timeout_count = 0
    retry_count = 0
    fallback_count = 0
    skipped_count = 0
    context_protection_count = 0

    for event in events:
        raw_payload = getattr(event, "payload", {})
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        event_type = str(getattr(event, "event_type", "") or "")
        event_stage = str(getattr(event, "stage", None) or payload.get("stage") or "").strip()
        if event_stage:
            stage_counts[event_stage] += 1
        event_created_at = getattr(event, "created_at", None)
        if event_created_at is not None and (last_event is None or event_created_at > last_event):
            last_event = event_created_at
        trace_id = trace_id or getattr(event, "trace_id", None)
        model_provider = str(payload.get("model_provider") or model_provider or "") or model_provider
        model_name = str(payload.get("model_name") or model_name or "") or model_name

        if event_type == "llm.request.started":
            physical_attempt_count += 1
            attempt = _event_int(payload, "attempt", 1)
            fallback_index = _event_int(payload, "fallback_index")
            if attempt == 1 and fallback_index == 0:
                logical_call_count += 1
            if attempt > 1:
                retry_count += 1
            if fallback_index > 0:
                fallback_count += 1
        if event_type == "llm.request.failed":
            failed_attempt_count += 1
        if event_type == "llm.request.skipped":
            skipped_count += 1
        if event_type in {"llm.request.failed", "llm.request.skipped"} and str(payload.get("failure_type") or "").lower() in {"timeout", "deadline"}:
            timeout_count += 1
        if _is_context_protection(payload):
            context_protection_count += 1

        issue = _classify_event_issue(payload, event_type)
        if issue:
            issue_counts[issue] += 1
            if event_stage and issue not in primary_issue_stage:
                primary_issue_stage[issue] = event_stage

    status = str(getattr(run, "status", "") or "")
    outcome = _task_outcome(status, issue_counts)
    primary_issue = next((issue for issue in _ISSUE_PRIORITY if issue_counts[issue]), None)
    primary_stage = primary_issue_stage.get(primary_issue or "") if primary_issue else None
    if primary_stage is None:
        primary_stage = stage_counts.most_common(1)[0][0] if stage_counts else getattr(run, "stage", None)

    return {
        "run_id": str(run.id),
        "trace_id": trace_id,
        "task_type": str(run.task_type),
        "agent_name": str(run.agent_name or "unknown"),
        "task_status": status,
        "stage": getattr(run, "stage", None),
        "primary_stage": primary_stage,
        "outcome": outcome,
        "primary_issue": primary_issue,
        "model_provider": model_provider,
        "model_name": model_name,
        "logical_call_count": logical_call_count,
        "physical_attempt_count": physical_attempt_count,
        "failed_attempt_count": failed_attempt_count,
        "timeout_count": timeout_count,
        "retry_count": retry_count,
        "fallback_count": fallback_count,
        "skipped_count": skipped_count,
        "context_protection_count": context_protection_count,
        "created_at": _isoformat(getattr(run, "created_at", None)),
        "finished_at": _isoformat(getattr(run, "finished_at", None)),
        "last_model_event_at": _isoformat(last_event),
    }


def build_task_health_summaries(
    runs: Iterable[AgentRunModel],
    events: Iterable[ModelMetricEventModel],
) -> list[dict[str, Any]]:
    """从已加载的任务和事件构建摘要，供查询层与纯单元测试复用。

    只有至少包含一条 ``llm.request.*`` 事件的任务才进入模型调用健康面板；
    prompt、embedding 等其他观测事件不能伪造一个模型调用任务。

    Args:
        runs: 传入的 runs 值。
        events: 事件列表。
    """

    events_by_run: dict[str, list[ModelMetricEventModel]] = {}
    for event in events:
        event_type = str(getattr(event, "event_type", "") or "")
        if not event_type.startswith("llm.request."):
            continue
        events_by_run.setdefault(str(event.run_id), []).append(event)
    return [
        _build_task_health(run, events_by_run[str(run.id)])
        for run in runs
        if str(run.id) in events_by_run
    ]


async def query_task_health(
    *, user_id: str, days: int = 7, task_type: str | None = None,
    agent_name: str | None = None, attention_only: bool = False,
    limit: int = 100, offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """查询当前 owner 的任务健康摘要，不返回原始模型事件 payload。

    Args:
        user_id: 用户 ID，所有者范围限定。
        days: 传入的 days 值。
        task_type: 任务类型。
        agent_name: Agent 名称。
        attention_only: 传入的 attention_only 值。
        limit: 返回数量上限。
        offset: 偏移量。
    """

    since = utc_now() - timedelta(days=max(1, min(days, 90)))
    filters = [AgentRunModel.user_id == user_id, AgentRunModel.created_at >= since]
    if task_type:
        filters.append(AgentRunModel.task_type == task_type)
    if agent_name:
        filters.append(AgentRunModel.agent_name == agent_name)

    async with async_session() as session:
        runs_total = list((await session.scalars(
            select(AgentRunModel)
            .where(*filters)
            .order_by(AgentRunModel.created_at.desc(), AgentRunModel.id.desc())
        )).all())
        run_ids = [run.id for run in runs_total]
        events: list[ModelMetricEventModel] = []
        if run_ids:
            events = list((await session.scalars(
                select(ModelMetricEventModel)
                .where(
                    ModelMetricEventModel.user_id == user_id,
                    ModelMetricEventModel.run_id.in_(run_ids),
                )
                .order_by(ModelMetricEventModel.created_at.asc(), ModelMetricEventModel.id.asc())
            )).all())

    summaries = build_task_health_summaries(runs_total, events)
    if attention_only:
        summaries = [
            summary for summary in summaries
            if summary["outcome"] in {"recovered", "failed"}
            or (summary["outcome"] == "active" and summary["primary_issue"] is not None)
        ]
    total = len(summaries)
    return summaries[offset:offset + limit], total


async def query_performance(
    *, user_id: str, days: int = 7, task_type: str | None = None,
    agent_name: str | None = None, model_name: str | None = None,
    degradations_only: bool = False, limit: int = 100, offset: int = 0,
) -> tuple[list[ModelMetricEventModel], int, list[str]]:
    """按条件分页查询模型指标事件并返回匹配总数与运行状态。

    Args:
        user_id: 用户 ID，限定所有者范围。
        days: 查询时间范围（天），最大 90。
        task_type: 按任务类型过滤；None 表示不过滤。
        agent_name: 按 Agent 名过滤；None 表示不过滤。
        model_name: 按安全持久化的实际模型名过滤；None 表示不过滤。
        degradations_only: 仅返回降级（is_degradation）事件。
        limit: 返回行数上限。
        offset: 分页偏移量。

    Returns:
        (事件行列表, 匹配总条数, 关联 AgentRun 状态列表)。
    """
    since = utc_now() - timedelta(days=max(1, min(days, 90)))
    filters = [ModelMetricEventModel.user_id == user_id, ModelMetricEventModel.created_at >= since]
    run_filters = [AgentRunModel.user_id == user_id, AgentRunModel.created_at >= since]
    if task_type:
        filters.append(ModelMetricEventModel.task_type == task_type)
        run_filters.append(AgentRunModel.task_type == task_type)
    if agent_name:
        filters.append(ModelMetricEventModel.agent_name == agent_name)
        run_filters.append(AgentRunModel.agent_name == agent_name)
    normalized_model_name = str(model_name or "").strip() or None
    if normalized_model_name:
        filters.append(ModelMetricEventModel.payload["model_name"].as_string() == normalized_model_name)
    if degradations_only:
        filters.append(ModelMetricEventModel.is_degradation.is_(True))
    async with async_session() as session:
        total = int(await session.scalar(select(func.count(ModelMetricEventModel.id)).where(*filters)) or 0)
        rows = list((await session.scalars(
            select(ModelMetricEventModel).where(*filters)
            .order_by(ModelMetricEventModel.created_at.desc(), ModelMetricEventModel.id.desc())
            .limit(limit).offset(offset)
        )).all())
        if normalized_model_name:
            matching_run_ids = {row.run_id for row in rows}
            statuses = [] if not matching_run_ids else list((await session.scalars(
                select(AgentRunModel.status).where(
                    *run_filters, AgentRunModel.id.in_(matching_run_ids)
                )
            )).all())
        else:
            statuses = list((await session.scalars(select(AgentRunModel.status).where(*run_filters))).all())
    return rows, total, statuses


async def performance_overview(**kwargs: Any) -> dict[str, Any]:
    """返回性能总览：汇总大量事件并附上匹配总数。

    Args:
        **kwargs: 透传给 query_performance 的过滤与分页参数。
    """
    query_kwargs = dict(kwargs)
    selected_model = str(query_kwargs.pop("model_name", "") or "").strip() or None
    rows, total, statuses = await query_performance(
        limit=5000, offset=0, model_name=selected_model, **query_kwargs,
    )
    option_rows = rows
    if selected_model:
        option_rows, _, _ = await query_performance(
            limit=5000, offset=0, **query_kwargs,
        )
    summary = summarize_model_metric_events((row.payload or {} for row in rows), run_statuses=statuses)
    summary["total_matching_events"] = total
    summary["daily_trend"] = build_performance_daily_trend(rows)
    summary["available_models"] = build_performance_model_options(option_rows)
    summary["model_daily_trend"] = build_model_performance_daily_trend(
        rows, model_name=selected_model,
    )
    return summary
