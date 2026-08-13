"""Agent 公共运行时。

业务 Agent 放在 :mod:`ai.agents`，这里仅保存跨 Agent 复用的运行机制。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from .context import AgentContext
from .execution.deadlines import TaskDeadline, TaskDeadlineExceeded, task_deadline_scope

__all__ = [
    "AgentContext",
    "TaskDeadline",
    "TaskDeadlineExceeded",
    "create_guarded_agent",
    "task_deadline_scope",
]


def _create_guarded_agent_fallback(
    model: Any,
    tools: Sequence[Any],
    *,
    system_prompt: Any = None,
    tool_permissions: dict[str, Collection[str]] | None = None,
    approval_tools: Collection[str] = (),
    fallback_models: Collection[Any] = (),
    checkpointer: Any = None,
    max_model_calls: int = 4,
    max_tool_calls: int = 12,
    **kwargs: Any,
) -> Any:
    """构建带安全护栏的 Agent fallback；fallback 只保证流程可恢复，不得绕过工具权限、审批、审计或模型配置校验。

    Args:
        model: 模型对象。
        tools: 经过类型边界校验的 `tools`；其格式和可选值由参数类型及调用流程约束。
        system_prompt: 经过类型边界校验的 `system_prompt`；其格式和可选值由参数类型及调用流程约束。
        tool_permissions: 经过类型边界校验的 `tool_permissions`；其格式和可选值由参数类型及调用流程约束。
        approval_tools: 经过类型边界校验的 `approval_tools`；其格式和可选值由参数类型及调用流程约束。
        fallback_models: 经过类型边界校验的 `fallback_models`；其格式和可选值由参数类型及调用流程约束。
        checkpointer: 经过类型边界校验的 `checkpointer`；其格式和可选值由参数类型及调用流程约束。
        max_model_calls: 经过类型边界校验的 `max_model_calls`；其格式和可选值由参数类型及调用流程约束。
        max_tool_calls: 经过类型边界校验的 `max_tool_calls`；其格式和可选值由参数类型及调用流程约束。
        **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
    """
    if approval_tools and checkpointer is None:
        raise ValueError("approval_tools require a checkpointer")
    raise ModuleNotFoundError("langchain is required to create a guarded agent")


def __getattr__(name: str):
    """实现 `__getattr__` 协议方法。

    Args:
        name: 名称。
    """
    if name == "create_guarded_agent":
        try:
            from .factory import create_guarded_agent
        except ModuleNotFoundError:
            return _create_guarded_agent_fallback
        return create_guarded_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
