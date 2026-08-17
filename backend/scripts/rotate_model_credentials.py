"""受控轮换模型凭据加密密钥。

用法（在 backend 目录，容器或本机均可）:

    uv run python -m scripts.rotate_model_credentials
    uv run python -m scripts.rotate_model_credentials --legacy-owner <user_id>

要求环境变量:
    MODEL_CREDENTIAL_ENCRYPTION_KEY          轮换后的新密钥（当前密钥）
    MODEL_CREDENTIAL_ENCRYPTION_PREVIOUS_KEY 轮换前的旧密钥（用于解密上一代密文）
    REDIS_URL                                凭据所在 Redis

行为:
    - 用当前密钥重加密全部 owner 分区凭据，逐条读回验证，并保留原 TTL；
    - 提供 --legacy-owner 时，把旧全局明文 Key 一次性迁入该 owner 的密文格式；
    - 只输出模型名与数量，绝不输出任何真实 Key 或密文。

轮换顺序建议：先配置 PREVIOUS=旧密钥 + 当前密钥=新密钥运行本脚本，验证全部成功
后，再移除 MODEL_CREDENTIAL_ENCRYPTION_PREVIOUS_KEY 并重启服务。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis_keys import APP_REDIS_NAMESPACE
from app.security.model_credential_crypto import (
    ModelCredentialCipher,
    ModelCredentialCryptoError,
    build_model_credential_cipher,
)
from app.security.model_credentials import ModelCredentialStore

_OWNER_KEY_PREFIX = f"{APP_REDIS_NAMESPACE}:model_credentials:v1:owner:"
_LEGACY_CHANNELS_KEY = f"{APP_REDIS_NAMESPACE}:model_credentials:v1:channels"


def _plaintext_legacy_scan_patterns() -> tuple[str, str]:
    """旧全局明文 Key 与旧 UUID Hash 的扫描样式。"""

    return (
        f"{APP_REDIS_NAMESPACE}:model_credentials:v1:*",
        _LEGACY_CHANNELS_KEY,
    )


async def _scan_keys(redis: Redis, pattern: str) -> list[str]:
    keys: list[str] = []
    async for key in redis.scan_iter(match=pattern):
        keys.append(key)
    return keys


def _is_owner_key(key: str) -> bool:
    return key.startswith(_OWNER_KEY_PREFIX)


def _is_legacy_plaintext_key(key: str) -> bool:
    """旧全局明文模型名 Key：非 owner/channels/model Hash 的 v1 直属 key。"""

    prefix = f"{APP_REDIS_NAMESPACE}:model_credentials:v1:"
    if not key.startswith(prefix) or key == _LEGACY_CHANNELS_KEY:
        return False
    return not key.startswith(_OWNER_KEY_PREFIX) and ":model:" not in key


def _model_name_from_legacy_key(key: str) -> str:
    return key.removeprefix(f"{APP_REDIS_NAMESPACE}:model_credentials:v1:")


async def _rotate_owner_keys(
    redis: Redis,
    cipher: ModelCredentialCipher,
    ttl_seconds: int,
) -> int:
    """用当前密钥重加密 owner 分区凭据并读回验证，保留原 TTL。"""

    rotated = 0
    for key in await _scan_keys(redis, f"{_OWNER_KEY_PREFIX}*"):
        envelope = await redis.get(key)
        if envelope is None:
            continue
        text = envelope.decode() if isinstance(envelope, bytes) else str(envelope)
        try:
            secret = cipher.decrypt(text)
        except ModelCredentialCryptoError as exc:
            raise RuntimeError(f"凭据无法解密，请检查 PREVIOUS 密钥配置: {exc}") from exc
        ttl_ms = await redis.pttl(key)
        ttl_ms = max(ttl_ms, 1000) if ttl_ms and ttl_ms > 0 else ttl_seconds * 1000
        await redis.set(key, cipher.encrypt(secret), px=ttl_ms)
        verified = await redis.get(key)
        verified_text = verified.decode() if isinstance(verified, bytes) else str(verified)
        if cipher.decrypt(verified_text) != secret:
            raise RuntimeError("轮换后读回验证失败，请勿移除 PREVIOUS 密钥")
        rotated += 1
    return rotated


async def _migrate_legacy_plaintext(redis: Redis, store: ModelCredentialStore, owner: str) -> int:
    """把旧全局明文模型名 Key 迁入指定 owner 的密文格式。"""

    migrated = 0
    for key in await _scan_keys(redis, f"{APP_REDIS_NAMESPACE}:model_credentials:v1:*"):
        if not _is_legacy_plaintext_key(key):
            continue
        model_name = _model_name_from_legacy_key(key)
        api_key = await store.get(owner, model_name)
        if api_key is None:
            print(f"  跳过（无法迁移）: {model_name}")
            continue
        migrated += 1
        print(f"  已迁移: {model_name}")
    return migrated


async def _run(legacy_owner: str | None) -> int:
    settings = get_settings()
    if not settings.redis_url:
        print("REDIS_URL 未配置", file=sys.stderr)
        return 2
    try:
        cipher = build_model_credential_cipher()
    except ModelCredentialCryptoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    store = ModelCredentialStore(redis, cipher, ttl_seconds=settings.model_credential_ttl_seconds)
    try:
        await redis.ping()
        rotated = await _rotate_owner_keys(redis, cipher, settings.model_credential_ttl_seconds)
        print(f"owner 分区凭据重加密: {rotated} 条（全部读回验证通过）")
        if legacy_owner:
            migrated = await _migrate_legacy_plaintext(redis, store, legacy_owner)
            print(f"旧全局明文凭据迁移: {migrated} 条")
        else:
            remaining = sum(
                1
                for key in await _scan_keys(redis, f"{APP_REDIS_NAMESPACE}:model_credentials:v1:*")
                if _is_legacy_plaintext_key(key)
            )
            if remaining:
                print(
                    f"提示: 仍存在 {remaining} 条旧全局明文凭据，"
                    "下次对应模型被使用时将自动迁移；也可加 --legacy-owner <user_id> 立即迁移"
                )
        return 0
    except (RedisError, RuntimeError) as exc:
        print(f"轮换失败: {exc}", file=sys.stderr)
        return 1
    finally:
        await redis.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="轮换模型凭据加密密钥")
    parser.add_argument("--legacy-owner", help="把旧全局明文凭据迁入该 user_id 的 owner 分区")
    args = parser.parse_args()
    return asyncio.run(_run(args.legacy_owner))


if __name__ == "__main__":
    sys.exit(main())
