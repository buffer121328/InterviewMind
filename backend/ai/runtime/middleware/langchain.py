"""LangChain 1.x Agent 的默认生产护轨。"""

from collections.abc import Collection
from typing import Any

from ai.runtime.context import AgentContext
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
        """包装工具调用以统一权限校验、异常映射和审计事件写入。

        Args:
            func: 经过类型边界校验的 `func`；其格式和可选值由参数类型及调用流程约束。
        """
        return func

    class _StubMiddleware:
        """应用或基础设施协作者，负责 `StubMiddleware` 的职责；依赖通过构造或模块边界注入，外部调用、状态持久化和安全校验不向调用方隐藏。"""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """初始化 `_StubMiddleware` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

            Args:
                *args: 经过类型边界校验的 `args`；其格式和可选值由参数类型及调用流程约束。
                **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
            """
            self.args = args
            self.kwargs = kwargs

    class HumanInTheLoopMiddleware(_StubMiddleware):
        """人工确认中间件边界；对需要审批的工具调用暂停并等待显式确认，不能把模型输出或自动化 fallback 当作用户批准。"""
        pass

    class ModelCallLimitMiddleware(_StubMiddleware):
        """模型调用次数治理中间件；在单次运行范围内限制调用量，防止重试或循环无限消耗额度，不改变业务权限。"""
        pass

    class ModelFallbackMiddleware(_StubMiddleware):
        """模型 fallback 中间件；仅在候选模型失败且策略允许时切换，并保留原始错误、观测和安全配置边界。"""
        pass

    class ModelRetryMiddleware(_StubMiddleware):
        """模型重试中间件；按可重试错误和次数限制重新调用，避免对有副作用的工具动作盲目重放。"""
        pass

    class PIIMiddleware(_StubMiddleware):
        """个人信息保护中间件；在模型和工具边界前后执行脱敏或拦截，避免原始 PII 进入不必要的日志和外部追踪。"""
        pass

    class ToolCallLimitMiddleware(_StubMiddleware):
        """工具调用次数治理中间件；限制单次运行的工具调用量，并与权限、审批和审计校验叠加而非替代。"""
        pass


def permission_middleware(tool_permissions: dict[str, Collection[str]]):
    """在实际工具调用时复核可信 Runtime context 中的权限。"""

    @wrap_tool_call
    async def enforce_permissions(request: Any, handler: Any):
        """在工具调用边界校验当前用户权限和工具契约，阻止未授权副作用。

        Args:
            request: 请求对象。
            handler: 处理器。
        """
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
