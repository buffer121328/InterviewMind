"""连接工具审计与 AgentRun 可重放事件流。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ai.runtime.context import AgentContext

logger = logging.getLogger(__name__)

ToolAuditCallback = Callable[[dict[str, Any]], Awaitable[None]]


def agent_run_audit_callback(context: AgentContext) -> ToolAuditCallback:
    """返回绑定可信运行身份的异步工具审计 sink。

    没有 AgentRun 的同步请求仍可使用 ``ToolExecutionGuard``，但不会尝试把事件
    写入 AgentRun 表；这避免把 BOSS 等非 AgentRun 调用伪造成可恢复任务。
    """

    async def persist(event: dict[str, Any]) -> None:
        if not context.run_id:
            return
        try:
            from ai.runtime.agent_runs.service import AgentRunService

            await AgentRunService().record_governance_event(
                context.run_id,
                user_id=context.user_id,
                event_type="tool.execution",
                payload=event,
            )
        except Exception as exc:  # noqa: BLE001 - 审计落库不可阻断已执行的业务动作。
            logger.warning("工具审计事件持久化失败: %s", type(exc).__name__)

    return persist
