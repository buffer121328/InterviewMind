"""LangChain 1.x Agent 的默认生产护轨。"""

from collections.abc import Collection
from typing import Any

from app.infrastructure.runtime.context import AgentContext
from .content_safety import prompt_injection_middleware

try:  # pragma: no cover - 运行时可选依赖
    from langchain.agents.middleware import (
        HumanInTheLoopMiddleware,
        ModelCallLimitMiddleware,
        ModelFallbackMiddleware,
        ModelRetryMiddleware,
        PIIMiddleware,
        ToolCallLimitMiddleware,
        wrap_tool_call,
    )
except ModuleNotFoundError:  # pragma: no cover - 轻量测试环境
    def wrap_tool_call(func):
        return func

    class _StubMiddleware:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class HumanInTheLoopMiddleware(_StubMiddleware):
        pass

    class ModelCallLimitMiddleware(_StubMiddleware):
        pass

    class ModelFallbackMiddleware(_StubMiddleware):
        pass

    class ModelRetryMiddleware(_StubMiddleware):
        pass

    class PIIMiddleware(_StubMiddleware):
        pass

    class ToolCallLimitMiddleware(_StubMiddleware):
        pass


def permission_middleware(tool_permissions: dict[str, Collection[str]]):
    """在实际工具调用时复核可信 Runtime context 中的权限。"""

    @wrap_tool_call
    async def enforce_permissions(request: Any, handler: Any):
        tool_name = str(request.tool_call.get("name", ""))
        required = set(tool_permissions.get(tool_name, ()))
        context = getattr(request.runtime, "context", None)
        if required:
            if not isinstance(context, AgentContext):
                raise PermissionError("trusted AgentContext is required")
            missing = required.difference(context.permissions)
            if missing:
                raise PermissionError(
                    f"tool {tool_name} requires permissions: {', '.join(sorted(missing))}"
                )
        return await handler(request)

    return enforce_permissions


def build_default_middleware(
    *,
    tool_permissions: dict[str, Collection[str]] | None = None,
    approval_tools: Collection[str] = (),
    fallback_models: Collection[Any] = (),
    max_model_calls: int = 4,
    max_tool_calls: int = 12,
) -> list[Any]:
    """生成有界 Agent 循环的中间件链；审批场景要求 Agent 配置 checkpointer。"""
    middleware: list[Any] = [
        permission_middleware(tool_permissions or {}),
        prompt_injection_middleware,
        PIIMiddleware("email", strategy="redact", apply_to_tool_results=True),
        PIIMiddleware("credit_card", strategy="redact", apply_to_tool_results=True),
        ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="error"),
        ToolCallLimitMiddleware(run_limit=max_tool_calls, exit_behavior="error"),
        ModelRetryMiddleware(max_retries=1),
    ]
    if fallback_models:
        middleware.append(ModelFallbackMiddleware(*fallback_models))
    if approval_tools:
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={name: True for name in approval_tools},
                description_prefix="该操作会产生外部或写入副作用，需要确认",
            )
        )
    return middleware
