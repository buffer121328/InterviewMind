"""Security and request hydration tests for Redis-backed model credentials."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.security.model_credential_middleware import ModelCredentialHydrationMiddleware
from app.security.model_credentials import ModelCredentialStore


class _FakePipeline:
    """Minimal async Redis pipeline for TTL status tests."""

    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._keys: list[str] = []

    def ttl(self, key: str) -> "_FakePipeline":
        """Queue a TTL lookup."""

        self._keys.append(key)
        return self

    async def execute(self) -> list[int]:
        """Return deterministic TTLs for queued keys."""

        return [self._redis.ttls.get(key, -2) for key in self._keys]


class _FakeRedis:
    """Small in-memory Redis substitute that preserves encrypted values for assertions."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        """Store one value with its TTL."""

        self.values[key] = value
        self.ttls[key] = ex

    async def get(self, key: str) -> str | None:
        """Return one stored value."""

        return self.values.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Return multiple stored values."""

        return [self.values.get(key) for key in keys]

    async def delete(self, *keys: str) -> int:
        """Delete stored values and return the number that existed."""

        deleted = 0
        for key in keys:
            deleted += int(key in self.values)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return deleted

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        """Create a non-transactional TTL pipeline."""

        assert transaction is False
        return _FakePipeline(self)


@pytest.fixture
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure an ephemeral Fernet key without exposing a real credential."""

    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.mark.asyncio
async def test_store_encrypts_key_scopes_owner_and_applies_thirty_day_ttl(encryption_key: None) -> None:
    """Plaintext never reaches Redis and another user cannot resolve the credential."""

    redis = _FakeRedis()
    store = ModelCredentialStore(redis, 30 * 24 * 60 * 60)  # type: ignore[arg-type]

    await store.put("user-a", "model-1", "test-secret-value")

    assert all("test-secret-value" not in value for value in redis.values.values())
    assert list(redis.ttls.values()) == [2_592_000]
    assert await store.get("user-a", "model-1") == "test-secret-value"
    assert await store.get("user-b", "model-1") is None


@pytest.mark.asyncio
async def test_status_and_delete_return_metadata_without_secret(encryption_key: None) -> None:
    """Status and deletion expose no key material and preserve owner isolation."""

    redis = _FakeRedis()
    store = ModelCredentialStore(redis, 2_592_000)  # type: ignore[arg-type]
    await store.put("user-a", "model-1", "test-secret-value")

    statuses = await store.statuses("user-a", ["model-1", "model-2"])

    assert [(item.model_id, item.stored) for item in statuses] == [("model-1", True), ("model-2", False)]
    assert "test-secret-value" not in repr(statuses)
    assert await store.delete("user-a", "model-1") is True
    assert await store.get("user-a", "model-1") is None


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
                    "credential_id": "model-1",
                    "base_url": "https://example.test/v1",
                    "model": "example-model",
                }
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["api_config"]["smart"]["api_key"] == "resolved-test-key"
    store.get.assert_awaited_once_with("user-a", "model-1")


def test_middleware_fails_closed_for_expired_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing Redis key stops the business request before it reaches the endpoint."""

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
        json={"api_config": {"smart": {"credential_id": "model-1"}}},
    )

    assert response.status_code == 401
    assert "重新填写" in response.json()["detail"]
