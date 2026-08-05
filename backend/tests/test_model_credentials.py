"""Local Redis model credential storage and request hydration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.security.model_credential_middleware import ModelCredentialHydrationMiddleware
from app.security.model_credentials import ModelCredentialStore, ModelCredentialStoreUnavailable


class _FakeRedis:
    """Small Redis substitute supporting final String keys plus legacy Hash migration."""

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool | None:
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self.strings:
            return False
        self.ttls[key] = seconds
        return True

    async def hget(self, name: str, key: str) -> str | None:
        return self.hashes.get(name, {}).get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += int(key in self.strings or key in self.hashes)
            self.strings.pop(key, None)
            self.hashes.pop(key, None)
            self.ttls.pop(key, None)
        return deleted


@pytest.mark.asyncio
async def test_store_uses_model_name_string_key_with_api_key_only() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis)  # type: ignore[arg-type]

    status = await store.put("user-a", "deepseek-v4-flash", "test-secret-value")

    assert redis.strings == {
        "agent_interview:model_credentials:v1:deepseek-v4-flash": "test-secret-value"
    }
    assert redis.hashes == {}
    assert status.model_name == "deepseek-v4-flash"
    assert status.stored is True
    assert status.expires_at is not None
    assert redis.ttls["agent_interview:model_credentials:v1:deepseek-v4-flash"] == 30 * 24 * 60 * 60
    assert await store.get("user-b", "deepseek-v4-flash") == "test-secret-value"


@pytest.mark.asyncio
async def test_successful_reads_and_status_checks_refresh_sliding_ttl() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis, ttl_seconds=120)  # type: ignore[arg-type]
    key = "agent_interview:model_credentials:v1:deepseek-v4-flash"
    await store.put("user-a", "deepseek-v4-flash", "test-secret-value")

    redis.ttls.pop(key)
    assert await store.get("user-a", "deepseek-v4-flash") == "test-secret-value"
    assert redis.ttls[key] == 120

    redis.ttls[key] = 5
    statuses = await store.statuses("user-a", [("deepseek-v4-flash", None)])
    assert statuses[0].stored is True
    assert statuses[0].expires_at is not None
    assert redis.ttls[key] == 120


@pytest.mark.asyncio
async def test_status_and_delete_use_same_global_model_name_key() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis)  # type: ignore[arg-type]
    await store.put("user-a", "deepseek-v4-flash", "test-secret-value")

    statuses = await store.statuses(
        "another-local-user",
        [("deepseek-v4-flash", None), ("missing-model", None)],
    )

    assert [(item.model_name, item.stored) for item in statuses] == [
        ("deepseek-v4-flash", True),
        ("missing-model", False),
    ]
    assert statuses[0].expires_at is not None
    assert statuses[1].expires_at is None
    assert await store.delete("user-b", "deepseek-v4-flash") is True
    assert redis.strings == {}


@pytest.mark.asyncio
async def test_legacy_uuid_hash_migrates_to_model_name_without_reentry() -> None:
    redis = _FakeRedis()
    legacy_id = "e8cbbb31-6df1-4ccb-bd08-41a85097f94e"
    legacy_key = f"agent_interview:model_credentials:v1:model:{legacy_id}"
    redis.hashes["agent_interview:model_credentials:v1:channels"] = {"mem0_llm": legacy_id}
    redis.hashes[legacy_key] = {
        "id": legacy_id,
        "model": "deepseek-v4-flash",
        "api_key": "migrated-secret",
    }
    store = ModelCredentialStore(redis)  # type: ignore[arg-type]

    assert await store.get(
        "ignored-user",
        "deepseek-v4-flash",
        legacy_id=legacy_id,
    ) == "migrated-secret"

    assert redis.strings == {
        "agent_interview:model_credentials:v1:deepseek-v4-flash": "migrated-secret"
    }
    assert redis.ttls["agent_interview:model_credentials:v1:deepseek-v4-flash"] == 30 * 24 * 60 * 60
    assert legacy_key not in redis.hashes
    assert "agent_interview:model_credentials:v1:channels" not in redis.hashes


def test_middleware_hydrates_credential_reference_before_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ASGI middleware rewrites JSON bodies before endpoint parsing."""

    store = AsyncMock()
    store.get.return_value = "resolved-test-key"
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/business")
    async def echo_api_config(request: Request) -> dict:
        """Echo the hydrated payload for the middleware contract test."""

        return await request.json()

    response = TestClient(app).post(
        "/business",
        headers={"X-User-ID": "user-a"},
        json={
            "api_config": {
                "smart": {
                    "credential_id": "example-model",
                    "legacy_credential_id": "model-1",
                    "base_url": "https://example.test/v1",
                    "model": "example-model",
                }
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["api_config"]["smart"]["api_key"] == "resolved-test-key"
    store.get.assert_awaited_once_with("user-a", "example-model", legacy_id="model-1")


def test_middleware_fails_closed_for_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing local Redis key stops the business request before it reaches the endpoint."""

    store = AsyncMock()
    store.get.return_value = None
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/business")
    async def unreachable() -> dict[str, bool]:
        """Represent a route that must not run with an expired credential."""

        return {"reached": True}

    response = TestClient(app).post(
        "/business",
        json={"api_config": {"smart": {"credential_id": "example-model", "model": "example-model"}}},
    )

    assert response.status_code == 401
    assert "模型设置中填写" in response.json()["detail"]


def test_memory_middleware_ignores_unrelated_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory routes hydrate only mem0/RAG channels instead of failing on unrelated Smart keys."""

    store = AsyncMock()

    async def resolve_key(_user_id: str, model_id: str, **_kwargs) -> str:
        if model_id in {"stale-smart", "stale-rag"}:
            raise ModelCredentialStoreUnavailable("模型凭据读取暂不可用")
        return f"resolved-{model_id}"

    store.get.side_effect = resolve_key
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/api/memory/list")
    async def echo_memory_request(request: Request) -> dict:
        return await request.json()

    response = TestClient(app).post(
        "/api/memory/list",
        headers={"X-User-ID": "user-a"},
        json={
            "page_size": 100,
            "api_config": {
                "smart": {"credential_id": "stale-smart"},
                "fast": {"credential_id": "stale-smart"},
                "mem0_llm": {
                    "credential_id": "memory-llm",
                    "base_url": "https://llm.example.test/v1",
                    "model": "memory-llm-model",
                },
                "mem0_embedder": {
                    "credential_id": "memory-embedder",
                    "base_url": "https://embedding.example.test/v1",
                    "model": "memory-embedding-model",
                },
                "rag_embedding": {
                    "credential_id": "stale-rag",
                    "base_url": "https://stale.example.test/v1",
                    "model": "stale-embedding-model",
                },
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["api_config"]
    assert "api_key" not in config["smart"]
    assert config["mem0_llm"]["api_key"] == "resolved-memory-llm-model"
    assert config["mem0_embedder"]["api_key"] == "resolved-memory-embedding-model"
    assert [call.args[1] for call in store.get.await_args_list] == [
        "memory-llm-model",
        "memory-embedding-model",
    ]


def test_memory_middleware_fails_closed_for_required_invalid_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid credential selected by a memory channel still stops the request."""

    store = AsyncMock()
    store.get.side_effect = ModelCredentialStoreUnavailable("模型凭据读取暂不可用")
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/api/memory/list")
    async def unreachable_memory_route() -> dict[str, bool]:
        return {"reached": True}

    response = TestClient(app).post(
        "/api/memory/list",
        json={
            "api_config": {
                "smart": {"credential_id": "valid-but-unneeded"},
                "fast": {"credential_id": "valid-but-unneeded"},
                "mem0_llm": {"credential_id": "stale-memory-llm", "model": "stale-memory-llm"},
            }
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "模型凭据读取暂不可用"
    store.get.assert_awaited_once_with("default_user", "stale-memory-llm", legacy_id=None)


def test_memory_middleware_hydrates_rag_embedding_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG embedding is hydrated only when the dedicated mem0 embedder is absent."""

    store = AsyncMock()
    store.get.side_effect = lambda _user_id, model_id, **_kwargs: f"resolved-{model_id}"
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/api/memory/list")
    async def echo_rag_fallback(request: Request) -> dict:
        return await request.json()

    response = TestClient(app).post(
        "/api/memory/list",
        json={
            "api_config": {
                "smart": {"credential_id": "unneeded-smart"},
                "fast": {"credential_id": "unneeded-fast"},
                "mem0_llm": {
                    "credential_id": "memory-llm",
                    "base_url": "https://llm.example.test/v1",
                    "model": "memory-llm-model",
                },
                "mem0_embedder": None,
                "rag_embedding": {
                    "credential_id": "rag-embedder",
                    "base_url": "https://embedding.example.test/v1",
                    "model": "rag-embedding-model",
                },
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["api_config"]["rag_embedding"]["api_key"] == "resolved-rag-embedding-model"
    assert [call.args[1] for call in store.get.await_args_list] == [
        "memory-llm-model",
        "rag-embedding-model",
    ]
