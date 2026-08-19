"""Langfuse client 配置、trace URL、评分、托管 Prompt 与 span 输出的离线测试。"""

from contextlib import contextmanager

import pytest


class FakeSpan:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeLangfuseClient:
    def __init__(self):
        self.observations = []
        self.shutdown_called = False

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        span = FakeSpan()
        self.observations.append((kwargs, span))
        yield span

    def create_trace_id(self):
        return "0123456789abcdef0123456789abcdef"

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture(autouse=True)
def reset_observability(monkeypatch):
    import observability

    for key in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_TRACING_ENVIRONMENT",
        "LANGFUSE_RELEASE",
        "LANGFUSE_SAMPLE_RATE",
        "LANGFUSE_CAPTURE_MODEL_IO",
        "LANGFUSE_PROMPT_MANAGEMENT_ENABLED",
        "LANGFUSE_PROMPT_LABEL",
        "LANGFUSE_PROMPT_CACHE_TTL_SECONDS",
        "LANGFUSE_PROMPT_FETCH_TIMEOUT_SECONDS",
        "LANGFUSE_PROMPT_MAX_RETRIES",
    ):
        monkeypatch.delenv(key, raising=False)
    observability._reset_langfuse_for_tests()
    yield
    observability._reset_langfuse_for_tests()


def test_shutdown_langfuse_closes_client(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    assert observability.configure_langfuse() is True
    observability.shutdown_langfuse()

    assert client.shutdown_called is True


def test_get_langfuse_trace_url_returns_valid_sdk_link(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    client.get_trace_url = lambda *, trace_id: (
        f"https://langfuse.example/project/project-1/traces/{trace_id}"
    )
    monkeypatch.setattr(observability, "_client", client)
    monkeypatch.setattr(observability, "_configured", True)

    assert observability.get_langfuse_trace_url("trace-1") == (
        "https://langfuse.example/project/project-1/traces/trace-1"
    )


def test_get_langfuse_trace_url_rejects_credentialed_link(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    client.get_trace_url = lambda *, trace_id: (
        f"https://user:secret@langfuse.example/traces/{trace_id}"
    )
    monkeypatch.setattr(observability, "_client", client)
    monkeypatch.setattr(observability, "_configured", True)

    assert observability.get_langfuse_trace_url("trace-1") is None


def test_langfuse_client_receives_environment_release_and_sampling(monkeypatch):
    import observability

    captured = {}

    def fake_create(config):
        captured.update(config.__dict__)
        return FakeLangfuseClient()

    monkeypatch.setattr(observability, "_create_langfuse_client", fake_create)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "test")
    monkeypatch.setenv("LANGFUSE_RELEASE", "2026.07.23")
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.25")

    assert observability.configure_langfuse() is True

    assert captured["environment"] == "test"
    assert captured["release"] == "2026.07.23"
    assert captured["sample_rate"] == 0.25
    assert captured["capture_model_io"] is False


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("-0.2", 0.0), ("1.7", 1.0), ("invalid", None)],
)
def test_langfuse_sampling_is_clamped_to_sdk_range(monkeypatch, configured, expected):
    """采样率越界时收敛到 0-1，非法值不传给 SDK。"""
    from observability.config import LangfuseConfig

    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", configured)

    assert LangfuseConfig.from_env().sample_rate == expected


def test_managed_prompt_uses_langfuse_with_local_fallback(monkeypatch):
    import observability
    from ai.prompts.interview import build_planner_prompt

    class FakePrompt:
        is_fallback = False

        def compile(self, **values):
            return f"remote planner {values['max_questions']} {values['round_type']}"

    class PromptClient(FakeLangfuseClient):
        def __init__(self):
            super().__init__()
            self.prompt_calls = []

        def get_prompt(self, name, **kwargs):
            self.prompt_calls.append((name, kwargs))
            return FakePrompt()

    client = PromptClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")

    rendered = build_planner_prompt(
        round_index=1,
        round_type="tech_initial",
        max_questions=5,
        strategy_focus="基础",
        requirements="覆盖项目",
        planning_context="【job_description】Python 后端",
    )

    assert rendered == "remote planner 5 tech_initial"
    assert client.prompt_calls[0][0] == "interview.planner"
    assert client.prompt_calls[0][1]["label"] == "production"
    assert "fallback" in client.prompt_calls[0][1]
    assert client.prompt_calls[0][1]["max_retries"] == 0
    assert client.prompt_calls[0][1]["fetch_timeout_seconds"] == pytest.approx(0.05)


def test_managed_prompt_is_opt_in_and_defaults_to_local(monkeypatch):
    from ai.prompts.interview import build_opening_prompt

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    rendered = build_opening_prompt(
        round_index=1,
        round_type="tech_initial",
        strategy_focus="基础",
        first_question="介绍一下项目",
    )

    assert "介绍一下项目" in rendered
    assert "专业、克制的面试官" in rendered


def test_record_trace_score_writes_score_without_breaking_business(monkeypatch):
    import observability

    class ScoreClient(FakeLangfuseClient):
        def __init__(self):
            super().__init__()
            self.scores = []
            self.current_scores = []

        def create_score(self, **kwargs):
            self.scores.append(kwargs)

        def score_current_trace(self, **kwargs):
            self.current_scores.append(kwargs)

    client = ScoreClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    assert observability.record_trace_score(
        name="dialogue_quality",
        value=0.92,
        trace_id="trace-1",
        data_type="NUMERIC",
        comment="离线评估通过",
        metadata={"suite": "deepeval"},
    ) is True
    assert client.scores == [{
        "name": "dialogue_quality",
        "value": 0.92,
        "trace_id": "trace-1",
        "data_type": "NUMERIC",
        "comment": "离线评估通过",
        "metadata": {"suite": "deepeval"},
    }]

    assert observability.record_trace_score(name="manual_acceptance", value="pass") is True
    assert client.current_scores[0]["name"] == "manual_acceptance"


def test_provider_aware_factory_uses_native_deepseek_and_metadata(monkeypatch):
    from ai.llm import llms

    created = {}

    class FakeDeepSeek:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(llms, "ChatDeepSeek", FakeDeepSeek)
    monkeypatch.setattr(llms, "validate_outbound_url", lambda *_args, **_kwargs: None)

    llm = llms.create_llm_from_config(
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        provider="deepseek",
    )

    assert isinstance(llm, FakeDeepSeek)
    assert created["model"] == "deepseek-chat"
    assert created["metadata"]["model_provider"] == "deepseek"
    assert created["metadata"]["model_integration"] == "deepseek"
    assert getattr(llm, "_model_provider") == "deepseek"


def test_provider_aware_factory_uses_native_qwen_for_dashscope(monkeypatch):
    from ai.llm import llms

    created = {}

    class FakeQwen:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(llms, "ChatQwen", FakeQwen)
    monkeypatch.setattr(llms, "validate_outbound_url", lambda *_args, **_kwargs: None)

    llm = llms.create_llm_from_config(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        provider="aliyun",
    )

    assert isinstance(llm, FakeQwen)
    assert created["model"] == "qwen-plus"
    assert created["metadata"]["model_provider"] == "qwen"
    assert created["metadata"]["model_integration"] == "qwen"


@pytest.mark.asyncio
async def test_langfuse_span_output_keeps_model_events_summarized(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_INCLUDE_MODEL_EVENTS_IN_SPAN_OUTPUT", raising=False)

    async with observability.agent_observation(
        name="agent-run",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        input_payload={"turn": 1},
    ):
        observability.record_model_event(
            event_type="llm.request.started",
            model_name="qwen-plus",
            model_provider="qwen",
        )
        observability.record_model_event(
            event_type="llm.request.completed",
            model_name="qwen-plus",
            model_provider="qwen",
            model_duration_ms=42,
        )

    output = client.observations[0][1].updates[0]["output"]
    assert output["model_event_count"] == 2
    assert output["model_event_summary"]["interview"]["completed_count"] == 1
    assert "model_events" not in output


def test_legacy_raw_model_io_setting_is_ignored_for_credential_safety(monkeypatch):
    """The legacy setting cannot re-enable callbacks that see provider credentials."""
    from observability.config import LangfuseConfig

    monkeypatch.setenv("LANGFUSE_CAPTURE_MODEL_IO", "true")

    assert LangfuseConfig.from_env().capture_model_io is False


@pytest.mark.asyncio
async def test_langfuse_can_export_safe_model_event_details_without_raw_callback(monkeypatch):
    """The safe detail setting exposes diagnostics but never model credentials or source text."""
    import observability

    client = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_INCLUDE_MODEL_EVENTS_IN_SPAN_OUTPUT", "true")
    monkeypatch.setenv("LANGFUSE_CAPTURE_MODEL_IO", "true")

    async with observability.agent_observation(
        name="agent-run",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        input_payload={"turn": 1},
    ):
        observability.record_model_event(
            event_type="llm.request.completed",
            model_name="safe-model",
            model_provider="safe-provider",
            stage="session_report.review.technical_depth",
            input_tokens=120,
            output_tokens=40,
            total_tokens=160,
            model_duration_ms=42,
            source_breakdown={"qa_history": 500, "resume": 120},
            api_key="must-not-be-exported",
        )

    output = client.observations[0][1].updates[0]["output"]
    exported = output["model_events"][0]
    assert exported["model_name"] == "safe-model"
    assert exported["stage"] == "session_report.review.technical_depth"
    assert exported["source_breakdown"] == {"qa_history": 500, "resume": 120}
    assert "api_key" not in exported
    assert "must-not-be-exported" not in repr(output)
    assert observability.get_langchain_callbacks() == []
