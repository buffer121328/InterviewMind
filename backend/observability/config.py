"""Environment-backed Langfuse configuration without client lifecycle state."""

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes"}


def _env_int(name: str, default: int) -> int:
    """Read a positive integer environment variable with a safe fallback."""
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default




def _env_float_optional(name: str) -> float | None:
    """Read an optional float environment variable."""
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None




@dataclass(frozen=True)
class LangfuseConfig:
    """数据对象，承载 `LangfuseConfig` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    enabled: bool
    public_key: str = ""
    secret_key: str = ""
    base_url: str = "https://cloud.langfuse.com"
    environment: str | None = None
    release: str | None = None
    sample_rate: float | None = None
    prompt_management_enabled: bool = False
    prompt_label: str | None = "production"
    prompt_cache_ttl_seconds: int = 300

    @classmethod
    def from_env(cls) -> "LangfuseConfig":
        """从环境变量构造 Langfuse 配置，统一开关、项目和凭据的延迟读取边界。"""
        prompt_label = os.getenv("LANGFUSE_PROMPT_LABEL", "production").strip() or None
        return cls(
            enabled=_env_bool("LANGFUSE_ENABLED"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            base_url=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT") or None,
            release=os.getenv("LANGFUSE_RELEASE") or None,
            sample_rate=_env_float_optional("LANGFUSE_SAMPLE_RATE"),
            prompt_management_enabled=_env_bool("LANGFUSE_PROMPT_MANAGEMENT_ENABLED"),
            prompt_label=prompt_label,
            prompt_cache_ttl_seconds=_env_int("LANGFUSE_PROMPT_CACHE_TTL_SECONDS", 300),
        )
