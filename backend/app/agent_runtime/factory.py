"""统一创建带生产护轨的 LangChain Agent。"""

from collections.abc import Collection, Sequence
from typing import Any

from langchain.agents import create_agent

from app.agent_runtime.context import AgentContext
from app.agent_runtime.middleware import build_default_middleware


def create_guarded_agent(
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
    """创建统一受控 Agent；需要人审时强制提供 checkpoint。"""
    if approval_tools and checkpointer is None:
        raise ValueError("approval_tools require a checkpointer")

    middleware = build_default_middleware(
        tool_permissions=tool_permissions,
        approval_tools=approval_tools,
        fallback_models=fallback_models,
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
    )
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        **kwargs,
    )
