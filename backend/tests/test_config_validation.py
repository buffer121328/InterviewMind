"""API 配置验证应复用统一模型工厂。"""

import pytest

from app.api import config as config_api
from app.schemas.schemas import ApiConfigValidateRequest
from ai.workflows import config as config_workflow


class _FakeLLM:
    def __init__(self, result="OK"):
        self.result = result
        self.inputs = []

    async def ainvoke(self, value):
        self.inputs.append(value)
        return self.result


@pytest.mark.asyncio
async def test_validate_api_config_uses_unified_llm_factory(monkeypatch):
    captured = {}
    fake_llm = _FakeLLM()

    def fake_create_llm_from_config(**kwargs):
        captured.update(kwargs)
        return fake_llm

    monkeypatch.setattr(config_workflow, "create_llm_from_config", fake_create_llm_from_config)

    result = await config_api.validate_api_config(
        ApiConfigValidateRequest(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="test-model",
        )
    )

    assert result["success"] is True
    assert captured == {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "model": "test-model",
        "temperature": 0,
        "max_tokens": 10,
        "timeout": 10,
    }
    assert fake_llm.inputs == ["Say 'OK' in one word."]


@pytest.mark.asyncio
async def test_validate_api_config_keeps_friendly_error_message(monkeypatch):
    class FailingLLM:
        async def ainvoke(self, _value):
            raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(config_workflow, "create_llm_from_config", lambda **_kwargs: FailingLLM())

    result = await config_api.validate_api_config(
        ApiConfigValidateRequest(
            api_key="bad-key",
            base_url="https://example.invalid/v1",
            model="test-model",
        )
    )

    assert result == {"success": False, "message": "API Key 无效，请检查是否正确"}
