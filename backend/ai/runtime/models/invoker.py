"""统一模型调用入口。"""

from typing import Any, TypeVar

from pydantic import BaseModel

from ai.runtime.context import AgentContext
from .resolver import ModelRequest

T = TypeVar("T", bound=BaseModel)


class ModelInvoker:
    """表示 `ModelInvoker` 相关的数据或行为。"""
    async def structured(
        self,
        input_value: Any,
        output_model: type[T],
        context: AgentContext,
        request: ModelRequest | None = None,
        *,
        max_retries: int = 2,
    ) -> T:
        """异步执行 `structured` 相关逻辑。

        Args:
            input_value: 调用方传入的 `input_value` 参数。
            output_model: 调用方传入的 `output_model` 参数。
            context: 运行上下文。
            request: 请求对象。
            max_retries: 调用方传入的 `max_retries` 参数。
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
