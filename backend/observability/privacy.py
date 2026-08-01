"""Langfuse 外发载荷的最小化、标识哈希与秘密字段脱敏。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.security.security import REDACTED, redact_secret_text

_SAFE_TRACE_TEXT_FIELDS = {
    "agent_type",
    "agent_version",
    "browser_channel",
    "error_category",
    "error_code",
    "error_type",
    "event_type",
    "failure_type",
    "mode",
    "model_name",
    "model_provider",
    "next_turn_phase",
    "node",
    "operation",
    "phase",
    "prompt_name",
    "prompt_source",
    "prompt_version",
    "retrieval_mode",
    "round_type",
    "stage",
    "status",
    "task_type",
    "template_style",
    "turn_phase",
    "type",
}
_SAFE_TRACE_TEXT_LIST_FIELDS = {
    "truncated_sources",
}
_SECRET_TRACE_FIELDS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credentials",
    "password",
    "secret",
    "token",
}


def trace_fingerprint(value: str) -> str:
    """为外部 trace 中的标识或敏感原文生成不可逆关联指纹。"""

    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_mapping_key(value: Any, index: int) -> str:
    """Keep ordinary schema keys readable while hashing secret-like or attacker-controlled keys."""

    raw_key = str(value)
    normalized = raw_key.casefold()
    if normalized in _SECRET_TRACE_FIELDS:
        return raw_key[:80]
    if (
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", raw_key)
        and redact_secret_text(raw_key) == raw_key
    ):
        return raw_key
    return f"field_{index}_{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:12]}"


def sanitize_trace_payload(value: Any, *, field_name: str = "") -> Any:
    """把 Agent 自定义载荷收敛为计数、枚举和指纹，禁止任意业务原文进入 Langfuse。"""

    normalized = field_name.casefold()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if normalized in _SECRET_TRACE_FIELDS or normalized.endswith(
            ("_token", "_secret", "_password")
        ):
            return REDACTED
        if normalized == "trace_id":
            return redact_secret_text(value)[:160]
        if normalized == "id" or normalized.endswith("_id"):
            return trace_fingerprint(value)
        if normalized in _SAFE_TRACE_TEXT_FIELDS or normalized.endswith(
            ("_hash", "_fingerprint")
        ):
            return redact_secret_text(value)[:160]
        return {
            "redacted": True,
            "char_count": len(value),
            "fingerprint": trace_fingerprint(value),
        }
    if isinstance(value, Mapping):
        return {
            _safe_mapping_key(key, index): sanitize_trace_payload(item, field_name=str(key))
            for index, (key, item) in enumerate(list(value.items())[:64])
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        if normalized in _SAFE_TRACE_TEXT_LIST_FIELDS:
            return [redact_secret_text(str(item))[:80] for item in value[:32]]
        return {"item_count": len(value)}
    return {"redacted": True, "type": type(value).__name__[:80]}
