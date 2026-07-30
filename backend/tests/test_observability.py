"""Langfuse 观测适配层的离线单元测试。"""

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
        "LANGFUSE_PROMPT_MANAGEMENT_ENABLED",
        "LANGFUSE_PROMPT_LABEL",
        "LANGFUSE_PROMPT_CACHE_TTL_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    observability._reset_langfuse_for_tests()
    yield
    observability._reset_langfuse_for_tests()


@pytest.mark.asyncio
async def test_agent_observation_is_noop_without_langfuse_configuration():
    import observability

    async with observability.agent_observation(
        name="interview-runtime",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        input_payload={"question_count": 3},
    ) as observation:
        assert observation.enabled is False
        assert observability.get_langchain_callbacks() == []
        observation.set_output({"message_count": 1})


@pytest.mark.asyncio
async def test_agent_observation_records_safe_input_output_and_trace_attributes(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    attributes = []

    @contextmanager
    def fake_propagate_attributes(**kwargs):
        attributes.append(kwargs)
        yield

    class FakeCallbackHandler:
        pass

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
    monkeypatch.setattr(observability, "_get_callback_handler", lambda: FakeCallbackHandler)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    async with observability.agent_observation(
        name="resume-pipeline",
        agent_type="resume",
        user_id="user-1",
        session_id="resume-1",
        input_payload={"resume_length": 128},
    ) as observation:
        assert observation.enabled is True
        assert len(observability.get_langchain_callbacks()) == 1
        observation.set_output({"changes": 2, "has_errors": False})

    assert client.observations[0][0] == {
        "as_type": "span",
        "name": "resume-pipeline",
        "trace_context": {"trace_id": observation.trace_id},
    }
    assert attributes == [
        {
            "trace_name": "resume-pipeline",
            "user_id": "user-1",
            "session_id": "resume-1",
            "metadata": {"agent_type": "resume", "trace_id": observation.trace_id},
        }
    ]
    assert client.observations[0][1].updates == [
        {
            "input": {"resume_length": 128},
            "output": {
                "trace_id": observation.trace_id,
                "changes": 2,
                "has_errors": False,
            },
        }
    ]


@pytest.mark.asyncio
async def test_nested_agent_observation_reuses_root_trace_and_persists_once(monkeypatch):
    """Nested workflow spans must remain in the AgentRun root trace."""
    import observability

    client = FakeLangfuseClient()
    persisted = []

    @contextmanager
    def fake_propagate_attributes(**_kwargs):
        yield

    class FakeRunService:
        async def record_observation(self, run_id, *, trace_id):
            persisted.append((run_id, trace_id))

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
    monkeypatch.setattr(observability, "_get_agent_run_service", lambda: FakeRunService())
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    async with observability.agent_observation(
        name="agent-run-resume-workspace",
        agent_type="resume_workspace",
        user_id="user-1",
        session_id=None,
        run_id="run-1",
        input_payload={"task_type": "resume_workspace"},
    ) as root:
        async with observability.agent_observation(
            name="resume-pipeline",
            agent_type="resume",
            user_id="user-1",
            session_id=None,
            run_id="run-1",
            input_payload={"resume_length": 128},
        ) as child:
            observability.record_model_event(
                event_type="llm.request.completed",
                model_name="model-test",
            )
            child.set_output({"changes": 1})

    assert child.trace_id == root.trace_id
    assert client.observations[0][0]["trace_context"] == {"trace_id": root.trace_id}
    assert client.observations[1][0] == {
        "as_type": "span",
        "name": "resume-pipeline",
    }
    assert root.model_events == [
        {
            "agent_name": "resume",
            "event_type": "llm.request.completed",
            "model_name": "model-test",
        }
    ]
    assert persisted == [("run-1", root.trace_id)]


def test_langchain_callback_is_available_without_an_agent_root(monkeypatch):
    """Direct model workflows still create standalone Langfuse traces."""
    import observability

    class FakeCallbackHandler:
        pass

    monkeypatch.setattr(observability, "_client", FakeLangfuseClient())
    monkeypatch.setattr(observability, "_configured", True)
    monkeypatch.setattr(observability, "_get_callback_handler", lambda: FakeCallbackHandler)

    callbacks = observability.get_langchain_callbacks()

    assert len(callbacks) == 1
    assert isinstance(callbacks[0], FakeCallbackHandler)


@pytest.mark.asyncio
async def test_agent_observation_links_langfuse_trace_to_agent_run(monkeypatch):
    import observability

    client = FakeLangfuseClient()
    attributes = []
    persisted = []

    @contextmanager
    def fake_propagate_attributes(**kwargs):
        attributes.append(kwargs)
        yield

    class FakeRunService:
        async def record_observation(self, run_id, *, trace_id):
            persisted.append((run_id, trace_id))

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
    monkeypatch.setattr(observability, "_get_agent_run_service", lambda: FakeRunService())
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    async with observability.agent_observation(
        name="voice-interview",
        agent_type="voice",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        input_payload={"turn": 1},
    ) as observation:
        observability.record_model_event(
            event_type="voice.request.completed",
            channel="voice",
            model_name="gpt-voice",
            model_member="member-1",
            duration_ms=42,
        )
        observation.set_output({"ok": True})

    assert attributes == [
        {
            "trace_name": "voice-interview",
            "user_id": "user-1",
            "session_id": "session-1",
            "metadata": {
                "agent_type": "voice",
                "trace_id": observation.trace_id,
                "agent_run_id": "run-1",
            },
        }
    ]
    assert client.observations[0][1].updates[0]["output"]["agent_run_id"] == "run-1"
    assert persisted == [
        (
            "run-1",
            observation.trace_id,
        )
    ]


@pytest.mark.asyncio
async def test_agent_observation_collects_model_events_without_langfuse():
    import observability

    async with observability.agent_observation(
        name="voice-interview",
        agent_type="voice",
        user_id="user-1",
        session_id="session-1",
        input_payload={"turn": 1},
    ) as observation:
        observability.record_model_event(
            event_type="llm.request.completed",
            model_name="gpt-test",
            model_member="member-1",
            input_tokens=12,
            output_tokens=4,
        )
        observation.set_output({"ok": True})

    assert observation.model_events == [
        {
            "agent_name": "voice",
            "event_type": "llm.request.completed",
            "model_name": "gpt-test",
            "model_member": "member-1",
            "input_tokens": 12,
            "output_tokens": 4,
        }
    ]


@pytest.mark.asyncio
async def test_agent_observation_does_not_persist_fake_trace_without_langfuse(monkeypatch):
    """A disabled Langfuse client must not create a misleading Run Center trace link."""
    import observability

    persisted = []

    class FakeRunService:
        async def record_observation(self, run_id, *, trace_id):
            persisted.append((run_id, trace_id))

    monkeypatch.setattr(observability, "_get_agent_run_service", lambda: FakeRunService())

    async with observability.agent_observation(
        name="interview-report",
        agent_type="interview_report",
        user_id="user-1",
        session_id="session-1",
        run_id="run-1",
        input_payload={"session_id": "session-1"},
    ):
        pass

    assert persisted == []


@pytest.mark.asyncio
async def test_agent_observation_preserves_business_exception(monkeypatch):
    import observability

    client = FakeLangfuseClient()

    @contextmanager
    def fake_propagate_attributes(**kwargs):
        yield

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    with pytest.raises(RuntimeError, match="upstream failed"):
        async with observability.agent_observation(
            name="interview-runtime",
            agent_type="interview",
            user_id="user-1",
            session_id="session-1",
            input_payload={"question_count": 1},
        ):
            raise RuntimeError("upstream failed")

    update = client.observations[0][1].updates[0]
    assert update["input"] == {"question_count": 1}
    assert update["output"]["error"] == {"type": "RuntimeError", "message": "upstream failed"}
    assert "trace_id" in update["output"]


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


@pytest.mark.asyncio
async def test_agent_observation_records_rag_trace_without_raw_private_content(monkeypatch):
    """RAG 观测只记录模式、计数和 trace，不把 JD/简历/证据正文写入 Langfuse 输出。"""
    import observability
    from ai.agents.interview.interview_rag import RagEvidence, RagResult

    client = FakeLangfuseClient()
    attributes = []

    @contextmanager
    def fake_propagate_attributes(**kwargs):
        attributes.append(kwargs)
        yield

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    rag_result = RagResult(
        retrieval_mode="structured",
        evidences=[RagEvidence(
            source_type="candidate_material",
            source_id="material-1",
            evidence="候选人私密项目细节不应进入观测输出",
            retrieval_score=0.8,
        )],
        query_used="原始 JD 正文不应进入观测输出",
        retrieval_trace={
            "duration_ms": 12.5,
            "total_candidates": 3,
            "evidence_count": 1,
            "source_counts": {"candidate_material": 1},
            "agentic_mode": "shadow",
            "agentic_triggered": False,
            "agentic_adopted": False,
            "search_rounds": 0,
            "initial_quality_issues": [],
            "final_quality_issues": [],
            "agentic_error_type": None,
        },
    )

    async with observability.agent_observation(
        name="interview-rag",
        agent_type="interview",
        user_id="user-1",
        session_id="session-1",
        input_payload={"jd_length": 128, "resume_length": 256},
    ) as observation:
        observation.set_output({
            "retrieval_mode": rag_result.retrieval_mode,
            "evidence_count": len(rag_result.evidences),
            "rag_trace": rag_result.retrieval_trace,
        })

    output = client.observations[0][1].updates[0]["output"]
    assert output["retrieval_mode"] == "structured"
    assert output["evidence_count"] == 1
    assert output["rag_trace"]["source_counts"] == {"candidate_material": 1}

    output_text = repr(output)
    assert "候选人私密项目细节" not in output_text
    assert "原始 JD 正文" not in output_text
    assert attributes[0]["metadata"]["agent_type"] == "interview"


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
        {"agent_name": "test", "event_type": "llm.request.started", "input_chars": 14}
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


@pytest.mark.asyncio
async def test_browser_automation_event_records_only_timing_and_count(monkeypatch):
    import httpx
    from pydantic import SecretStr

    import observability
    from app.config import AppSettings
    from integrations.browser_automation.client import BrowserAutomationClient

    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    observability._reset_langfuse_for_tests()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(200, json={"success": True})

    client = BrowserAutomationClient(
        AppSettings(
            browser_automation_service_url="https://browser.internal",
            browser_automation_service_token=SecretStr("x" * 32),
        ),
        transport=httpx.MockTransport(handler),
    )

    async with observability.agent_observation(
        name="browser-test",
        agent_type="browser_automation",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "browser"},
    ) as observation:
        result = await client.post("/private/path", {"resume": "private resume"})

    assert result == {"success": True}
    assert observation.model_events == [
        {
            "agent_name": "browser_automation",
            "event_type": "external_io.completed",
            "operation": "browser_automation.post",
            "duration_ms": observation.model_events[0]["duration_ms"],
            "item_count": 1,
            "status": "completed",
            "degraded": False,
        }
    ]
    assert "private/path" not in str(observation.model_events)
    assert "private resume" not in str(observation.model_events)
    assert "browser.internal" not in str(observation.model_events)
    observability._reset_langfuse_for_tests()


def test_provider_aware_factory_uses_native_deepseek_and_metadata(monkeypatch):
    from ai.llm import llms

    created = {}

    class FakeDeepSeek:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(llms, "ChatDeepSeek", FakeDeepSeek)
    monkeypatch.setattr(llms, "get_langchain_callbacks", lambda: [])
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
    monkeypatch.setattr(llms, "get_langchain_callbacks", lambda: [])
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
