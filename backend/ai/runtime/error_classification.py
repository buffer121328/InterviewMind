"""统一运行时失败分类，供重试、fallback、HTTP 映射和安全观测复用。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from json import JSONDecodeError

from pydantic import ValidationError


class ErrorCategory(StrEnum):
    """面向现有 API 的粗粒度错误类别；枚举值保持向后兼容。"""

    NETWORK = "network_failure"
    AUTHENTICATION = "authentication_failure"
    RATE_LIMIT = "rate_limited"
    QUOTA = "quota_exceeded"
    OUTPUT_CONTRACT = "output_contract_failure"
    PROVIDER = "provider_failure"
    INTERNAL = "internal_error"


class FailureType(StrEnum):
    """面向运行时治理的细粒度失败类型，决定是否重试或切换候选。"""

    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    SCHEMA_VALIDATION_ERROR = "schema_validation_error"
    JSON_PARSE_ERROR = "json_parse_error"
    PARTIAL_OUTPUT = "partial_output"
    BUSINESS_VALIDATION_ERROR = "business_validation_error"
    PROVIDER_REJECTION = "provider_rejection"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    """稳定错误码、用户提示与运行时重试/fallback 决策。"""

    category: ErrorCategory
    code: str
    user_message: str
    failure_type: FailureType
    retryable: bool
    fallback_allowed: bool


TIMEOUT_KEYWORDS = (
    "timeout",
    "timed out",
    "readtimeout",
    "connect timeout",
    "deadline exceeded",
)
NETWORK_KEYWORDS = (
    "connection",
    "connecterror",
    "network",
    "dns",
    "name resolution",
)
JSON_PARSE_KEYWORDS = (
    "jsondecodeerror",
    "invalid json",
    "json parse",
    "malformed json",
)
OUTPUT_CONTRACT_KEYWORDS = (
    "outputparserexception",
    "output parser",
    "validation error",
    "pydantic",
    "output contract",
    "schema validation",
    "structured output",
)
PARTIAL_OUTPUT_KEYWORDS = (
    "partial output",
    "incomplete output",
    "truncated output",
    "finish_reason=length",
)
BUSINESS_VALIDATION_KEYWORDS = (
    "business validation",
    "business rule",
    "domain validation",
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
    "content policy",
    "request rejected",
)
CANCELLED_KEYWORDS = ("cancelled", "canceled")


def _classified(
    category: ErrorCategory,
    code: str,
    user_message: str,
    failure_type: FailureType,
    *,
    retryable: bool,
    fallback_allowed: bool,
) -> ClassifiedError:
    """构造分类结果，集中保持字段顺序和策略语义。"""
    return ClassifiedError(
        category=category,
        code=code,
        user_message=user_message,
        failure_type=failure_type,
        retryable=retryable,
        fallback_allowed=fallback_allowed,
    )


def classify_error_message(message: str) -> ClassifiedError:
    """将已脱敏错误文本分类为稳定错误码、失败类型和重试策略。"""
    lowered = message.lower()
    if any(keyword in lowered for keyword in CANCELLED_KEYWORDS):
        return _classified(
            ErrorCategory.INTERNAL,
            "CancelledError",
            "任务已取消",
            FailureType.CANCELLED,
            retryable=False,
            fallback_allowed=False,
        )
    if any(keyword in lowered for keyword in AUTH_KEYWORDS):
        return _classified(
            ErrorCategory.AUTHENTICATION,
            "AuthenticationError",
            "API Key 无效或未配置，请检查设置",
            FailureType.PROVIDER_REJECTION,
            retryable=False,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in RATE_LIMIT_KEYWORDS):
        return _classified(
            ErrorCategory.RATE_LIMIT,
            "RateLimitError",
            "API 请求过于频繁，请稍后重试",
            FailureType.PROVIDER_REJECTION,
            retryable=False,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in QUOTA_KEYWORDS):
        return _classified(
            ErrorCategory.QUOTA,
            "QuotaError",
            "API 余额不足，请充值后重试",
            FailureType.PROVIDER_REJECTION,
            retryable=False,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in TIMEOUT_KEYWORDS):
        return _classified(
            ErrorCategory.NETWORK,
            "NetworkError",
            "模型请求超时，请稍后重试",
            FailureType.TIMEOUT,
            retryable=True,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in NETWORK_KEYWORDS):
        return _classified(
            ErrorCategory.NETWORK,
            "NetworkError",
            "网络连接失败，请稍后重试",
            FailureType.NETWORK_ERROR,
            retryable=True,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in OUTPUT_CONTRACT_KEYWORDS):
        return _classified(
            ErrorCategory.OUTPUT_CONTRACT,
            "OutputContractError",
            "模型输出格式不符合预期，请重试",
            FailureType.SCHEMA_VALIDATION_ERROR,
            retryable=True,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in JSON_PARSE_KEYWORDS):
        return _classified(
            ErrorCategory.OUTPUT_CONTRACT,
            "JsonParseError",
            "模型输出不是有效 JSON，请重试",
            FailureType.JSON_PARSE_ERROR,
            retryable=True,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in PARTIAL_OUTPUT_KEYWORDS):
        return _classified(
            ErrorCategory.OUTPUT_CONTRACT,
            "PartialOutputError",
            "模型输出不完整，请重试",
            FailureType.PARTIAL_OUTPUT,
            retryable=True,
            fallback_allowed=True,
        )
    if any(keyword in lowered for keyword in BUSINESS_VALIDATION_KEYWORDS):
        return _classified(
            ErrorCategory.INTERNAL,
            "BusinessValidationError",
            "结果未通过业务规则校验",
            FailureType.BUSINESS_VALIDATION_ERROR,
            retryable=False,
            fallback_allowed=False,
        )
    if any(keyword in lowered for keyword in PROVIDER_KEYWORDS):
        return _classified(
            ErrorCategory.PROVIDER,
            "ProviderError",
            "模型服务暂时不可用，请稍后重试",
            FailureType.PROVIDER_REJECTION,
            retryable=False,
            fallback_allowed=True,
        )
    return _classified(
        ErrorCategory.INTERNAL,
        "InternalServerError",
        f"处理失败: {message[:100]}",
        FailureType.INTERNAL_ERROR,
        retryable=True,
        fallback_allowed=True,
    )


def classify_exception(error: BaseException) -> ClassifiedError:
    """优先按异常类型分类，再使用已脱敏消息补足供应商错误语义。"""
    if isinstance(error, asyncio.CancelledError):
        return _classified(
            ErrorCategory.INTERNAL,
            "CancelledError",
            "任务已取消",
            FailureType.CANCELLED,
            retryable=False,
            fallback_allowed=False,
        )
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return _classified(
            ErrorCategory.NETWORK,
            "TimeoutError",
            "模型请求超时，请稍后重试",
            FailureType.TIMEOUT,
            retryable=True,
            fallback_allowed=True,
        )
    if isinstance(error, JSONDecodeError):
        return _classified(
            ErrorCategory.OUTPUT_CONTRACT,
            "JsonParseError",
            "模型输出不是有效 JSON，请重试",
            FailureType.JSON_PARSE_ERROR,
            retryable=True,
            fallback_allowed=True,
        )
    if isinstance(error, ValidationError):
        return _classified(
            ErrorCategory.OUTPUT_CONTRACT,
            "OutputContractError",
            "模型输出格式不符合预期，请重试",
            FailureType.SCHEMA_VALIDATION_ERROR,
            retryable=True,
            fallback_allowed=True,
        )
    if isinstance(error, (ConnectionError, OSError)):
        return _classified(
            ErrorCategory.NETWORK,
            "NetworkError",
            "网络连接失败，请稍后重试",
            FailureType.NETWORK_ERROR,
            retryable=True,
            fallback_allowed=True,
        )
    # 异常正文不一定包含类型名；始终拼入类名，确保 OutputParserException
    # 等结构化输出异常可以稳定进入本地兜底，而不是被误判为内部错误。
    return classify_error_message(f"{type(error).__name__}: {error}")
