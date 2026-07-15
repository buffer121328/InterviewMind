"""把业务模型请求解析为有序候选模型。"""

from dataclasses import dataclass
from typing import Any, Mapping

from app.agent_runtime.context import AgentContext


@dataclass(frozen=True, slots=True)
class ModelRequest:
    channel: str = "smart"
    capability: str = "structured_output"
    temperature: float = 0.7
    max_tokens: int = 8000


class ModelResolver:
    """保留现有通道回退语义的统一解析入口。"""

    def resolve(self, request: ModelRequest, context: AgentContext) -> list[Any]:
        from app.services.llms import get_llm_candidates_for_request

        return get_llm_candidates_for_request(
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
        return self.resolve(
            request,
            AgentContext(user_id=user_id, api_config=api_config),
        )
