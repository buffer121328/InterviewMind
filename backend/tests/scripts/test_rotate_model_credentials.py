"""模型凭据轮换脚本的 Redis bytes/str 边界回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest

import scripts.rotate_model_credentials as rotation
from app.security.model_credential_crypto import ModelCredentialCipher


class _BytesRedis:
    """只覆盖轮换脚本需要的最小 Redis 异步协议。"""

    def __init__(self, values: dict[bytes, bytes]) -> None:
        self.values = values
        self.ttls = {key: 120_000 for key in values}
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True

    async def scan_iter(self, *, match: str):
        for key in list(self.values):
            decoded = key.decode()
            if match.endswith("*") and decoded.startswith(match[:-1]):
                yield key

    async def get(self, key: str | bytes) -> bytes | None:
        return self.values.get(key.encode() if isinstance(key, str) else key)

    async def pttl(self, key: str | bytes) -> int:
        return self.ttls[key.encode() if isinstance(key, str) else key]

    async def set(self, key: str | bytes, value: str, *, px: int) -> bool:
        normalized = key.encode() if isinstance(key, str) else key
        self.values[normalized] = value.encode()
        self.ttls[normalized] = px
        return True


class _RedisFactory:
    def __init__(self, client: _BytesRedis) -> None:
        self.client = client

    def from_url(self, _url: str, *, decode_responses: bool) -> _BytesRedis:
        assert decode_responses is False
        return self.client


def test_key_helpers_accept_bytes_from_redis_scan() -> None:
    legacy = b"agent_interview:model_credentials:v1:deepseek-v4-flash"
    owner = b"agent_interview:model_credentials:v1:owner:abc:model:deepseek-v4-flash"

    assert rotation._is_legacy_plaintext_key(legacy) is True
    assert rotation._is_owner_key(owner) is True
    assert rotation._model_name_from_legacy_key(legacy) == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_rotation_run_succeeds_with_bytes_keys(monkeypatch, capsys) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    owner_key = b"agent_interview:model_credentials:v1:owner:abc:model:rotation-model"
    fixture_value = "fixture-model-credential"
    redis = _BytesRedis({owner_key: ModelCredentialCipher(old_key).encrypt(fixture_value).encode()})

    monkeypatch.setenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("MODEL_CREDENTIAL_ENCRYPTION_PREVIOUS_KEY", old_key)
    monkeypatch.setattr(rotation, "Redis", _RedisFactory(redis))
    monkeypatch.setattr(
        rotation,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://test", model_credential_ttl_seconds=600),
    )

    result = await rotation._run(None)

    assert result == 0
    rotated = await redis.get(owner_key)
    assert rotated is not None
    assert ModelCredentialCipher(new_key).decrypt(rotated.decode()) == fixture_value
    assert redis.ttls[owner_key] == 120_000
    assert fixture_value not in capsys.readouterr().out
