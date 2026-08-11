"""提供键相关后端功能。"""

from __future__ import annotations

APP_REDIS_NAMESPACE = "agent_interview"
REDIS_KEY_SCHEMA_VERSION = "v1"


def build_redis_key(domain: str, kind: str, *segments: object) -> str:
    """根据调用方已清洗且不含敏感信息的片段构建带版本的 Redis 键。"""

    return ":".join(
        (
            APP_REDIS_NAMESPACE,
            domain,
            REDIS_KEY_SCHEMA_VERSION,
            kind,
            *(str(segment) for segment in segments),
        )
    )
