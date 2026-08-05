"""Keep the public environment template aligned with runtime deadline settings."""

from pathlib import Path

from app.config import AppSettings


_RUNTIME_BUDGET_KEYS = {
    "LLM_REQUEST_TIMEOUT_SECONDS": "45",
    "LLM_TASK_TIMEOUT_SECONDS": "90",
    "LLM_MIN_ATTEMPT_TIMEOUT_SECONDS": "2",
    "LLM_MAX_TOKENS": "8000",
    "LLM_ESTIMATED_CHARS_PER_TOKEN": "4",
    "TASK_DEADLINE_ENABLED": "true",
    "AGENT_CONTEXT_BUDGET_FLAGS": '{"interview":true,"resume_optimizer":true,"resume_generator":true,"job_assets":true,"voice_interview":true}',
    "INTERVIEW_PLAN_TIMEOUT_SECONDS": "20",
    "INTERACTIVE_INTERVIEW_TASK_TIMEOUT_SECONDS": "60",
    "VOICE_INTERVIEW_TASK_TIMEOUT_SECONDS": "45",
    "VOICE_INTERVIEW_NODE_TIMEOUT_SECONDS": "15",
    "INTERACTIVE_MIN_REMAINING_ATTEMPT_SECONDS": "3",
    "INTERVIEW_REPORT_QA_CHAR_BUDGET": "12000",
    "INTERVIEW_REPORT_TASK_TIMEOUT_SECONDS": "180",
    "RESUME_WORKSPACE_TASK_TIMEOUT_SECONDS": "240",
    "RESUME_GENERATION_TASK_TIMEOUT_SECONDS": "240",
    "JOB_ASSETS_TASK_TIMEOUT_SECONDS": "240",
    "ABILITY_PROFILE_TASK_TIMEOUT_SECONDS": "60",
}


def _template_values() -> dict[str, str]:
    """Read non-secret key/value defaults from the repository environment template."""
    template = Path(__file__).resolve().parents[2] / "env_example"
    values: dict[str, str] = {}
    for raw_line in template.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_env_example_contains_current_runtime_budget_defaults(monkeypatch) -> None:
    """Every public deadline/token budget uses the same default as AppSettings."""
    monkeypatch.delenv("TASK_DEADLINE_ENABLED", raising=False)
    monkeypatch.delenv("AGENT_CONTEXT_BUDGET_FLAGS", raising=False)
    values = _template_values()
    assert {key: values.get(key) for key in _RUNTIME_BUDGET_KEYS} == _RUNTIME_BUDGET_KEYS

    settings = AppSettings()
    assert settings.task_deadline_enabled is True
    assert all(settings.agent_context_budget_flags.values())
    assert settings.interactive_interview_task_timeout_seconds == 60
    assert settings.voice_interview_task_timeout_seconds == 45
    assert settings.voice_interview_node_timeout_seconds == 15
    assert settings.interactive_min_remaining_attempt_seconds == 3


_FEATURE_DEFAULT_KEYS = {
    "TASK_QUEUE_ENABLED": "true",
    "LLM_POOL_REDIS_ENABLED": "true",
    "ALLOW_PRIVATE_MODEL_BASE_URLS": "true",
    "GUARDRAILS_ENABLED": "true",
    "GUARDRAILS_FAIL_CLOSED": "true",
    "RAG_VECTOR_ENABLED": "true",
    "RAG_AGENTIC_MODE": "active",
    "LANGFUSE_ENABLED": "true",
    "LANGFUSE_PROMPT_MANAGEMENT_ENABLED": "true",
    "LANGFUSE_EVAL_REPORTING_ENABLED": "true",
    "MEM0_ENABLED": "true",
    "MEM0_BACKGROUND_WRITE": "true",
    "EVALUATION_CENTER_ENABLED": "true",
    "EVALUATION_RUNS_ENABLED": "true",
    "EVALUATION_LANGFUSE_REPORTING_ENABLED": "true",
    "EVALUATION_ONLINE_SAMPLING_ENABLED": "true",
    "EVALUATION_RELEASE_GATE_MODE": "enforce",
}


def test_env_example_keeps_product_capabilities_enabled_by_default(monkeypatch) -> None:
    """The canonical template and code fallbacks keep ordinary product capabilities on."""
    for key in _FEATURE_DEFAULT_KEYS:
        monkeypatch.delenv(key, raising=False)

    values = _template_values()
    assert {key: values.get(key) for key in _FEATURE_DEFAULT_KEYS} == _FEATURE_DEFAULT_KEYS

    settings = AppSettings(_env_file=None)
    assert settings.llm_pool_redis_enabled is True
    assert settings.allow_private_model_base_urls is True
    assert settings.guardrails_enabled is True
    assert settings.guardrails_fail_closed is True
    assert settings.evaluation_center_enabled is True
    assert settings.evaluation_runs_enabled is True
    assert settings.evaluation_langfuse_reporting_enabled is True
    assert settings.evaluation_online_sampling_enabled is True
    assert settings.evaluation_release_gate_mode == "enforce"

    from ai.memory.config import get_mem0_config, is_mem0_background_write
    from ai.runtime.agent_runs.service import task_queue_enabled
    from observability.config import LangfuseConfig

    assert task_queue_enabled() is True
    assert LangfuseConfig.from_env().enabled is True
    assert LangfuseConfig.from_env().prompt_management_enabled is True
    assert is_mem0_background_write() is True
    # Default-enabled mem0 still fails closed without external model credentials.
    monkeypatch.delenv("MEM0_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_EMBEDDER_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_mem0_config() is None
