"""模型事件、callback 接线、LLM 工厂与 token/成本归一化的离线测试。"""

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


def test_langchain_callback_requires_explicit_raw_model_io_opt_in(monkeypatch):
    """官方 callback 会携带完整 prompt/output，因此必须显式启用。"""
    import observability

    class FakeCallbackHandler:
        pass

    monkeypatch.setattr(observability, "_client", FakeLangfuseClient())
    monkeypatch.setattr(observability, "_configured", True)
    monkeypatch.setattr(observability, "_get_callback_handler", lambda: FakeCallbackHandler)

    assert observability.get_langchain_callbacks() == []

    monkeypatch.setenv("LANGFUSE_CAPTURE_MODEL_IO", "true")
    monkeypatch.setattr(observability, "_config", None)
    callbacks = observability.get_langchain_callbacks()

    assert len(callbacks) == 1
    assert isinstance(callbacks[0], FakeCallbackHandler)


def test_llm_factory_attaches_langfuse_callback_only_when_active(monkeypatch):
    from ai.llm import llms

    created = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(llms, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llms, "get_langchain_callbacks", lambda: ["langfuse-callback"])
    monkeypatch.setattr(llms, "validate_outbound_url", lambda *_args, **_kwargs: None)

    llms.create_llm_from_config(
        api_key="test-key",
        base_url="https://example.test",
        model="gpt-test",
    )

    assert created["callbacks"] == ["langfuse-callback"]
    assert created["model_name"] == "gpt-test"


def test_langfuse_callback_handler_dependency_is_available():
    from observability import _get_callback_handler

    callback_handler = _get_callback_handler()

    assert callable(callback_handler)


@pytest.mark.asyncio
async def test_langgraph_config_uses_official_callback_and_suppresses_direct_llm_callbacks(monkeypatch):
    import observability

    class FakeCallbackHandler:
        pass

    client = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_callback_handler", lambda: FakeCallbackHandler)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_CAPTURE_MODEL_IO", "true")

    config = observability.with_langgraph_langfuse_config(
        {"configurable": {"thread_id": "thread-1"}, "metadata": {"existing": "yes"}},
        run_name="interview-turn",
        metadata={"agent_type": "interview"},
    )

    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["run_name"] == "interview-turn"
    assert config["metadata"] == {"existing": "yes", "agent_type": "interview"}
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], FakeCallbackHandler)

    async with observability.agent_observation(
        name="interview-runtime",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        input_payload={},
    ):
        assert len(observability.get_langchain_callbacks()) == 1
        with observability.langgraph_langfuse_scope(True):
            assert observability.get_langchain_callbacks() == []


@pytest.mark.asyncio
async def test_model_pool_callback_records_input_budget_without_private_content():
    import observability
    from ai.llm.model_pool import _ModelPoolCallback

    class Scheduler:
        def start(self, _identity):
            return None

        def record_success(self, _identity):
            return None

        def record_failure(self, _identity):
            return None

    callback = _ModelPoolCallback(
        Scheduler(),  # type: ignore[arg-type]
        "https://private.example/v1|model-x|secret-hash",
        channel="smart",
        model_name="model-x",
        candidate_count=2,
        candidate_index=1,
        output_token_limit=2048,
    )

    async with observability.agent_observation(
        name="budget-test",
        agent_type="test",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "budget"},
    ) as observation:
        with observability.model_call_metadata_scope(
            attempt=2,
            deadline_ms=10_000,
            deadline_remaining_ms=4_000,
            truncated_sources=["history"],
        ):
            callback.on_chat_model_start(
                messages=[[{"role": "system", "content": "private-system"}, {"role": "user", "content": "private-resume"}]],
                run_id="run-budget-1",
            )
            callback.on_llm_end(run_id="run-budget-1")

    assert len(observation.model_events) == 2
    started, completed = observation.model_events
    assert started["event_type"] == "llm.request.started"
    assert started["input_chars"] == len("private-systemprivate-resume")
    assert started["estimated_input_tokens"] > 0
    assert started["source_breakdown"] == {
        "system": len("private-system"),
        "human": len("private-resume"),
    }
    assert started["attempt"] == 2
    assert started["deadline_remaining_ms"] == 4_000
    assert started["truncated_sources"] == ["history"]
    assert "private-system" not in str(observation.model_events)
    assert "private-resume" not in str(observation.model_events)
    assert "private.example" not in str(observation.model_events)
    assert completed["event_type"] == "llm.request.completed"
    assert completed["model_duration_ms"] >= 0
    assert completed["total_duration_ms"] >= completed["model_duration_ms"]


@pytest.mark.asyncio
async def test_record_model_event_drops_raw_payload_fields():
    import observability

    async with observability.agent_observation(
        name="safe-event-test",
        agent_type="test",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "safe-event"},
    ) as observation:
        observability.record_model_event(
            event_type="llm.request.started",
            prompt="private prompt",
            resume="private resume",
            api_key="sk-private",
            input_chars=14,
        )

    assert observation.model_events == [
        {
            "agent_name": "test",
            "trace_id": observation.trace_id,
            "event_type": "llm.request.started",
            "input_chars": 14,
        }
    ]


def test_summarize_model_events_reports_latency_timeout_retry_and_fallback_rates():
    import observability

    summary = observability.summarize_model_events([
        {"agent_name": "planner", "event_type": "llm.request.started", "attempt": 1, "fallback_index": 0},
        {"agent_name": "planner", "event_type": "llm.request.failed", "failure_type": "timeout", "model_duration_ms": 100},
        {"agent_name": "planner", "event_type": "llm.request.started", "attempt": 2, "fallback_index": 1},
        {"agent_name": "planner", "event_type": "llm.request.completed", "model_duration_ms": 300},
    ])

    assert summary["planner"] == {
        "call_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "p50_model_duration_ms": 100,
        "p95_model_duration_ms": 300,
        "timeout_rate": 0.5,
        "retry_rate": 0.5,
        "fallback_rate": 0.5,
    }


def test_model_input_fingerprint_changes_when_same_length_content_changes():
    import observability

    first = observability.measure_model_input("resume-A")
    second = observability.measure_model_input("resume-B")

    assert first["input_chars"] == second["input_chars"]
    assert first["input_fingerprint"] != second["input_fingerprint"]
    assert "resume-A" not in str(first)


def test_token_usage_and_local_cny_cost_are_normalized(monkeypatch):
    import observability

    class Response:
        usage_metadata = {
            "input_tokens": 1_000,
            "output_tokens": 500,
            "total_tokens": 1_500,
            "cached_tokens": 100,
        }

    monkeypatch.setenv(
        "MODEL_PRICE_REGISTRY",
        '{"qwen-plus":{"currency":"CNY","input_per_1m":0.8,"output_per_1m":2.0}}',
    )

    usage = observability.extract_token_usage(Response())
    cost = observability.estimate_model_cost(
        pricing_key="qwen-plus",
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
    )

    assert usage == {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "cache_read_tokens": 100,
        "reasoning_tokens": None,
    }
    assert cost == {
        "usage_status": "available",
        "cost_status": "estimated",
        "cost_currency": "CNY",
        "cost_source": "local_pricelist",
        "estimated_cost_cny": 0.0018,
    }
