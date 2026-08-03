"""User-isolated encrypted model credentials backed by Redis."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.security.payload_crypto import (
    TaskPayloadConfigurationError,
    decrypt_payload,
    encrypt_payload,
)

_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MEMORY_CHANNELS = ("mem0_llm", "mem0_embedder", "rag_embedding")


class ModelCredentialError(RuntimeError):
    """Base error for model credential persistence and lookup."""


class InvalidModelCredentialId(ModelCredentialError):
    """The supplied local model identifier is unsafe or malformed."""


class ModelCredentialStoreUnavailable(ModelCredentialError):
    """Redis or credential encryption is not configured or available."""


@dataclass(frozen=True)
class StoredCredentialStatus:
    """Non-sensitive credential status returned to callers."""

    model_id: str
    stored: bool
    expires_at: datetime | None


@dataclass(frozen=True)
class StoredModelProfile:
    """Non-secret model connection metadata needed by backend jobs."""

    model_id: str
    base_url: str
    model: str
    provider: str | None = None
    integration: str | None = None
    pricing_key: str | None = None


class ModelCredentialStore:
    """Encrypt API keys before storing them in owner-scoped Redis keys."""

    def __init__(self, redis_client: Redis, ttl_seconds: int) -> None:
        """Create a credential store using an injected async Redis client."""

        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _validate_model_id(model_id: str) -> str:
        """Validate and return a model ID that is safe for credential lookup."""

        if not _MODEL_ID_PATTERN.fullmatch(model_id):
            raise InvalidModelCredentialId("模型连接 ID 格式无效")
        return model_id

    @classmethod
    def _redis_key(cls, user_id: str, model_id: str) -> str:
        """Build a non-reversible user-scoped Redis key."""

        safe_model_id = cls._validate_model_id(model_id)
        owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
        return f"model-credential:v1:{owner_hash}:{safe_model_id}"

    @classmethod
    def _profile_key(cls, user_id: str, model_id: str) -> str:
        """Build an owner-scoped encrypted model profile key."""

        safe_model_id = cls._validate_model_id(model_id)
        owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
        return f"model-credential-profile:v1:{owner_hash}:{safe_model_id}"

    @staticmethod
    def _channel_key(user_id: str, channel: str) -> str:
        """Build an owner-scoped memory channel binding key."""

        if channel not in _MEMORY_CHANNELS:
            raise ModelCredentialError("不支持的模型通道")
        owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
        return f"model-channel-binding:v1:{owner_hash}:{channel}"

    async def put(self, user_id: str, model_id: str, api_key: str) -> StoredCredentialStatus:
        """Encrypt and store one key with the configured rolling TTL."""

        secret = api_key.strip()
        if not secret:
            raise ModelCredentialError("API Key 不能为空")
        try:
            encrypted = encrypt_payload({"api_key": secret})
            await self._redis.set(self._redis_key(user_id, model_id), encrypted, ex=self._ttl_seconds)
        except (RedisError, TaskPayloadConfigurationError) as exc:
            raise ModelCredentialStoreUnavailable("模型凭据存储暂不可用") from exc
        return StoredCredentialStatus(
            model_id=model_id,
            stored=True,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
        )

    async def get(self, user_id: str, model_id: str) -> str | None:
        """Resolve and decrypt one owner-scoped model API key."""

        try:
            encrypted = await self._redis.get(self._redis_key(user_id, model_id))
            if encrypted is None:
                return None
            payload = decrypt_payload(encrypted.decode() if isinstance(encrypted, bytes) else encrypted)
        except (RedisError, TaskPayloadConfigurationError) as exc:
            raise ModelCredentialStoreUnavailable("模型凭据读取暂不可用") from exc
        api_key = payload.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise ModelCredentialStoreUnavailable("模型凭据内容无效")
        return api_key

    async def delete(self, user_id: str, model_id: str) -> bool:
        """Delete one owner-scoped credential."""

        try:
            safe_model_id = self._validate_model_id(model_id)
            channel_keys = [self._channel_key(user_id, channel) for channel in _MEMORY_CHANNELS]
            bindings = await self._redis.mget(channel_keys)
            bound_keys = [
                key
                for key, value in zip(channel_keys, bindings, strict=True)
                if value is not None
                and (value.decode() if isinstance(value, bytes) else str(value)) == safe_model_id
            ]
            deleted = await self._redis.delete(
                self._redis_key(user_id, safe_model_id),
                self._profile_key(user_id, safe_model_id),
                *bound_keys,
            )
            return bool(deleted)
        except RedisError as exc:
            raise ModelCredentialStoreUnavailable("模型凭据删除暂不可用") from exc

    async def remember_model_profile(
        self,
        *,
        user_id: str,
        channel: str,
        model_id: str,
        base_url: str,
        model: str,
        provider: str | None = None,
        integration: str | None = None,
        pricing_key: str | None = None,
    ) -> None:
        """Persist bounded model metadata and its owner-scoped memory-channel binding."""

        safe_model_id = self._validate_model_id(model_id)
        clean_base_url = base_url.strip()[:2048]
        clean_model = model.strip()[:256]
        if not clean_base_url or not clean_model:
            return
        profile = {
            "model_id": safe_model_id,
            "base_url": clean_base_url,
            "model": clean_model,
            "provider": provider.strip()[:128] if isinstance(provider, str) else None,
            "integration": integration.strip()[:128] if isinstance(integration, str) else None,
            "pricing_key": pricing_key.strip()[:256] if isinstance(pricing_key, str) else None,
        }
        try:
            encrypted_profile = encrypt_payload(profile)
            pipeline = self._redis.pipeline(transaction=False)
            pipeline.set(
                self._profile_key(user_id, safe_model_id),
                encrypted_profile,
                ex=self._ttl_seconds,
            )
            pipeline.set(
                self._channel_key(user_id, channel),
                safe_model_id,
                ex=self._ttl_seconds,
            )
            await pipeline.execute()
        except (RedisError, TaskPayloadConfigurationError) as exc:
            raise ModelCredentialStoreUnavailable("模型通道元数据存储暂不可用") from exc

    async def resolve_channel_config(self, user_id: str, channel: str) -> dict | None:
        """Restore one owner-scoped channel config from Redis for backend-only jobs."""

        try:
            binding = await self._redis.get(self._channel_key(user_id, channel))
            if binding is None:
                return None
            model_id = binding.decode() if isinstance(binding, bytes) else str(binding)
            safe_model_id = self._validate_model_id(model_id)
            encrypted_profile = await self._redis.get(self._profile_key(user_id, safe_model_id))
            if encrypted_profile is None:
                return None
            payload = decrypt_payload(
                encrypted_profile.decode()
                if isinstance(encrypted_profile, bytes)
                else encrypted_profile
            )
            api_key = await self.get(user_id, safe_model_id)
        except (RedisError, TaskPayloadConfigurationError) as exc:
            raise ModelCredentialStoreUnavailable("模型通道配置读取暂不可用") from exc
        if api_key is None:
            return None
        base_url = payload.get("base_url")
        model = payload.get("model")
        if not isinstance(base_url, str) or not isinstance(model, str):
            return None
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "provider": payload.get("provider"),
            "integration": payload.get("integration"),
            "pricing_key": payload.get("pricing_key"),
        }

    async def statuses(self, user_id: str, model_ids: list[str]) -> list[StoredCredentialStatus]:
        """Return existence and expiry metadata for model IDs without secrets."""

        unique_ids = list(dict.fromkeys(model_ids))
        keys = [self._redis_key(user_id, model_id) for model_id in unique_ids]
        if not keys:
            return []
        try:
            pipeline = self._redis.pipeline(transaction=False)
            for key in keys:
                pipeline.ttl(key)
            ttls = await pipeline.execute()
        except RedisError as exc:
            raise ModelCredentialStoreUnavailable("模型凭据状态查询暂不可用") from exc
        now = datetime.now(UTC)
        return [
            StoredCredentialStatus(
                model_id=model_id,
                stored=ttl > 0,
                expires_at=now + timedelta(seconds=ttl) if ttl > 0 else None,
            )
            for model_id, ttl in zip(unique_ids, ttls, strict=True)
        ]


@lru_cache(maxsize=1)
def get_model_credential_store() -> ModelCredentialStore:
    """Build the process-wide Redis credential store from application settings."""

    settings = get_settings()
    if not settings.redis_url:
        raise ModelCredentialStoreUnavailable("REDIS_URL 未配置")
    client = Redis.from_url(settings.redis_url, decode_responses=False)
    return ModelCredentialStore(client, settings.model_credential_ttl_seconds)
