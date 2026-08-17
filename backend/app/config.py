"""应用统一配置入口。

仅放置服务端运行默认值；本地模型 API Key 以 Fernet 密文按 owner 分区存入仅绑定
localhost 的 Redis String Key，不写入代码或配置文件。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.runtime_paths import RuntimePaths, resolve_runtime_paths


class AppSettings(BaseSettings):
    """可通过同名环境变量覆盖的模型运行配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    llm_request_timeout_seconds: int = Field(default=45, ge=1, le=600)
    llm_task_timeout_seconds: int = Field(default=90, ge=1, le=1800)
    llm_min_attempt_timeout_seconds: float = Field(default=2.0, ge=0.0, le=60.0)
    llm_max_tokens: int = Field(default=8000, ge=1)
    llm_estimated_chars_per_token: float = Field(default=4.0, ge=0.1, le=20.0)
    task_deadline_enabled: bool = True
    agent_context_budget_flags: dict[str, bool] = Field(default_factory=lambda: {
        "interview": True,
        "resume_optimizer": True,
        "resume_generator": True,
        "job_assets": True,
        "voice_interview": True,
    })
    interview_plan_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    interactive_interview_task_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    voice_interview_task_timeout_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
    voice_interview_node_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    interactive_min_remaining_attempt_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    interview_report_qa_char_budget: int = Field(default=12_000, ge=2_000, le=100_000)
    interview_report_chunk_size: int = Field(default=5, ge=2, le=10)
    interview_report_task_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    resume_workspace_task_timeout_seconds: int = Field(default=240, ge=30, le=1800)
    resume_generation_task_timeout_seconds: int = Field(default=240, ge=30, le=1800)
    job_assets_task_timeout_seconds: int = Field(default=240, ge=30, le=1800)
    ability_profile_task_timeout_seconds: int = Field(default=60, ge=5, le=600)
    resume_material_max_items: int = Field(default=8, ge=1, le=20)
    resume_material_item_max_chars: int = Field(default=1200, ge=200, le=5000)
    project_rewrite_project_max_chars: int = Field(default=5000, ge=500, le=20000)
    project_rewrite_jd_max_chars: int = Field(default=2500, ge=500, le=10000)
    embedding_timeout_seconds: float = Field(default=8.0, ge=0.5, le=120.0)
    vector_search_timeout_seconds: float = Field(default=5.0, ge=0.5, le=120.0)
    mem0_search_timeout_seconds: float = Field(default=5.0, ge=0.5, le=120.0)
    mem0_add_timeout_seconds: float = Field(default=5.0, ge=0.5, le=120.0)
    llm_pool_failure_threshold: int = Field(default=2, ge=1, le=20)
    llm_pool_cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    llm_pool_redis_enabled: bool = True
    llm_pool_inflight_ttl_seconds: int = Field(default=600, ge=30, le=3600)
    llm_pool_cursor_ttl_seconds: int = Field(default=86_400, ge=60, le=30 * 24 * 60 * 60)
    # SSRF 边界：默认拒绝私网/回环模型 Base URL；仅本地开发（Ollama/vLLM/LM Studio）显式开启。
    allow_private_model_base_urls: bool = False
    api_config_validation_timeout_seconds: int = Field(default=10, ge=1, le=60)
    redis_url: str = ""
    runtime_data_dir: str = "data"
    artifact_storage_dir: str | None = None
    static_storage_dir: str | None = None
    model_credential_ttl_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        ge=60,
        le=3650 * 24 * 60 * 60,
    )

    # 长期记忆分层保留和两阶段清理。core 始终受保护，不提供自动删除开关。
    memory_retention_durable_min_age_days: int = Field(default=730, ge=1, le=36_500)
    memory_retention_durable_inactive_days: int = Field(default=365, ge=1, le=36_500)
    memory_retention_transient_min_age_days: int = Field(default=120, ge=1, le=36_500)
    memory_retention_transient_inactive_days: int = Field(default=90, ge=1, le=36_500)
    memory_retention_cleanup_grace_days: int = Field(default=30, ge=1, le=365)
    memory_retention_cleanup_interval_hours: int = Field(default=24, ge=1, le=720)
    memory_retention_state_ttl_days: int = Field(default=3 * 365, ge=30, le=36_500)

    # Guardrails 仅运行本地 validator，默认 fail closed，且不使用 Guardrails Hub 或 vendor telemetry。
    guardrails_enabled: bool = True
    guardrails_fail_closed: bool = True
    guardrails_max_untrusted_context_chars: int = Field(default=20_000, ge=1_000, le=100_000)

    # 本地开发默认自动同步表结构；需要严格迁移验证时设为 false，仅使用 Alembic。
    auto_create_tables: bool = True

    # Agent 评测中心默认全开；评测适配器仍必须 mock/阻断真实外部副作用。
    evaluation_center_enabled: bool = True
    evaluation_runs_enabled: bool = True
    evaluation_langfuse_reporting_enabled: bool = True
    evaluation_online_sampling_enabled: bool = True
    evaluation_release_gate_mode: str = Field(default="enforce", pattern=r"^(off|warn|enforce)$")
    evaluation_max_concurrency: int = Field(default=4, ge=1, le=20)
    evaluation_default_max_budget_usd: float = Field(default=5.0, gt=0, le=1000)

    browser_automation_service_url: str = ""
    browser_automation_service_token: SecretStr = SecretStr("")
    browser_automation_request_timeout_seconds: int = Field(default=300, ge=5, le=600)

    mimo_voice: str = "Chloe"
    mimo_tts_timeout_seconds: int = Field(default=30, ge=1, le=120)
    mimo_asr_timeout_seconds: int = Field(default=30, ge=1, le=120)
    voice_transcript_term_fixes: dict[str, str] = Field(default_factory=dict)
    voice_history_max_chars: int = Field(default=5_000, ge=1_000, le=30_000)
    voice_recent_message_count: int = Field(default=8, ge=2, le=30)
    voice_audio_max_bytes: int = Field(default=8_000_000, ge=100_000, le=50_000_000)
    voice_audio_max_duration_seconds: int = Field(default=120, ge=5, le=600)

    @property
    def runtime_paths(self) -> RuntimePaths:
        """返回不依赖当前工作目录的统一运行路径。"""

        return resolve_runtime_paths(
            runtime_data_dir=self.runtime_data_dir,
            artifact_storage_dir=self.artifact_storage_dir,
            static_storage_dir=self.static_storage_dir,
        )

    @property
    def runtime_data_path(self) -> Path:
        """返回 canonical runtime data root。"""

        return self.runtime_paths.runtime_data_dir

    @property
    def artifact_storage_path(self) -> Path:
        """返回私有 artifact 存储根。"""

        return self.runtime_paths.artifact_storage_dir

    @property
    def static_storage_path(self) -> Path:
        """返回公开静态运行文件根。"""

        return self.runtime_paths.static_storage_dir


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """返回进程内单例配置。"""

    return AppSettings()
