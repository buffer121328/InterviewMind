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


def test_langchain_callback_is_disabled_even_when_legacy_raw_model_io_opt_in_is_set(monkeypatch):
    """Provider API keys can appear in serialized callback params, so raw callbacks stay disabled."""
    import observability

    monkeypatch.setattr(observability, "_client", FakeLangfuseClient())
    monkeypatch.setattr(observability, "_configured", True)
    monkeypatch.setattr(
        observability,
        "_get_callback_handler",
        lambda: (_ for _ in ()).throw(AssertionError("raw callback must not be created")),
    )
    monkeypatch.setenv("LANGFUSE_CAPTURE_MODEL_IO", "true")
    monkeypatch.setattr(observability, "_config", None)

    assert observability.get_langchain_callbacks() == []
    assert observability.get_langgraph_callbacks() == []


def test_llm_factory_never_attaches_raw_langfuse_callback(monkeypatch):
    from ai.llm import llms

    created = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(llms, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llms, "validate_outbound_url", lambda *_args, **_kwargs: None)

    llms.create_llm_from_config(
        api_key="test-key",
        base_url="https://example.test",
        model="gpt-test",
    )

    assert "callbacks" not in created
    assert "test-key" not in repr(created["metadata"])
    assert created["model_name"] == "gpt-test"
    assert created["streaming"] is True


def test_langfuse_callback_handler_dependency_is_available():
    from observability import _get_callback_handler

    callback_handler = _get_callback_handler()

    assert callable(callback_handler)


@pytest.mark.asyncio
async def test_langgraph_config_keeps_existing_callbacks_but_never_adds_raw_langfuse_callback(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    existing_callback = object()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(
        observability,
        "_get_callback_handler",
        lambda: (_ for _ in ()).throw(AssertionError("raw callback must not be created")),
    )
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_CAPTURE_MODEL_IO", "true")

    config = observability.with_langgraph_langfuse_config(
        {"configurable": {"thread_id": "thread-1"}, "metadata": {"existing": "yes"}, "callbacks": [existing_callback]},
        run_name="interview-turn",
        metadata={"agent_type": "interview"},
    )

    assert config["configurable"] == {"thread_id": "thread-1"}
    assert config["run_name"] == "interview-turn"
    assert config["metadata"] == {"existing": "yes", "agent_type": "interview"}
    assert config["callbacks"] == [existing_callback]

    async with observability.agent_observation(
        name="interview-runtime",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        input_payload={},
    ):
        assert observability.get_langchain_callbacks() == []
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
async def test_model_pool_callback_records_first_non_empty_chunk_duration(monkeypatch):
    import observability
    from ai.llm import model_pool

    class Scheduler:
        def start(self, _identity):
            return None

        def record_success(self, _identity):
            return None

        def record_failure(self, _identity):
            return None

    ticks = iter((100.0, 100.125, 100.2, 100.2))
    monkeypatch.setattr(model_pool, "monotonic", lambda: next(ticks))
    callback = model_pool._ModelPoolCallback(
        Scheduler(),  # type: ignore[arg-type]
        "identity",
        model_name="model-x",
    )

    async with observability.agent_observation(
        name="ttft-test",
        agent_type="test",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "ttft"},
    ) as observation:
        callback.on_chat_model_start(messages=[[{"role": "user", "content": "private"}]], run_id="run-ttft-1")
        callback.on_llm_new_token("", run_id="run-ttft-1")
        callback.on_llm_new_token("   ", run_id="run-ttft-1")
        callback.on_llm_new_token("first private token", run_id="run-ttft-1")
        callback.on_llm_new_token("later token", run_id="run-ttft-1")
        callback.on_llm_end(run_id="run-ttft-1")

    assert observation.model_events is not None
    completed = observation.model_events[-1]
    assert completed["first_chunk_duration_ms"] == 125
    assert "first private token" not in str(observation.model_events)
    assert "later token" not in str(observation.model_events)


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
            source_raw_breakdown={"resume": 5460},
            source_raw_token_breakdown={"resume": 3817},
        )

    assert observation.model_events == [
        {
            "agent_name": "test",
            "trace_id": observation.trace_id,
            "event_type": "llm.request.started",
            "input_chars": 14,
            "source_raw_breakdown": {"resume": 5460},
            "source_raw_token_breakdown": {"resume": 3817},
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
        "prompt_cache_hit_tokens": None,
        "prompt_cache_miss_tokens": None,
        "reasoning_tokens": None,
    }
    assert cost == {
        "usage_status": "confirmed",
        "cost_status": "estimated",
        "cost_currency": "CNY",
        "cost_source": "local_pricelist",
        "estimated_cost_cny": 0.0018,
    }


def test_deepseek_cache_usage_merges_provider_fields_with_langchain_usage():
    """DeepSeek cache counters can coexist with LangChain's normalized totals."""
    import observability

    class Response:
        usage_metadata = {
            "input_tokens": 1200,
            "output_tokens": 300,
            "total_tokens": 1500,
        }
        response_metadata = {
            "token_usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 300,
                "prompt_cache_hit_tokens": 800,
                "prompt_cache_miss_tokens": 400,
            }
        }

    assert observability.extract_token_usage(Response()) == {
        "input_tokens": 1200,
        "output_tokens": 300,
        "total_tokens": 1500,
        "cache_read_tokens": 800,
        "prompt_cache_hit_tokens": 800,
        "prompt_cache_miss_tokens": 400,
        "reasoning_tokens": None,
    }


def test_deepseek_zero_hit_usage_remains_a_reported_cache_miss():
    import observability

    class Response:
        response_metadata = {
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 50,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 500,
            }
        }

    usage = observability.extract_token_usage(Response())

    assert usage["cache_read_tokens"] == 0
    assert usage["prompt_cache_hit_tokens"] == 0
    assert usage["prompt_cache_miss_tokens"] == 500


@pytest.mark.asyncio
async def test_deepseek_cache_usage_is_recorded_as_safe_hit_event():
    import observability
    from ai.llm.model_pool import _ModelPoolCallback

    class Scheduler:
        def start(self, _identity):
            return None

        def record_success(self, _identity):
            return None

        def record_failure(self, _identity):
            return None

    class Response:
        response_metadata = {
            "token_usage": {
                "prompt_tokens": 700,
                "completion_tokens": 100,
                "prompt_cache_hit_tokens": 600,
                "prompt_cache_miss_tokens": 100,
            }
        }

    callback = _ModelPoolCallback(
        Scheduler(),  # type: ignore[arg-type]
        "deepseek-cache-test",
        model_name="deepseek-chat",
        provider_metadata={
            "model_provider": "deepseek",
            "model_integration": "deepseek",
        },
    )

    async with observability.agent_observation(
        name="deepseek-cache-test",
        agent_type="test",
        user_id="user-1",
        session_id="session-1",
        input_payload={},
    ) as observation:
        with observability.model_call_metadata_scope(
            prompt_cache_eligible=True,
            prompt_cache_status="unreported",
        ):
            callback.on_chat_model_start(
                messages=[[{"role": "user", "content": "stable prefix"}]],
                run_id="deepseek-cache-run",
            )
            callback.on_llm_end(Response(), run_id="deepseek-cache-run")

    completed = observation.model_events[-1]
    assert completed["prompt_cache_status"] == "hit"
    assert completed["cache_hit"] is True
    assert completed["cache_read_tokens"] == 600
    assert completed["prompt_cache_hit_tokens"] == 600
    assert completed["prompt_cache_miss_tokens"] == 100


@pytest.mark.asyncio
async def test_deepseek_missing_cache_counters_remains_unreported():
    import observability
    from ai.llm.model_pool import _ModelPoolCallback

    class Scheduler:
        def start(self, _identity):
            return None

        def record_success(self, _identity):
            return None

        def record_failure(self, _identity):
            return None

    class Response:
        usage_metadata = {
            "input_tokens": 90,
            "output_tokens": 10,
            "total_tokens": 100,
        }

    callback = _ModelPoolCallback(
        Scheduler(),  # type: ignore[arg-type]
        "deepseek-unreported-test",
        model_name="deepseek-chat",
        provider_metadata={"model_integration": "deepseek"},
    )

    async with observability.agent_observation(
        name="deepseek-unreported-test",
        agent_type="test",
        user_id="user-1",
        session_id="session-1",
        input_payload={},
    ) as observation:
        with observability.model_call_metadata_scope(
            prompt_cache_eligible=True,
            prompt_cache_status="unreported",
        ):
            callback.on_chat_model_start(
                messages=[[{"role": "user", "content": "stable prefix"}]],
                run_id="deepseek-unreported-run",
            )
            callback.on_llm_end(Response(), run_id="deepseek-unreported-run")

    completed = observation.model_events[-1]
    assert completed["input_tokens"] == 90
    assert completed["output_tokens"] == 10
    assert completed["prompt_cache_status"] == "unreported"
    assert "cache_hit" not in completed
