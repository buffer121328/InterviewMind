"""一次 Agent 执行期间保持不变的上下文。"""

from dataclasses import dataclass, field
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class AgentContext:
    """不向模型暴露的可信运行上下文。"""

    user_id: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    request_id: Optional[str] = None
    api_config: Mapping[str, Any] = field(default_factory=dict)
    permissions: frozenset[str] = field(default_factory=frozenset)
    locale: str = "zh-CN"

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        object.__setattr__(self, "api_config", MappingProxyType(deepcopy(dict(self.api_config))))

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
