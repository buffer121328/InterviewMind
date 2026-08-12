"""统一错误分类测试。"""

import pytest
from unittest.mock import AsyncMock

from ai.runtime.safety.errors import (
    ErrorCategory,
    classify_error_message,
    classify_exception,
)
from ai.workflows.interview.lifecycle.start import InterviewStartUseCases


@pytest.mark.parametrize(
    ("message", "category", "code"),
    [
        ("ConnectTimeout: request timed out", ErrorCategory.NETWORK, "NetworkError"),
        ("HTTP 429 rate limit exceeded", ErrorCategory.RATE_LIMIT, "RateLimitError"),
        ("Validation error: missing field in structured output", ErrorCategory.OUTPUT_CONTRACT, "OutputContractError"),
        ("upstream provider 503 service unavailable", ErrorCategory.PROVIDER, "ProviderError"),
        ("invalid API key unauthorized", ErrorCategory.AUTHENTICATION, "AuthenticationError"),
        ("insufficient quota balance", ErrorCategory.QUOTA, "QuotaError"),
    ],
)
def test_classify_error_message_distinguishes_platform_failures(message, category, code):
    classified = classify_error_message(message)

    assert classified.category == category
    assert classified.code == code
    assert classified.user_message


def test_interview_start_error_classification_reuses_shared_classifier():
    code, message = InterviewStartUseCases._classify_start_error("Validation error: invalid json")

    assert code == "OutputContractError"
    assert message == "模型输出格式不符合预期，请重试"


def test_failure_type_distinguishes_timeout_json_and_business_validation():
    from json import JSONDecodeError

    from pydantic import BaseModel, ValidationError

    from ai.runtime.safety.errors import FailureType, classify_exception

    class Payload(BaseModel):
        count: int

    assert classify_exception(TimeoutError()).failure_type == FailureType.TIMEOUT
    assert classify_exception(JSONDecodeError("bad json", "{", 1)).failure_type == FailureType.JSON_PARSE_ERROR
    with pytest.raises(ValidationError) as exc_info:
        Payload.model_validate({"count": "not-int"})
    assert classify_exception(exc_info.value).failure_type == FailureType.SCHEMA_VALIDATION_ERROR
    business = classify_error_message("business validation failed")
    assert business.failure_type == FailureType.BUSINESS_VALIDATION_ERROR
    assert business.retryable is False
    assert business.fallback_allowed is False


def test_output_parser_exception_is_an_output_contract_failure():
    """LangChain OutputParserException 文案应进入可兜底的输出契约分类。"""
    classified = classify_error_message("OutputParserException: failed to parse JSON output")

    assert classified.category == ErrorCategory.OUTPUT_CONTRACT
    assert classified.code == "OutputContractError"


def test_output_parser_exception_type_is_used_when_message_omits_its_name():
    """异常正文不含类名时，类型名仍应让 JD 分析进入输出契约兜底。"""
    class OutputParserException(RuntimeError):
        """模拟 LangChain 解析异常，但正文只保留供应商输出错误。"""

    classified = classify_exception(OutputParserException("invalid structured output"))

    assert classified.category == ErrorCategory.OUTPUT_CONTRACT
    assert classified.fallback_allowed is True


@pytest.mark.asyncio
async def test_jd_matcher_uses_deterministic_fallback_for_output_parser_failure(monkeypatch):
    """JD 结构化输出解析失败时返回本地证据结果，而不是让整套资产失败。"""
    from ai.agents.resume import jd_matcher

    monkeypatch.setattr(
        jd_matcher,
        "invoke_structured",
        AsyncMock(
            side_effect=RuntimeError("OutputParserException: invalid structured output")
        ),
    )

    result = await jd_matcher.analyze_jd_match(
        resume_content="Python Django FastAPI Agent Redis",
        job_description="需要 Python FastAPI Agent 与 Redis 经验",
        api_config={"smart": {"model": "mock"}},
    )

    assert result["overall_match_score"] > 20
    assert result["selection_hints"]["fallback"] == "deterministic_keyword_overlap"
    assert "Python" in {item.title() for item in result["matched_keywords"]}
