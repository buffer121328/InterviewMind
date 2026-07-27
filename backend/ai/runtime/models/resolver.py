"""把业务模型请求解析为有序候选模型。"""

from dataclasses import dataclass
from typing import Any, Mapping

from ai.runtime.context import AgentContext


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """表示请求数据结构。"""
    channel: str = "smart"
    capability: str = "structured_output"
    temperature: float = 0.7
    max_tokens: int = 8000


class ModelResolver:
    """保留现有通道回退语义的统一解析入口。"""

    def resolve(self, request: ModelRequest, context: AgentContext) -> list[Any]:
        """按模型 profile 和请求配置解析可用模型，应用健康检查与 fallback，不把本次选择写入共享配置。

        Args:
            request: 请求对象。
            context: 运行上下文。
        """
        from ai.llm.llms import model_gateway

        return model_gateway.get_chat_candidates(
            api_config=dict(context.api_config),
            channel=request.channel,
        )

    def resolve_config(
        self,
        request: ModelRequest,
        api_config: Mapping[str, Any],
        *,
        user_id: str = "system",
    ) -> list[Any]:
        """解析 `config`。

        Args:
            request: 请求对象。
            api_config: api 配置。
            user_id: 当前用户标识。
        """
        return self.resolve(
            request,
            AgentContext(user_id=user_id, api_config=api_config),
        )
