"""Shared naming contract for application-owned Redis keys."""

from __future__ import annotations

APP_REDIS_NAMESPACE = "agent_interview"
REDIS_KEY_SCHEMA_VERSION = "v1"


def build_redis_key(domain: str, kind: str, *segments: object) -> str:
    """Build a versioned Redis key from caller-sanitized, non-sensitive segments.

    ``v1`` versions the key layout and value contract. It changes only when the
    Redis representation becomes incompatible, not whenever the stored data is
    updated.
    """

    return ":".join(
        (
            APP_REDIS_NAMESPACE,
            domain,
            REDIS_KEY_SCHEMA_VERSION,
            kind,
            *(str(segment) for segment in segments),
        )
    )
