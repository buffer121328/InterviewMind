"""Agent 公共运行时。

业务 Agent 放在 :mod:`app.agents`，这里仅保存跨 Agent 复用的运行机制。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from .context import AgentContext

__all__ = ["AgentContext", "create_guarded_agent"]


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
    """创建 `guarded agent fallback`。

    Args:
        model: 模型对象。
        tools: 调用方传入的 `tools` 参数。
        system_prompt: 调用方传入的 `system_prompt` 参数。
        tool_permissions: 调用方传入的 `tool_permissions` 参数。
        approval_tools: 调用方传入的 `approval_tools` 参数。
        fallback_models: 调用方传入的 `fallback_models` 参数。
        checkpointer: 调用方传入的 `checkpointer` 参数。
        max_model_calls: 调用方传入的 `max_model_calls` 参数。
        max_tool_calls: 调用方传入的 `max_tool_calls` 参数。
        **kwargs: 调用方传入的 `kwargs` 参数。
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
