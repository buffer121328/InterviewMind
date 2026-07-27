"""统一模型调用入口。"""

from typing import Any, TypeVar

from pydantic import BaseModel

from ai.runtime.context import AgentContext
from .resolver import ModelRequest

T = TypeVar("T", bound=BaseModel)


class ModelInvoker:
    """统一结构化模型调用入口，负责注入 AgentContext、校验输出 schema 并沿用重试和观测约束；不持有跨请求凭据。"""
    async def structured(
        self,
        input_value: Any,
        output_model: type[T],
        context: AgentContext,
        request: ModelRequest | None = None,
        *,
        max_retries: int = 2,
    ) -> T:
        """执行结构化模型调用并验证返回 schema，保留超时、失败冷却和观测约束。

        Args:
            input_value: 经过类型边界校验的 `input_value`；其格式和可选值由参数类型及调用流程约束。
            output_model: 经过类型边界校验的 `output_model`；其格式和可选值由参数类型及调用流程约束。
            context: 运行上下文。
            request: 请求对象。
            max_retries: 经过类型边界校验的 `max_retries`；其格式和可选值由参数类型及调用流程约束。
        """
        from ai.llm.llm_utils import invoke_structured, invoke_structured_with_messages

        current = request or ModelRequest()
        kwargs = {
            "output_model": output_model,
            "api_config": dict(context.api_config),
            "channel": current.channel,
            "max_retries": max_retries,
        }
        if isinstance(input_value, str):
            return await invoke_structured(input_value, temperature=current.temperature, **kwargs)
        return await invoke_structured_with_messages(input_value, **kwargs)
