"""AgentRun 治理审计载荷的最小化与脱敏。"""

from typing import Any

from app.security.security import redact_secrets


def _sanitize_governance_payload(value: Any, *, max_text_chars: int = 300) -> Any:
    """递归脱敏和截断治理审计载荷。"""

    value = redact_secrets(value)
    if isinstance(value, str):
        return value[:max_text_chars]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _sanitize_governance_payload(
                item, max_text_chars=max_text_chars
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_governance_payload(item, max_text_chars=max_text_chars)
            for item in value[:20]
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_governance_payload(item, max_text_chars=max_text_chars)
            for item in value[:20]
        ]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_text_chars]
