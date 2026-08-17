"""面试聊天 SSE 事件与 AgentRun lifecycle 事件投影。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ai.runtime.agent_runs.event_stream import build_run_event_envelope
from app.schemas.interview.schemas import ChatStreamResponse


def execution_plan() -> list[dict[str, str]]:
    """返回文本面试流保持兼容的前端执行计划。"""
    return [
        {"id": "save_answer", "title": "记录本轮回答", "status": "pending"},
        {"id": "analyze_answer", "title": "分析回答并决定追问策略", "status": "pending"},
        {"id": "generate_response", "title": "生成反馈与下一题", "status": "pending"},
        {"id": "update_progress", "title": "更新面试进度", "status": "pending"},
    ]


def stream_event(event_type: str, payload: object) -> str:
    """编码保持兼容的文本面试 SSE 业务事件。

    Args:
        event_type: SSE 事件类型。
        payload: 事件负载；字符串直接透传，其他类型序列化为 JSON。
    """
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    response = ChatStreamResponse(type=event_type, content=content)
    return f"data: {response.model_dump_json()}\n\n"


def encode_run_event(envelope: dict[str, Any]) -> str:
    """将受限 lifecycle envelope 映射到文本 SSE schema。

    Args:
        envelope: 受限的 AgentRun lifecycle envelope 字典。
    """
    return stream_event("agent_run_event", envelope)


def encode_error(message: str) -> str:
    """将安全错误映射到保持兼容的文本 SSE schema。

    Args:
        message: 脱敏后的错误消息文本。
    """
    return stream_event("error", message)


def detect_error_event(chunk: str) -> str | None:
    """识别已由业务流投影的 error SSE，避免错误流被错误收敛为成功。

    Args:
        chunk: 一段 SSE 数据块（可含多行 data: 帧）。
    """
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

    # 运行记录 ID。
    run_id: str | None = None  # 关联的 AgentRun 标识；为空时禁用 run 事件
    # emitted_steps，字符串类型。
    emitted_steps: set[tuple[str, str]] = field(default_factory=set)  # 已发射的步骤 marker 集合
    # sequence，整数类型。
    sequence: int = 0  # AgentRun 事件单调递增序号

    def step_event(self, step_id: str, status: str) -> str | None:
        """将流水线步骤状态转换为前端事件，并抑制重复 marker。

        Args:
            step_id: 步骤标识。
            status: 步骤状态。
        """
        marker = (step_id, status)
        if marker in self.emitted_steps:
            return None
        # event 类型。
        self.emitted_steps.add(marker)
        # stage。
        return stream_event("step_update", {"id": step_id, "status": status})
# 载荷字典。

    def run_event(
        self,
        event_type: str,
        stage: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        """将一次 lifecycle 变化编码为单调递增的 AgentRun 事件。

        Args:
            event_type: 事件类型。
            stage: 关联的阶段名，可选。
            payload: 事件负载，可选。
        """
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
