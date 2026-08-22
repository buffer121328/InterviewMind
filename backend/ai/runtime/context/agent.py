"""一次 Agent 执行期间保持不变的上下文。"""

from copy import deepcopy
from dataclasses import dataclass, field
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
    runtime_data: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    permissions: frozenset[str] = field(default_factory=frozenset)
    locale: str = "zh-CN"

    def __post_init__(self) -> None:
        """实现 `__post_init__` 协议方法。"""
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        object.__setattr__(self, "api_config", MappingProxyType(deepcopy(dict(self.api_config))))
        object.__setattr__(self, "runtime_data", MappingProxyType(dict(self.runtime_data)))

    def has_permission(self, permission: str) -> bool:
        """判断 `permission` 是否满足条件。

        Args:
            permission: 经过类型边界校验的 `permission`；其格式和可选值由参数类型及调用流程约束。
        """
        return permission in self.permissions
