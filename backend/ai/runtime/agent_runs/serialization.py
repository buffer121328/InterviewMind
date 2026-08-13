"""AgentRun 与事件的公开序列化边界。"""

import math
from typing import Any

from app.db.models import AgentRunEventModel, AgentRunModel
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import can_cancel_status

from .definitions import build_task_plan, get_task_definition
from .policies import allows_whole_run_retry
from .settings import max_attempts


def _public_step_results(value: dict | None) -> dict:
    """移除步骤状态中的加密恢复载荷，只向客户端暴露时间和状态摘要。"""

    public: dict[str, dict] = {}
    for step_id, raw in (value or {}).items():
        step = dict(raw or {})
        step.pop("checkpoint_encrypted", None)
        public[str(step_id)] = step
    return public


def _first_token_duration_ms(model_events: list[dict[str, Any]] | None) -> int | None:
    """Return the earliest finite non-negative first-chunk latency in an observation."""

    values = [
        int(value)
        for event in model_events or []
        if isinstance((value := event.get("first_chunk_duration_ms")), (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    ]
    return min(values) if values else None


def serialize_run(run: AgentRunModel) -> dict:
    """将 AgentRun 模型序列化为 API 响应格式，不公开加密任务输入。"""

    definition = get_task_definition(run.task_type)
    agent_definition = get_agent_definition(run.task_type)
    return {
        "run_id": run.id,
        "session_id": getattr(run, "session_id", None),
        "session_title": getattr(run, "session_title", None),
        "session_status": getattr(run, "session_status", None),
        "session_question_count": getattr(run, "session_question_count", None),
        "session_max_questions": getattr(run, "session_max_questions", None),
        "agent_name": getattr(run, "agent_name", None) or agent_definition.name,
        "agent_version": getattr(run, "agent_version", None) or agent_definition.version,
        "task_type": run.task_type,
        "title": definition["title"],
        "status": run.status,
        "stage": run.stage,
        "plan": build_task_plan(run.task_type, run.stage, run.status),
        "result": run.result,
        "step_results": _public_step_results(getattr(run, "step_results", None)),
        "error_message": run.error_message,
        "trace_id": getattr(run, "trace_id", None),
        "first_token_duration_ms": getattr(run, "first_token_duration_ms", None),
        "attempts": run.attempts,
        "max_attempts": max_attempts(),
        "can_retry": (
            allows_whole_run_retry(run.task_type)
            and run.status in {"failed", "cancelled"}
            and run.attempts < max_attempts()
        ),
        "can_cancel": can_cancel_status(run.status),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def serialize_event(event: AgentRunEventModel) -> dict:
    """将 AgentRunEvent 模型序列化为 API 响应格式。"""

    return {
        "event_id": str(event.id),
        "run_id": event.run_id,
        "sequence": event.sequence,
        "type": event.event_type,
        "stage": event.stage,
        "payload": event.payload or {},
        "schema_version": event.schema_version,
        "timestamp": event.created_at.isoformat(),
    }
