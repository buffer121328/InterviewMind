"""统一错误分类测试。"""

import pytest

from app.application.interview.start import InterviewStartUseCases
from app.services.error_classification import ErrorCategory, classify_error_message


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
