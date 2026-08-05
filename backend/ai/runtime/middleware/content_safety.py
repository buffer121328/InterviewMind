"""工具输出的提示注入隔离中间件。"""

from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover - 运行时可选依赖
    from langchain.agents.middleware import wrap_tool_call
    from langchain_core.messages import ToolMessage
except ModuleNotFoundError:  # pragma: no cover - 轻量测试环境
    wrap_tool_call = None
    ToolMessage = Any


_COMMAND_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"reveal\s+(the\s+)?(system|developer)\s+(prompt|message)",
        r"忽略.{0,16}(之前|以上|原有).{0,16}(指令|提示词|规则)",
        r"(泄露|输出|显示).{0,16}(系统|开发者).{0,16}(提示词|指令|消息)",
        r"<\|(?:im_start|system|assistant)\|>",
    )
)
_SECURITY_TERM_PATTERNS = (
    re.compile(r"\b(prompt\s*injection|jailbreak)\b", re.IGNORECASE | re.DOTALL),
)
_INJECTION_PATTERNS = _COMMAND_INJECTION_PATTERNS + _SECURITY_TERM_PATTERNS


def contains_prompt_injection(value: Any, *, allow_security_terms: bool = False) -> bool:
    """Recursively detect executable injection; trusted documents may name security concepts."""
    patterns = _COMMAND_INJECTION_PATTERNS if allow_security_terms else _INJECTION_PATTERNS
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in patterns)
    if isinstance(value, dict):
        return any(
            contains_prompt_injection(item, allow_security_terms=allow_security_terms)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(
            contains_prompt_injection(item, allow_security_terms=allow_security_terms)
            for item in value
        )
    return False


if wrap_tool_call is not None:

    @wrap_tool_call
    async def prompt_injection_middleware(request: Any, handler: Any):
        """不将被判定为注入的工具输出交给模型。"""
        response = await handler(request)
        if isinstance(response, ToolMessage) and contains_prompt_injection(response.content):
            return response.model_copy(
                update={
                    "content": "[BLOCKED] 工具输出包含可疑的指令注入，已隔离。",
                    "status": "error",
                }
            )
        return response

else:

    async def prompt_injection_middleware(request: Any, handler: Any):  # pragma: no cover - 轻量测试环境
        """轻量测试环境下的占位实现。"""
        return await handler(request)
