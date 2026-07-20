"""统一模型调用入口。"""

from typing import Any, TypeVar

from pydantic import BaseModel

from app.infrastructure.runtime.context import AgentContext
from .resolver import ModelRequest

T = TypeVar("T", bound=BaseModel)


class ModelInvoker:
    async def structured(
        self,
        input_value: Any,
        output_model: type[T],
        context: AgentContext,
        request: ModelRequest | None = None,
        *,
        max_retries: int = 2,
    ) -> T:
        from app.infrastructure.llm.llm_utils import invoke_structured, invoke_structured_with_messages

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
