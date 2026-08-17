"""提供模型凭据相关后端功能。

凭据按 owner 分区保存为 Fernet 密文；旧全局明文 Key 与旧 UUID Hash 仅作为
一次性迁移源，迁移写入并验证成功后才会删除源值。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis_keys import build_redis_key
from app.security.model_credential_crypto import (
    ModelCredentialCipher,
    ModelCredentialCryptoError,
    build_model_credential_cipher,
)

_LEGACY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ModelCredentialError(RuntimeError):
    """定义模型凭据错误相关后端数据结构或服务组件。"""


class InvalidModelCredentialId(ModelCredentialError):
    """定义模型凭据ID相关后端数据结构或服务组件。"""


class ModelCredentialStoreUnavailable(ModelCredentialError):
    """定义模型凭据存储不可用相关后端数据结构或服务组件。"""


@dataclass(frozen=True)
class StoredCredentialStatus:
    """定义已存储凭据状态相关后端数据结构或服务组件。"""

    model_name: str
    stored: bool
    expires_at: datetime | None


def _text(value: Any) -> str | None:
    """处理文本相关后端逻辑。"""

    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


class ModelCredentialStore:
    """定义模型凭据存储相关后端数据结构或服务组件。"""

    def __init__(
        self,
        redis_client: Redis,
        cipher: ModelCredentialCipher,
        ttl_seconds: int = 30 * 24 * 60 * 60,
    ) -> None:
        self._redis = redis_client
        self._cipher = cipher
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _validate_model_name(model_name: str) -> str:
        """校验模型名称相关后端逻辑。"""

        if not isinstance(model_name, str):
            raise InvalidModelCredentialId("模型名称格式无效")
        cleaned = model_name.strip()
        if not cleaned or len(cleaned) > 256 or any(ord(char) < 32 for char in cleaned):
            raise InvalidModelCredentialId("模型名称格式无效")
        return cleaned

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        """校验用户标识相关后端逻辑。"""

        if not isinstance(user_id, str):
            raise InvalidModelCredentialId("用户标识格式无效")
        cleaned = user_id.strip()
        if not cleaned or len(cleaned) > 256 or any(ord(char) < 32 for char in cleaned):
            raise InvalidModelCredentialId("用户标识格式无效")
        return cleaned

    @staticmethod
    def _validate_legacy_id(legacy_id: str) -> str:
        """校验旧版ID相关后端逻辑。"""

        if not _LEGACY_ID_PATTERN.fullmatch(legacy_id):
            raise InvalidModelCredentialId("旧模型连接 ID 格式无效")
        return legacy_id

    @classmethod
    def _owner_hash(cls, user_id: str) -> str:
        """处理 owner 摘要相关后端逻辑。"""

        return hashlib.sha256(cls._validate_user_id(user_id).encode()).hexdigest()

    @classmethod
    def _credential_key(cls, user_id: str, model_name: str) -> str:
        """处理凭据键相关后端逻辑。"""

        return build_redis_key(
            "model_credentials",
            "owner",
            cls._owner_hash(user_id),
            "model",
            cls._validate_model_name(model_name),
        )

    @classmethod
    def _legacy_plaintext_key(cls, model_name: str) -> str:
        """处理旧版明文键相关后端逻辑。"""

        return build_redis_key("model_credentials", cls._validate_model_name(model_name))

    @classmethod
    def _legacy_hash_key(cls, legacy_id: str) -> str:
        """处理旧版哈希键相关后端逻辑。"""

        return build_redis_key("model_credentials", "model", cls._validate_legacy_id(legacy_id))

    @staticmethod
    def _legacy_channels_key() -> str:
        """处理旧版渠道键相关后端逻辑。"""

        return build_redis_key("model_credentials", "channels")

    async def _read_new_format(self, user_id: str, model_name: str) -> str | None:
        """读取并解密 owner 分区凭据，成功后刷新 TTL。"""

        key = self._credential_key(user_id, model_name)
        envelope = _text(await self._redis.get(key))
        if envelope is None:
            return None
        try:
            secret = self._cipher.decrypt(envelope)
        except ModelCredentialCryptoError as exc:
            raise ModelCredentialStoreUnavailable("模型凭据无法解密，请检查加密密钥配置") from exc
        await self._redis.expire(key, self._ttl_seconds)
        return secret

    async def _write_new_format(self, user_id: str, model_name: str, secret: str) -> str | None:
        """写入 owner 分区密文并读回验证；失败时返回 None 且不返回明文。"""

        key = self._credential_key(user_id, model_name)
        envelope = self._cipher.encrypt(secret)
        await self._redis.set(key, envelope, ex=self._ttl_seconds, nx=True)
        try:
            verified = await self._read_new_format(user_id, model_name)
        except ModelCredentialStoreUnavailable:
            return None
        return verified if verified == secret else None

    async def _migrate_legacy(self, user_id: str, model_name: str, legacy_id: str | None) -> str | None:
        """处理迁移旧版相关后端逻辑。

        迁移顺序：写入新格式 -> 读回验证 -> 删除旧值。任一步失败保留源值。
        """

        legacy_keys = [
            self._legacy_plaintext_key(model_name),
            self._legacy_channels_key(),
            self._legacy_hash_key(legacy_id) if legacy_id else None,
        ]

        try:
            current = await self._read_new_format(user_id, model_name)
            if current is not None:
                await self._redis.delete(*(key for key in legacy_keys if key is not None))
                return current

            legacy_api_key = _text(await self._redis.get(self._legacy_plaintext_key(model_name)))
            if legacy_api_key is None and legacy_id:
                legacy_api_key = _text(await self._redis.hget(self._legacy_hash_key(legacy_id), "api_key"))
            if not legacy_api_key or not legacy_api_key.strip():
                return None

            secret = legacy_api_key.strip()
            migrated = await self._write_new_format(user_id, model_name, secret)
            if migrated is None:
                # 新格式写入或验证失败：保留旧值，等待下次重试。
                return None
            await self._redis.delete(*(key for key in legacy_keys if key is not None))
            return migrated
        except RedisError as exc:
            raise ModelCredentialStoreUnavailable("旧模型 Key 迁移暂不可用") from exc

    async def put(
        self,
        user_id: str,
        model_name: str,
        api_key: str,
        *,
        legacy_id: str | None = None,
    ) -> StoredCredentialStatus:
        """写入模型凭据相关后端逻辑。"""

        secret = api_key.strip()
        if not secret:
            raise ModelCredentialError("API Key 不能为空")
        key = self._credential_key(user_id, model_name)
        legacy_keys = (
            self._legacy_plaintext_key(model_name),
            self._legacy_hash_key(legacy_id) if legacy_id else None,
            self._legacy_channels_key(),
        )
        try:
            await self._redis.set(key, self._cipher.encrypt(secret), ex=self._ttl_seconds)
            await self._redis.delete(*(item for item in legacy_keys if item is not None))
        except RedisError as exc:
            raise ModelCredentialStoreUnavailable("模型 API Key 存储暂不可用") from exc
        return StoredCredentialStatus(
            model_name=model_name.strip(),
            stored=True,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds),
        )

    async def move(
        self,
        user_id: str,
        source_model: str,
        target_model: str,
        *,
        legacy_id: str | None = None,
    ) -> StoredCredentialStatus:
        """移动模型凭据相关后端逻辑。"""

        api_key = await self.get(user_id, source_model, legacy_id=legacy_id)
        if api_key is None:
            raise ModelCredentialError("原模型 API Key 未保存")
        status = await self.put(user_id, target_model, api_key)
        if self._credential_key(user_id, source_model) != self._credential_key(user_id, target_model):
            try:
                await self._redis.delete(self._credential_key(user_id, source_model))
            except RedisError as exc:
                raise ModelCredentialStoreUnavailable("旧模型 API Key 删除暂不可用") from exc
        return status

    async def get(
        self,
        user_id: str,
        model_name: str,
        *,
        legacy_id: str | None = None,
    ) -> str | None:
        """获取模型凭据相关后端逻辑。"""

        return await self._migrate_legacy(user_id, model_name, legacy_id)

    async def delete(
        self,
        user_id: str,
        model_name: str,
        *,
        legacy_id: str | None = None,
    ) -> bool:
        """删除模型凭据相关后端逻辑。"""

        keys = [
            self._credential_key(user_id, model_name),
            self._legacy_plaintext_key(model_name),
            self._legacy_channels_key(),
        ]
        if legacy_id:
            keys.append(self._legacy_hash_key(legacy_id))
        try:
            return bool(await self._redis.delete(*keys))
        except RedisError as exc:
            raise ModelCredentialStoreUnavailable("模型 API Key 删除暂不可用") from exc

    async def statuses(
        self,
        user_id: str,
        models: list[tuple[str, str | None]],
    ) -> list[StoredCredentialStatus]:
        """处理状态相关后端逻辑。"""

        statuses: list[StoredCredentialStatus] = []
        seen: set[str] = set()
        for model_name, legacy_id in models:
            safe_name = self._validate_model_name(model_name)
            if safe_name in seen:
                continue
            seen.add(safe_name)
            api_key = await self.get(user_id, safe_name, legacy_id=legacy_id)
            statuses.append(
                StoredCredentialStatus(
                    model_name=safe_name,
                    stored=bool(api_key),
                    expires_at=(
                        datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
                        if api_key
                        else None
                    ),
                )
            )
        return statuses


@lru_cache(maxsize=1)
def get_model_credential_store() -> ModelCredentialStore:
    """获取模型凭据存储相关后端逻辑。"""

    settings = get_settings()
    if not settings.redis_url:
        raise ModelCredentialStoreUnavailable("REDIS_URL 未配置")
    try:
        cipher = build_model_credential_cipher()
    except ModelCredentialCryptoError as exc:
        raise ModelCredentialStoreUnavailable(str(exc)) from exc
    client = Redis.from_url(settings.redis_url, decode_responses=False)
    return ModelCredentialStore(
        client,
        cipher,
        ttl_seconds=settings.model_credential_ttl_seconds,
    )
