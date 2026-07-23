"""安全相关工具函数。"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "token", "secret", "password"}
REDACTED = "***REDACTED***"


def redact_secrets(value: Any) -> Any:
    """递归脱敏字典/列表/字符串中的密钥。"""
    if isinstance(value, dict):
        return {
            key: (REDACTED if key.lower() in SENSITIVE_KEYS else redact_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


def redact_secret_text(text: str) -> str:
    """脱敏常见文本形式的密钥。"""
    if not text:
        return text

    patterns = [
        r"(api[_-]?key\s*[:=]\s*)([^\s,}]+)",
        r"(authorization\s*[:=]\s*bearer\s+)([^\s,}]+)",
        r"(sk-[A-Za-z0-9_-]{12,})",
    ]
    result = text
    for pattern in patterns:
        if pattern.startswith("(sk-"):
            result = re.sub(pattern, REDACTED, result, flags=re.IGNORECASE)
        else:
            result = re.sub(pattern, rf"\1{REDACTED}", result, flags=re.IGNORECASE)
    return result


def safe_error_message(exc: BaseException, max_len: int = 200) -> str:
    """返回适合日志/响应使用的脱敏异常文本。"""
    return redact_secret_text(str(exc))[:max_len]
