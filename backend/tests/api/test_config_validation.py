"""API 配置验证应复用统一模型工厂。"""

import pytest
from fastapi import Request
from pydantic import ValidationError

from app.api import config as config_api
from app.schemas.schemas import ApiConfigValidateRequest
from ai.workflows.configuration import api_validation as config_workflow


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
async def test_validate_api_config_preserves_volcengine_provider_metadata(monkeypatch):
    captured = {}

    def fake_create_llm_from_config(**kwargs):
        captured.update(kwargs)
        return _FakeLLM()

    monkeypatch.setattr(config_workflow, "create_llm_from_config", fake_create_llm_from_config)

    result = await config_api.validate_api_config(
        ApiConfigValidateRequest(
            api_key="test-key",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model="doubao-seed-1-6-250615",
            provider="volcengine",
            integration="openai_compatible",
        )
    )

    assert result["success"] is True
    assert captured["provider"] == "volcengine"
    assert captured["integration"] == "openai_compatible"


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


@pytest.mark.asyncio
async def test_validate_embedding_uses_requested_dimensions_and_checks_response(monkeypatch):
    captured = {}

    class _EmbeddingItem:
        embedding = [0.1, 0.2]

    class _EmbeddingResponse:
        data = [_EmbeddingItem()]

    async def fake_create_embeddings(input_value, **kwargs):
        captured.update({"input": input_value, **kwargs})
        return _EmbeddingResponse()

    monkeypatch.setattr(
        config_workflow.llms.model_gateway,
        "create_embeddings",
        fake_create_embeddings,
    )

    result = await config_api.validate_api_config(
        ApiConfigValidateRequest(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="embed-model",
            kind="embedding",
            dimensions=2,
        )
    )

    assert result["success"] is True
    assert result["dimensions"] == 2
    assert captured["api_config"]["rag_embedding"]["dimensions"] == 2


@pytest.mark.asyncio
async def test_validate_embedding_rejects_provider_dimension_mismatch(monkeypatch):
    class _EmbeddingItem:
        embedding = [0.1]

    class _EmbeddingResponse:
        data = [_EmbeddingItem()]

    async def fake_create_embeddings(*_args, **_kwargs):
        return _EmbeddingResponse()

    monkeypatch.setattr(
        config_workflow.llms.model_gateway,
        "create_embeddings",
        fake_create_embeddings,
    )

    result = await config_api.validate_api_config(
        ApiConfigValidateRequest(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="embed-model",
            kind="embedding",
            dimensions=2,
        )
    )

    assert result["success"] is False
    assert "维度不匹配" in str(result["message"])


def test_embedding_dimension_schema_accepts_legacy_and_rejects_invalid_values():
    legacy = ApiConfigValidateRequest(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="embed-model",
        kind="embedding",
    )
    assert legacy.dimensions is None

    for value in (0, -1, 16001, 1.5):
        with pytest.raises(ValidationError):
            ApiConfigValidateRequest(
                api_key="test-key",
                base_url="https://example.invalid/v1",
                model="embed-model",
                kind="embedding",
                dimensions=value,
            )


@pytest.mark.asyncio
async def test_validate_api_config_redacts_upstream_secret_in_message_and_log(monkeypatch, caplog):
    fixture_key = "fixture-sk-leaky-987654321"

    class LeakyLLM:
        async def ainvoke(self, _value):
            raise RuntimeError(f"upstream rejected key {fixture_key} for https://example.invalid/v1")

    monkeypatch.setattr(config_workflow, "create_llm_from_config", lambda **_kwargs: LeakyLLM())

    with caplog.at_level("WARNING"):
        result = await config_api.validate_api_config(
            ApiConfigValidateRequest(
                api_key=fixture_key,
                base_url="https://example.invalid/v1",
                model="test-model",
            )
        )

    assert result["success"] is False
    assert fixture_key not in result["message"]
    assert fixture_key not in caplog.text


def test_config_validate_guard_rejects_oversized_body():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.security.config_validate_guard import ConfigValidateGuardMiddleware

    app = FastAPI()
    app.add_middleware(ConfigValidateGuardMiddleware)

    @app.post("/api/config/validate")
    async def echo(request: Request) -> dict:
        return {"reached": True}

    client = TestClient(app)
    payload = {"pad": "x" * (9 * 1024)}
    response = client.post(
        "/api/config/validate",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "请求体过大"


def test_config_validate_guard_rejects_oversized_content_length():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.security.config_validate_guard import ConfigValidateGuardMiddleware

    app = FastAPI()
    app.add_middleware(ConfigValidateGuardMiddleware)
    reached = False

    @app.post("/api/config/validate")
    async def echo(request: Request) -> dict:
        nonlocal reached
        reached = True
        return {"reached": True}

    client = TestClient(app)
    response = client.post(
        "/api/config/validate",
        content=b"x" * (9 * 1024),
        headers={"Content-Type": "application/json", "Content-Length": str(9 * 1024)},
    )
    assert response.status_code == 413
    assert reached is False


def test_config_validate_guard_rate_limits_burst():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.security.config_validate_guard import ConfigValidateGuardMiddleware

    app = FastAPI()
    app.add_middleware(ConfigValidateGuardMiddleware)

    @app.post("/api/config/validate")
    async def echo(request: Request) -> dict:
        return {"reached": True}

    client = TestClient(app)
    statuses = [
        client.post("/api/config/validate", json={}).status_code for _ in range(25)
    ]
    assert statuses[:5] == [200] * 5
    assert 429 in statuses


def test_config_validate_guard_leaves_other_routes_untouched():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.security.config_validate_guard import ConfigValidateGuardMiddleware

    app = FastAPI()
    app.add_middleware(ConfigValidateGuardMiddleware)

    @app.post("/api/business")
    async def business(request: Request) -> dict:
        return {"ok": True}

    client = TestClient(app)
    big = {"pad": "x" * (20 * 1024)}
    assert client.post("/api/business", json=big).status_code == 200
