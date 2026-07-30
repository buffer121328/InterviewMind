"""生产 Trace 的脱敏与可复现抽样治理。"""

from __future__ import annotations

import hashlib
from typing import Any

from app.security.security import redact_secret_text
from evaluation.domain import OnlineSamplingPolicy

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "authorization",
    "auth_header",
    "password",
    "secret",
}


def sanitize_production_trace(value: Any) -> Any:
    """递归移除凭据并清洗字符串，输出只含可持久化 JSON 值。"""

    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).lower() in _SENSITIVE_KEYS
                else sanitize_production_trace(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_production_trace(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_production_trace(item) for item in value]
    if isinstance(value, str):
        return redact_secret_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def sampling_decision(
    *,
    trace_id: str,
    risk_level: str,
    policy: OnlineSamplingPolicy | None = None,
) -> dict[str, Any]:
    """用稳定哈希决定 Judge/人工抽样；确定性规则始终为 100%。"""

    rates = (policy or OnlineSamplingPolicy()).rates(risk_level=risk_level)
    bucket = int(hashlib.sha256(trace_id.encode()).hexdigest()[:12], 16) / float(
        0xFFFFFFFFFFFF
    )
    return {
        "deterministic": True,
        "judge": bucket < rates.judge_rate,
        "human": bucket < rates.human_review_rate,
        "judge_rate": rates.judge_rate,
        "human_rate": rates.human_review_rate,
        "bucket": bucket,
    }
