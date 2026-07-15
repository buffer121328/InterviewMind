"""工具输出的提示注入隔离中间件。"""

from __future__ import annotations

import re
from typing import Any

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage


_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
        r"reveal\s+(the\s+)?(system|developer)\s+(prompt|message)",
        r"\b(prompt\s*injection|jailbreak)\b",
        r"忽略.{0,16}(之前|以上|原有).{0,16}(指令|提示词|规则)",
        r"(泄露|输出|显示).{0,16}(系统|开发者).{0,16}(提示词|指令|消息)",
        r"<\|(?:im_start|system|assistant)\|>",
    )
)


def contains_prompt_injection(value: Any) -> bool:
    """递归检查工具输出中的高置信度注入特征。"""
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _INJECTION_PATTERNS)
    if isinstance(value, dict):
        return any(contains_prompt_injection(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_prompt_injection(item) for item in value)
    return False


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
