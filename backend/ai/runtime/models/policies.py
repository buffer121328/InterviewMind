"""模型可靠性策略。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelCallPolicy:
    """定义策略规则。"""
    timeout_seconds: int = 45
    primary_retries: int = 2
    allow_fallback: bool = True
