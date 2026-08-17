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
    cache_samples = [row for row in completed if isinstance(row.get("cache_hit"), bool)]
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
        "cache_hit_rate": sum(row["cache_hit"] is True for row in cache_samples) / len(cache_samples) if cache_samples else None,
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
    "model_failure", "skipped", "context_protection", "fallback", "retry",
)


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

    if _is_context_protection(payload):
        return "context_protection"
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
