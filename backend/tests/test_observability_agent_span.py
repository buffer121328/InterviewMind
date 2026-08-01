"""agent_observation 观测跨度：安全 IO、脱敏、嵌套 trace 与运行链接的离线测试。"""

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

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
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
        assert observability.get_langchain_callbacks() == []
        observation.set_output({"changes": 2, "has_errors": False})

    assert client.observations[0][0] == {
        "as_type": "span",
        "name": "resume-pipeline",
        "trace_context": {"trace_id": observation.trace_id},
    }
    assert attributes == [
        {
            "trace_name": "resume-pipeline",
            "user_id": observability._trace_fingerprint("user-1"),
            "session_id": observability._trace_fingerprint("resume-1"),
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
async def test_agent_observation_redacts_arbitrary_business_text_before_langfuse(monkeypatch):
    """即使调用方误传简历、回答或密钥，根 span 也只保留长度和指纹。"""
    import observability

    client = FakeLangfuseClient()

    @contextmanager
    def fake_propagate_attributes(**_kwargs):
        yield

    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setattr(observability, "_get_propagate_attributes", lambda: fake_propagate_attributes)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    async with observability.agent_observation(
        name="privacy-boundary",
        agent_type="resume",
        user_id="candidate@example.com",
        session_id="private-session",
        input_payload={
            "resume_content": "候选人手机号 13800000000",
            "api_key": "sk-private-value",
            "mode": "optimize",
            "sk-private-field-name-123456": "field value",
            "missing": ["私密技能关键词"],
        },
    ) as observation:
        observation.set_output({
            "answer": "这是不应外发的面试回答",
            "status": "completed",
        })

    update = client.observations[0][1].updates[0]
    serialized = repr(update)
    assert "13800000000" not in serialized
    assert "sk-private-value" not in serialized
    assert "sk-private-field-name-123456" not in serialized
    assert "私密技能关键词" not in serialized
    assert "不应外发的面试回答" not in serialized
    assert update["input"]["resume_content"]["redacted"] is True
    assert update["input"]["api_key"] == "***REDACTED***"
    assert update["input"]["mode"] == "optimize"
    assert update["input"]["missing"] == {"item_count": 1}
    assert update["output"]["answer"]["redacted"] is True
    assert update["output"]["status"] == "completed"


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
            "trace_id": root.trace_id,
            "event_type": "llm.request.completed",
            "model_name": "model-test",
        }
    ]
    assert persisted == [("run-1", root.trace_id)]


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
            "user_id": observability._trace_fingerprint("user-1"),
            "session_id": observability._trace_fingerprint("session-1"),
            "metadata": {
                "agent_type": "voice",
                "trace_id": observation.trace_id,
                "agent_run_id": observability._trace_fingerprint("run-1"),
            },
        }
    ]
    assert client.observations[0][1].updates[0]["output"]["agent_run_id"] == observability._trace_fingerprint("run-1")
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
            "trace_id": observation.trace_id,
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
    assert update["output"]["error"]["type"] == "RuntimeError"
    assert update["output"]["error"]["message"]["redacted"] is True
    assert "upstream failed" not in repr(update["output"])
    assert "trace_id" in update["output"]


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
    assert observation.model_events == []
    assert observation.runtime_events is not None
    assert len(observation.runtime_events) == 1
    event = observation.runtime_events[0]
    assert event["agent_name"] == "browser_automation"
    assert event["dependency"] == "browser_automation"
    assert event["event_type"] == "external_io.completed"
    assert event["operation"] == "browser_automation.post"
    assert event["item_count"] == 1
    assert event["schema_version"] == 1
    assert event["status"] == "completed"
    assert event["trace_id"] == observation.trace_id
    assert isinstance(event["duration_ms"], int)
    assert event["duration_ms"] >= 0
    assert "private/path" not in str(observation.runtime_events)
    assert "private resume" not in str(observation.runtime_events)
    assert "browser.internal" not in str(observation.runtime_events)
    observability._reset_langfuse_for_tests()
