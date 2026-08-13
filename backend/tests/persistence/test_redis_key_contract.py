"""Acceptance contract for application-owned Redis key names."""

from __future__ import annotations

import hashlib

from ai.llm.model_pool import ModelPoolScheduler, _identity
from ai.memory.retention import MemoryRetentionStore
from ai.runtime.execution.gate import LOCK_KEY
from app.security.model_credentials import ModelCredentialStore
from integrations.browser_automation.rate_limiter import RateLimitType, RedisRateLimitStore


def _model_config() -> dict[str, object]:
    return {
        "provider": "openai_compatible",
        "integration": "langchain_openai",
        "base_url": "https://models.example.test/v1",
        "model": "test-model",
        "api_key": "never-place-this-secret-in-a-key",
        "weight": 1,
    }


def test_application_redis_keys_use_versioned_readable_namespace() -> None:
    """Each first-party key exposes its domain/kind while keeping safe identifiers."""

    user_id = "user@example.test"
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    model_id = "model-1"
    memory_id = "memory-1"
    config = _model_config()
    scheduler = ModelPoolScheduler(redis_client=None)
    identity = _identity(config)
    rate_store = RedisRateLimitStore("redis://localhost:6379/0")

    assert ModelCredentialStore._credential_key("deepseek-v4-flash") == (
        "agent_interview:model_credentials:v1:deepseek-v4-flash"
    )
    assert MemoryRetentionStore._access_key(user_id, memory_id) == (
        f"agent_interview:memory_retention:v1:access:{owner_hash}:{memory_id}"
    )
    assert MemoryRetentionStore._candidate_key(user_id, memory_id) == (
        f"agent_interview:memory_retention:v1:candidate:{owner_hash}:{memory_id}"
    )
    assert MemoryRetentionStore._sweep_key(user_id) == (
        f"agent_interview:memory_retention:v1:sweep:{owner_hash}"
    )
    assert scheduler._cursor_key("fast_pool", [config]) == (
        f"agent_interview:model_pool:v1:cursor:{scheduler._pool_token('fast_pool', [config])}"
    )
    assert scheduler._member_key("inflight", identity).startswith(
        "agent_interview:model_pool:v1:inflight:"
    )
    assert LOCK_KEY == "agent_interview:runtime_gate:v1:active_lease"
    assert rate_store._rate_key(user_id, RateLimitType.BOSS_CAPTURE) == (
        f"agent_interview:browser_rate_limit:v1:window:{owner_hash}:boss_capture"
    )
    assert rate_store._failure_key(user_id) == (
        f"agent_interview:browser_rate_limit:v1:failures:{owner_hash}"
    )


def test_redis_keys_do_not_expose_sensitive_source_values() -> None:
    """Readable key labels must not reveal owners, API keys, or model endpoints."""

    user_id = "private-owner@example.test"
    config = _model_config()
    scheduler = ModelPoolScheduler(redis_client=None)
    keys = [
        ModelCredentialStore._credential_key("deepseek-v4-flash"),
        MemoryRetentionStore._access_key(user_id, "memory-1"),
        scheduler._cursor_key("reasoning_pool", [config]),
        scheduler._member_key("failures", _identity(config)),
    ]

    for key in keys:
        assert user_id not in key
        assert str(config["api_key"]) not in key
        assert str(config["base_url"]) not in key
