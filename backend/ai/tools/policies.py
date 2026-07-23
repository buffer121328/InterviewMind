"""工具安全策略类型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """定义策略规则。"""
    timeout_seconds: float = 30.0
    max_result_chars: int = 20_000
    require_confirmation_for_external: bool = True
