"""提供性能相关后端功能。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Iterable

from sqlalchemy import func, select

from app.db.models import AgentRunModel, ModelMetricEventModel, async_session
from app.clock import utc_now


def _number(value: Any) -> float:
    """处理性能相关后端逻辑。"""
    return float(value) if isinstance(value, (int, float)) else 0.0


def _percentile(values: list[float], percentile: float) -> float | None:
    """处理性能相关后端逻辑。"""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, ceil(percentile * len(ordered)) - 1))]


def summarize_model_metric_events(
    events: Iterable[dict[str, Any]], *, run_statuses: Iterable[str] = ()
) -> dict[str, Any]:
    """汇总模型指标事件相关后端逻辑。"""
    rows = list(events)
    started = [row for row in rows if row.get("event_type") == "llm.request.started"]
    completed = [row for row in rows if row.get("event_type") == "llm.request.completed"]
    terminal = [row for row in rows if row.get("event_type") in {"llm.request.completed", "llm.request.failed"}]
    logical = [row for row in started if int(row.get("attempt") or 1) == 1 and int(row.get("fallback_index") or 0) == 0]
    fallback = [row for row in started if int(row.get("fallback_index") or 0) > 0]
    retries = [row for row in started if int(row.get("attempt") or 1) > 1]
    timeouts = [row for row in rows if row.get("event_type") in {"llm.request.failed", "llm.request.skipped"} and row.get("failure_type") == "timeout"]
    durations = [_number(row.get("model_duration_ms")) for row in terminal if _number(row.get("model_duration_ms")) >= 0]
    authoritative = [row for row in rows if "authoritative_source_truncated" in row]
    overflow = Counter(str(row.get("overflow_strategy") or "unspecified") for row in authoritative)
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
        "input_tokens": int(sum(_number(row.get("input_tokens")) for row in completed)),
        "output_tokens": int(sum(_number(row.get("output_tokens")) for row in completed)),
        "cache_read_tokens": int(sum(_number(row.get("cache_read_tokens")) for row in completed)),
        "cache_hit_rate": sum(bool(row.get("cache_hit")) for row in completed) / len(completed) if completed else None,
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


def serialize_model_metric_event(row: ModelMetricEventModel) -> dict[str, Any]:
    """序列化模型指标事件相关后端逻辑。"""
    return {
        "event_id": str(row.id), "run_id": row.run_id, "trace_id": row.trace_id,
        "agent_name": row.agent_name, "task_type": row.task_type, "stage": row.stage,
        "event_type": row.event_type, "is_degradation": row.is_degradation,
        "payload": row.payload or {}, "timestamp": row.created_at.isoformat(),
    }


async def query_performance(
    *, user_id: str, days: int = 7, task_type: str | None = None,
    agent_name: str | None = None, degradations_only: bool = False,
    limit: int = 100, offset: int = 0,
) -> tuple[list[ModelMetricEventModel], int, list[str]]:
    """处理性能相关后端逻辑。"""
    since = utc_now() - timedelta(days=max(1, min(days, 90)))
    filters = [ModelMetricEventModel.user_id == user_id, ModelMetricEventModel.created_at >= since]
    run_filters = [AgentRunModel.user_id == user_id, AgentRunModel.created_at >= since]
    if task_type:
        filters.append(ModelMetricEventModel.task_type == task_type)
        run_filters.append(AgentRunModel.task_type == task_type)
    if agent_name:
        filters.append(ModelMetricEventModel.agent_name == agent_name)
        run_filters.append(AgentRunModel.agent_name == agent_name)
    if degradations_only:
        filters.append(ModelMetricEventModel.is_degradation.is_(True))
    async with async_session() as session:
        total = int(await session.scalar(select(func.count(ModelMetricEventModel.id)).where(*filters)) or 0)
        rows = list((await session.scalars(
            select(ModelMetricEventModel).where(*filters)
            .order_by(ModelMetricEventModel.created_at.desc(), ModelMetricEventModel.id.desc())
            .limit(limit).offset(offset)
        )).all())
        statuses = list((await session.scalars(select(AgentRunModel.status).where(*run_filters))).all())
    return rows, total, statuses


async def performance_overview(**kwargs: Any) -> dict[str, Any]:
    """处理性能相关后端逻辑。"""
    rows, total, statuses = await query_performance(limit=5000, offset=0, **kwargs)
    summary = summarize_model_metric_events((row.payload or {} for row in rows), run_statuses=statuses)
    summary["total_matching_events"] = total
    return summary
