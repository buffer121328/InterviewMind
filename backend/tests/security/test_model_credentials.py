"""Local Redis model credential storage and request hydration tests."""

from __future__ import annotations

from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.security.model_credential_crypto import (
    ModelCredentialCipher,
    ModelCredentialCryptoError,
    build_model_credential_cipher,
)
from app.security.model_credential_middleware import ModelCredentialHydrationMiddleware
from app.security.model_credentials import ModelCredentialStore, ModelCredentialStoreUnavailable


def _owner_key(user_id: str, model_name: str) -> str:
    owner = sha256(user_id.encode()).hexdigest()
    return f"agent_interview:model_credentials:v1:owner:{owner}:model:{model_name}"


def _cipher() -> ModelCredentialCipher:
    return ModelCredentialCipher(Fernet.generate_key().decode())


class _FakeRedis:
    """Small Redis substitute supporting String keys plus legacy Hash migration."""

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}
        self.fail_set = False

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool | None:
        if self.fail_set:
            from redis.exceptions import RedisError

            raise RedisError("simulated write failure")
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
            if key is None:
                continue
            deleted += int(key in self.strings or key in self.hashes)
            self.strings.pop(key, None)
            self.hashes.pop(key, None)
            self.ttls.pop(key, None)
        return deleted


@pytest.mark.asyncio
async def test_store_writes_owner_scoped_ciphertext_only() -> None:
    redis = _FakeRedis()
    cipher = _cipher()
    store = ModelCredentialStore(redis, cipher)  # type: ignore[arg-type]

    status = await store.put("user-a", "deepseek-v4-flash", "test-secret-value")

    key = _owner_key("user-a", "deepseek-v4-flash")
    assert set(redis.strings) == {key}
    assert redis.strings[key] != "test-secret-value"
    assert redis.strings[key].startswith("v1:")
    assert cipher.decrypt(redis.strings[key]) == "test-secret-value"
    assert redis.hashes == {}
    assert redis.ttls[key] == 30 * 24 * 60 * 60
    assert status.model_name == "deepseek-v4-flash"
    assert status.stored is True
    assert status.expires_at is not None


@pytest.mark.asyncio
async def test_same_model_name_is_partitioned_by_user() -> None:
    redis = _FakeRedis()
    cipher = _cipher()
    store = ModelCredentialStore(redis, cipher)  # type: ignore[arg-type]
    await store.put("user-a", "deepseek-v4-flash", "secret-a")
    await store.put("user-b", "deepseek-v4-flash", "secret-b")

    assert set(redis.strings) == {
        _owner_key("user-a", "deepseek-v4-flash"),
        _owner_key("user-b", "deepseek-v4-flash"),
    }
    assert await store.get("user-a", "deepseek-v4-flash") == "secret-a"
    assert await store.get("user-b", "deepseek-v4-flash") == "secret-b"
    assert cipher.decrypt(redis.strings[_owner_key("user-a", "deepseek-v4-flash")]) == "secret-a"


@pytest.mark.asyncio
async def test_successful_reads_and_status_checks_refresh_sliding_ttl() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis, _cipher(), ttl_seconds=120)  # type: ignore[arg-type]
    key = _owner_key("user-a", "deepseek-v4-flash")
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
async def test_status_and_delete_are_owner_scoped() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis, _cipher())  # type: ignore[arg-type]
    await store.put("user-a", "deepseek-v4-flash", "test-secret-value")

    statuses = await store.statuses(
        "another-local-user",
        [("deepseek-v4-flash", None), ("missing-model", None)],
    )

    assert [(item.model_name, item.stored) for item in statuses] == [
        ("deepseek-v4-flash", False),
        ("missing-model", False),
    ]
    assert statuses[0].expires_at is None
    assert await store.delete("user-a", "deepseek-v4-flash") is True
    assert redis.strings == {}


@pytest.mark.asyncio
async def test_legacy_plaintext_key_migrates_to_owner_ciphertext_once() -> None:
    redis = _FakeRedis()
    cipher = _cipher()
    legacy_key = "agent_interview:model_credentials:v1:deepseek-v4-flash"
    redis.strings[legacy_key] = "migrated-secret"
    store = ModelCredentialStore(redis, cipher)  # type: ignore[arg-type]

    assert await store.get("user-a", "deepseek-v4-flash") == "migrated-secret"

    owner_key = _owner_key("user-a", "deepseek-v4-flash")
    assert legacy_key not in redis.strings
    assert cipher.decrypt(redis.strings[owner_key]) == "migrated-secret"
    # 迁移完成后读取不再依赖旧键。
    redis.strings.pop(owner_key, None)
    redis.strings[legacy_key] = "migrated-secret"
    assert await store.get("user-a", "deepseek-v4-flash") == "migrated-secret"
    assert legacy_key not in redis.strings


@pytest.mark.asyncio
async def test_legacy_uuid_hash_migrates_to_owner_ciphertext() -> None:
    redis = _FakeRedis()
    cipher = _cipher()
    legacy_id = "e8cbbb31-6df1-4ccb-bd08-41a85097f94e"
    legacy_key = f"agent_interview:model_credentials:v1:model:{legacy_id}"
    redis.hashes["agent_interview:model_credentials:v1:channels"] = {"mem0_llm": legacy_id}
    redis.hashes[legacy_key] = {
        "id": legacy_id,
        "model": "deepseek-v4-flash",
        "api_key": "migrated-secret",
    }
    store = ModelCredentialStore(redis, cipher)  # type: ignore[arg-type]

    assert await store.get("user-a", "deepseek-v4-flash", legacy_id=legacy_id) == "migrated-secret"

    owner_key = _owner_key("user-a", "deepseek-v4-flash")
    assert cipher.decrypt(redis.strings[owner_key]) == "migrated-secret"
    assert legacy_key not in redis.hashes
    assert "agent_interview:model_credentials:v1:channels" not in redis.hashes
    assert redis.ttls[owner_key] == 30 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_migration_write_failure_keeps_legacy_source() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis, _cipher())  # type: ignore[arg-type]
    legacy_key = "agent_interview:model_credentials:v1:deepseek-v4-flash"
    redis.strings[legacy_key] = "keep-me-secret"
    redis.fail_set = True

    with pytest.raises(ModelCredentialStoreUnavailable):
        await store.get("user-a", "deepseek-v4-flash")

    # 源值保留，未写入任何新键；恢复后可再次迁移。
    assert redis.strings == {legacy_key: "keep-me-secret"}
    redis.fail_set = False
    assert await store.get("user-a", "deepseek-v4-flash") == "keep-me-secret"
    assert legacy_key not in redis.strings


@pytest.mark.asyncio
async def test_undecryptable_value_fails_safe_without_leaking_secret() -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis, _cipher())  # type: ignore[arg-type]
    key = _owner_key("user-a", "deepseek-v4-flash")
    redis.strings[key] = _cipher().encrypt("fixture-sk-1234567890abcdef")

    with pytest.raises(ModelCredentialStoreUnavailable) as excinfo:
        await store.get("user-a", "deepseek-v4-flash")

    assert "fixture-sk-1234567890abcdef" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_logs_never_contain_fixture_api_key(caplog) -> None:
    redis = _FakeRedis()
    store = ModelCredentialStore(redis, _cipher())  # type: ignore[arg-type]
    fixture = "fixture-sk-log-1234567890"
    await store.put("user-a", "deepseek-v4-flash", fixture)
    await store.get("user-a", "deepseek-v4-flash")

    legacy_key = "agent_interview:model_credentials:v1:other-model"
    redis.strings[legacy_key] = fixture
    redis.fail_set = True
    with pytest.raises(ModelCredentialStoreUnavailable):
        await store.get("user-a", "other-model")

    assert fixture not in caplog.text


def test_cipher_decrypts_previous_generation_within_rotation_window() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    envelope = ModelCredentialCipher(old_key).encrypt("rotation-secret")

    rotated = ModelCredentialCipher(new_key, old_key)
    assert rotated.decrypt(envelope) == "rotation-secret"
    assert rotated.encrypt("rotation-secret") != envelope


def test_cipher_fails_closed_without_current_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("MODEL_CREDENTIAL_ENCRYPTION_PREVIOUS_KEY", raising=False)

    with pytest.raises(ModelCredentialCryptoError):
        build_model_credential_cipher()


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


def test_memory_delete_middleware_hydrates_mem0_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE memory requests hydrate the selected mem0 credentials before routing."""

    store = AsyncMock()
    store.get.side_effect = lambda _user_id, model_id, **_kwargs: f"resolved-{model_id}"
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)
    received_config: dict[str, object] = {}

    @app.delete("/api/memory/{memory_id}")
    async def delete_memory(memory_id: str, request: Request) -> dict[str, object]:
        """Capture the hydrated payload without exposing a credential in the response."""

        received_config.update((await request.json())["api_config"])
        return {"deleted": memory_id}

    response = TestClient(app).request(
        "DELETE",
        "/api/memory/memory-1",
        headers={"X-User-ID": "user-a"},
        json={
            "api_config": {
                "smart": {"credential_id": "unneeded-smart", "model": "unneeded-smart"},
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
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": "memory-1"}
    assert "api_key" not in response.text
    assert received_config["smart"] == {
        "credential_id": "unneeded-smart",
        "model": "unneeded-smart",
    }
    assert received_config["mem0_llm"]["api_key"] == "resolved-memory-llm-model"
    assert received_config["mem0_embedder"]["api_key"] == "resolved-memory-embedding-model"
    assert [call.args[1] for call in store.get.await_args_list] == [
        "memory-llm-model",
        "memory-embedding-model",
    ]


def test_memory_delete_middleware_fails_closed_for_missing_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DELETE request cannot reach a memory route when its mem0 key has expired."""

    store = AsyncMock()
    store.get.return_value = None
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)
    reached = False

    @app.delete("/api/memory/{memory_id}")
    async def unreachable_memory_delete(memory_id: str) -> dict[str, object]:
        """Represent a delete route that must remain unreachable without a credential."""

        nonlocal reached
        reached = True
        return {"deleted": memory_id}

    response = TestClient(app).request(
        "DELETE",
        "/api/memory/memory-1",
        json={
            "api_config": {
                "mem0_llm": {"credential_id": "missing-model", "model": "missing-model"},
            }
        },
    )

    assert response.status_code == 401
    assert "模型设置中填写" in response.json()["detail"]
    assert "missing-model" in response.json()["detail"]
    assert reached is False


def test_interview_history_draft_middleware_preserves_model_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft submission must not hydrate every configured model before queueing."""

    store = AsyncMock()
    store.get.side_effect = AssertionError("middleware must not read model credentials")
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/api/evaluations/interview-history/drafts")
    async def echo_reference(request: Request) -> dict:
        return await request.json()

    payload = {
        "attempt_ids": [11],
        "capability": "interview_turn",
        "api_config": {
            "fast_pool": [
                {
                    "credential_id": "deepseek-v4-flash",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://example.invalid/v1",
                },
                {
                    "credential_id": "expired-smart",
                    "model": "expired-smart",
                    "base_url": "https://example.invalid/v1",
                },
            ]
        },
    }
    response = TestClient(app).post(
        "/api/evaluations/interview-history/drafts",
        headers={"X-User-ID": "owner-a"},
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == payload
    store.get.assert_not_awaited()


def test_interview_history_failed_case_retry_preserves_model_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selected-case retry also defers credential hydration to the Worker."""

    store = AsyncMock()
    store.get.side_effect = AssertionError("middleware must not read model credentials")
    monkeypatch.setattr(
        "app.security.model_credential_middleware.get_model_credential_store",
        lambda: store,
    )
    app = FastAPI()
    app.add_middleware(ModelCredentialHydrationMiddleware)

    @app.post("/api/evaluations/interview-history/drafts/{run_id}/retry-failed")
    async def echo_reference(run_id: str, request: Request) -> dict:
        return {"run_id": run_id, "payload": await request.json()}

    payload = {
        "attempt_ids": [12],
        "api_config": {
            "fast": {
                "credential_id": "deepseek-v4-flash",
                "model": "deepseek-v4-flash",
                "base_url": "https://example.invalid/v1",
            }
        },
    }
    response = TestClient(app).post(
        "/api/evaluations/interview-history/drafts/draft-run-1/retry-failed",
        headers={"X-User-ID": "owner-a"},
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == {"run_id": "draft-run-1", "payload": payload}
    store.get.assert_not_awaited()
