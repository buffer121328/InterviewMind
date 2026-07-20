"""统一错误分类。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCategory(StrEnum):
    NETWORK = "network_failure"
    AUTHENTICATION = "authentication_failure"
    RATE_LIMIT = "rate_limited"
    QUOTA = "quota_exceeded"
    OUTPUT_CONTRACT = "output_contract_failure"
    PROVIDER = "provider_failure"
    INTERNAL = "internal_error"


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    category: ErrorCategory
    code: str
    user_message: str


NETWORK_KEYWORDS = (
    "timeout",
    "timed out",
    "connection",
    "connecterror",
    "connect timeout",
    "readtimeout",
    "network",
    "dns",
    "name resolution",
)
OUTPUT_CONTRACT_KEYWORDS = (
    "validation error",
    "pydantic",
    "jsondecodeerror",
    "invalid json",
    "output contract",
    "schema validation",
    "structured output",
)
AUTH_KEYWORDS = ("api key", "authentication", "unauthorized", "401", "invalid key")
RATE_LIMIT_KEYWORDS = ("rate limit", "ratelimit", "429", "too many requests")
QUOTA_KEYWORDS = ("insufficient", "quota", "balance", "billing", "payment required")
PROVIDER_KEYWORDS = (
    "provider",
    "upstream",
    "bad gateway",
    "502",
    "503",
    "504",
    "service unavailable",
    "model overloaded",
)


def classify_error_message(message: str) -> ClassifiedError:
    """将已脱敏错误文本分类为稳定错误码和用户提示。"""
    lowered = message.lower()
    if any(keyword in lowered for keyword in AUTH_KEYWORDS):
        return ClassifiedError(
            ErrorCategory.AUTHENTICATION,
            "AuthenticationError",
            "API Key 无效或未配置，请检查设置",
        )
    if any(keyword in lowered for keyword in RATE_LIMIT_KEYWORDS):
        return ClassifiedError(
            ErrorCategory.RATE_LIMIT,
            "RateLimitError",
            "API 请求过于频繁，请稍后重试",
        )
    if any(keyword in lowered for keyword in QUOTA_KEYWORDS):
        return ClassifiedError(
            ErrorCategory.QUOTA,
            "QuotaError",
            "API 余额不足，请充值后重试",
        )
    if any(keyword in lowered for keyword in NETWORK_KEYWORDS):
        return ClassifiedError(
            ErrorCategory.NETWORK,
            "NetworkError",
            "网络连接失败，请稍后重试",
        )
    if any(keyword in lowered for keyword in OUTPUT_CONTRACT_KEYWORDS):
        return ClassifiedError(
            ErrorCategory.OUTPUT_CONTRACT,
            "OutputContractError",
            "模型输出格式不符合预期，请重试",
        )
    if any(keyword in lowered for keyword in PROVIDER_KEYWORDS):
        return ClassifiedError(
            ErrorCategory.PROVIDER,
            "ProviderError",
            "模型服务暂时不可用，请稍后重试",
        )
    return ClassifiedError(
        ErrorCategory.INTERNAL,
        "InternalServerError",
        f"处理失败: {message[:100]}",
    )
