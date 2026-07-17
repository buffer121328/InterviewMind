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
    if approval_tools and checkpointer is None:
        raise ValueError("approval_tools require a checkpointer")
    raise ModuleNotFoundError("langchain is required to create a guarded agent")


def __getattr__(name: str):
    if name == "create_guarded_agent":
        try:
            from .factory import create_guarded_agent
        except ModuleNotFoundError:
            return _create_guarded_agent_fallback
        return create_guarded_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
