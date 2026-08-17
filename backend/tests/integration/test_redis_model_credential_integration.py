"""真实 Redis 模型凭据加密与 owner 分区集成测试。

默认不连接外部基础设施；设置 TEST_REDIS_URL 后可单独运行：

    uv run pytest -q -m "integration and requires_redis" tests/integration/test_redis_model_credential_integration.py
"""

import os
import uuid

import pytest
from cryptography.fernet import Fernet

from app.security.model_credential_crypto import ModelCredentialCipher
from app.security.model_credentials import ModelCredentialStore


def _redis_url() -> str | None:
    return os.getenv("TEST_REDIS_URL")


def _client(redis_url: str):
    from redis.asyncio import Redis

    return Redis.from_url(redis_url, decode_responses=False)


@pytest.mark.integration
@pytest.mark.requires_redis
@pytest.mark.asyncio
async def test_credentials_store_ciphertext_and_partition_by_owner(monkeypatch) -> None:
    redis_url = _redis_url()
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 模型凭据测试")
    monkeypatch.setenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from app.security.model_credential_crypto import build_model_credential_cipher

    cipher = build_model_credential_cipher()
    redis = _client(redis_url)
    token = uuid.uuid4().hex
    model = f"integration-model-{token}"
    secret = f"fixture-sk-{token}"
    store = ModelCredentialStore(redis, cipher, ttl_seconds=600)

    try:
        status = await store.put("user-a", model, secret)
        assert status.stored is True

        raw = await redis.get(store._credential_key("user-a", model))
        assert raw is not None
        raw_text = raw.decode() if isinstance(raw, bytes) else str(raw)
        assert raw_text != secret
        assert raw_text.startswith("v1:")
        assert cipher.decrypt(raw_text) == secret

        assert await store.get("user-a", model) == secret
        assert await store.get("user-b", model) is None
        assert await store.delete("user-a", model) is True
        assert await redis.get(store._credential_key("user-a", model)) is None
    finally:
        await redis.aclose()


@pytest.mark.integration
@pytest.mark.requires_redis
@pytest.mark.asyncio
async def test_legacy_plaintext_migrates_and_source_is_removed(monkeypatch) -> None:
    redis_url = _redis_url()
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 模型凭据测试")
    monkeypatch.setenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from app.security.model_credential_crypto import build_model_credential_cipher

    cipher = build_model_credential_cipher()
    redis = _client(redis_url)
    token = uuid.uuid4().hex
    model = f"integration-legacy-{token}"
    secret = f"fixture-sk-{token}"
    legacy_key = f"agent_interview:model_credentials:v1:{model}"
    store = ModelCredentialStore(redis, cipher, ttl_seconds=600)

    try:
        await redis.set(legacy_key, secret, ex=600)
        assert await store.get("user-a", model) == secret

        owner_raw = await redis.get(store._credential_key("user-a", model))
        assert owner_raw is not None
        owner_text = owner_raw.decode() if isinstance(owner_raw, bytes) else str(owner_raw)
        assert owner_text != secret
        assert cipher.decrypt(owner_text) == secret
        assert await redis.get(legacy_key) is None
        assert await store.delete("user-a", model) is True
    finally:
        await redis.delete(legacy_key)
        await redis.aclose()


@pytest.mark.integration
@pytest.mark.requires_redis
@pytest.mark.asyncio
async def test_rotation_window_decrypts_previous_generation(monkeypatch) -> None:
    redis_url = _redis_url()
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 模型凭据测试")
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", old_key)

    from app.security.model_credential_crypto import build_model_credential_cipher

    redis = _client(redis_url)
    token = uuid.uuid4().hex
    model = f"integration-rotate-{token}"
    secret = f"fixture-sk-{token}"
    old_store = ModelCredentialStore(redis, build_model_credential_cipher(), ttl_seconds=600)

    try:
        await old_store.put("user-a", model, secret)

        rotated = ModelCredentialCipher(new_key, old_key)
        rotated_store = ModelCredentialStore(redis, rotated, ttl_seconds=600)
        assert await rotated_store.get("user-a", model) == secret

        raw = await redis.get(rotated_store._credential_key("user-a", model))
        raw_text = raw.decode() if isinstance(raw, bytes) else str(raw)
        # 读取路径不重加密；轮换窗口内旧密文由当前+上一代密钥解密，脚本负责重加密。
        assert ModelCredentialCipher(old_key).decrypt(raw_text) == secret
        assert ModelCredentialCipher(new_key, old_key).decrypt(raw_text) == secret
        assert await rotated_store.delete("user-a", model) is True
    finally:
        await redis.aclose()
