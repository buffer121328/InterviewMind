"""面试聊天 SSE 事件与 AgentRun lifecycle 事件投影。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ai.runtime.agent_runs.event_stream import build_run_event_envelope
from app.schemas.schemas import ChatStreamResponse


def execution_plan() -> list[dict[str, str]]:
    """返回文本面试流保持兼容的前端执行计划。"""
    return [
        {"id": "save_answer", "title": "记录本轮回答", "status": "pending"},
        {"id": "analyze_answer", "title": "分析回答并决定追问策略", "status": "pending"},
        {"id": "generate_response", "title": "生成反馈与下一题", "status": "pending"},
        {"id": "update_progress", "title": "更新面试进度", "status": "pending"},
    ]


def stream_event(event_type: str, payload: object) -> str:
    """编码保持兼容的文本面试 SSE 业务事件。"""
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    response = ChatStreamResponse(type=event_type, content=content)
    return f"data: {response.model_dump_json()}\n\n"


def encode_run_event(envelope: dict[str, Any]) -> str:
    """将受限 lifecycle envelope 映射到文本 SSE schema。"""
    return stream_event("agent_run_event", envelope)


def encode_error(message: str) -> str:
    """将安全错误映射到保持兼容的文本 SSE schema。"""
    return stream_event("error", message)


def detect_error_event(chunk: str) -> str | None:
    """识别已由业务流投影的 error SSE，避免错误流被错误收敛为成功。"""
    for line in chunk.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line.removeprefix("data: "))
        except json.JSONDecodeError:
            continue
        if event.get("type") == "error":
            return str(event.get("content") or event.get("message") or "面试流执行失败")
    return None


@dataclass(slots=True)
class ChatStreamEventEmitter:
    """为一次聊天流维护步骤去重和 AgentRun 事件序号。"""

    run_id: str | None = None
    emitted_steps: set[tuple[str, str]] = field(default_factory=set)
    sequence: int = 0

    def step_event(self, step_id: str, status: str) -> str | None:
        """将流水线步骤状态转换为前端事件，并抑制重复 marker。"""
        marker = (step_id, status)
        if marker in self.emitted_steps:
            return None
        self.emitted_steps.add(marker)
        return stream_event("step_update", {"id": step_id, "status": status})

    def run_event(
        self,
        event_type: str,
        stage: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        """将一次 lifecycle 变化编码为单调递增的 AgentRun 事件。"""
        if not self.run_id:
            return None
        self.sequence += 1
        return stream_event(
            "agent_run_event",
            build_run_event_envelope(
                run_id=self.run_id,
                event_type=event_type,
                stage=stage,
                payload=payload,
                sequence=self.sequence,
                event_id=f"inline:{self.run_id}:{self.sequence}",
            ),
        )
