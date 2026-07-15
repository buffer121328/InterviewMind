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

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture(autouse=True)
def reset_observability(monkeypatch):
    from app.services import observability

    for key in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    observability._reset_observability_for_tests()
    yield
    observability._reset_observability_for_tests()


@pytest.mark.asyncio
async def test_agent_observation_is_noop_without_langfuse_configuration():
    from app.services import observability

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
    from app.services import observability

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
    }
    assert attributes == [
        {
            "trace_name": "resume-pipeline",
            "user_id": "user-1",
            "session_id": "resume-1",
            "metadata": {"agent_type": "resume"},
        }
    ]
    assert client.observations[0][1].updates == [
        {
            "input": {"resume_length": 128},
            "output": {"changes": 2, "has_errors": False},
        }
    ]


@pytest.mark.asyncio
async def test_agent_observation_preserves_business_exception(monkeypatch):
    from app.services import observability

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

    assert client.observations[0][1].updates == [
        {
            "input": {"question_count": 1},
            "output": {"error": {"type": "RuntimeError", "message": "upstream failed"}},
        }
    ]


def test_llm_factory_attaches_langfuse_callback_only_when_active(monkeypatch):
    from app.services import llms

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
    from app.services.observability import _get_callback_handler

    callback_handler = _get_callback_handler()

    assert callback_handler.__module__.startswith("langfuse.langchain")
    assert callable(callback_handler)


def test_shutdown_observability_closes_client(monkeypatch):
    from app.services import observability

    client = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_create_langfuse_client", lambda config: client)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    assert observability.configure_observability() is True
    observability.shutdown_observability()

    assert client.shutdown_called is True
