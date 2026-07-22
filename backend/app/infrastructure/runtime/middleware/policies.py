"""跨模型与工具调用的默认运行策略。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    """定义策略规则。"""
    redact_secrets: bool = True
    trace_calls: bool = True
    require_confirmation_for_external_tools: bool = True
    max_model_calls: int = 2
    max_tool_calls: int = 20
    retry_idempotent_tools: int = 1
