"""应用统一配置入口。

仅放置服务端运行默认值；求职者填写的 API Key 仍随请求传入，不写入代码或配置文件。
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """可通过同名环境变量覆盖的模型运行配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    llm_request_timeout_seconds: int = Field(default=45, ge=1, le=600)
    llm_max_tokens: int = Field(default=8000, ge=1)
    llm_pool_failure_threshold: int = Field(default=2, ge=1, le=20)
    llm_pool_cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    llm_pool_redis_enabled: bool = True
    llm_pool_inflight_ttl_seconds: int = Field(default=600, ge=30, le=3600)
    allow_private_model_base_urls: bool = True
    api_config_validation_timeout_seconds: int = Field(default=10, ge=1, le=60)
    # 本地开发默认自动同步表结构；需要严格迁移验证时设为 false，仅使用 Alembic。
    auto_create_tables: bool = True

    boss_automation_service_url: str = ""
    boss_automation_service_token: SecretStr = SecretStr("")
    boss_automation_request_timeout_seconds: int = Field(default=240, ge=5, le=600)

    voice_model: str = "qwen3-omni-flash-2025-12-01"
    voice_name: str = "Cherry"
    voice_input_format: str = "wav"
    voice_output_format: str = "wav"
    voice_transcript_term_fixes: dict[str, str] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """返回进程内单例配置。"""

    return AppSettings()
