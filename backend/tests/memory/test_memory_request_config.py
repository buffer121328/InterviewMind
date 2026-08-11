"""Regression tests for request-scoped mem0 model configuration."""

import pytest
from ai.memory import service as memory_service_module
from ai.workflows.memory import MemoryUseCases


@pytest.mark.asyncio
async def test_memory_list_passes_frontend_api_config_to_mem0_service(monkeypatch):
    """The memory center must not fall back to the disabled startup singleton."""
    captured: list[dict | None] = []

    class FakeMemoryService:
        is_enabled = True

        async def get_all(self, *, user_id: str, page_size: int):
            assert user_id == "user-1"
            assert page_size == 20
            return []

    async def fake_get_service(api_config=None):
        captured.append(api_config)
        return FakeMemoryService()

    monkeypatch.setattr("ai.workflows.memory.get_agent_memory_service", fake_get_service)
    api_config = {
        "mem0_llm": {"api_key": "secret", "base_url": "https://llm.example/v1", "model": "memory"},
        "mem0_embedder": {"api_key": "secret", "base_url": "https://embed.example/v1", "model": "embed"},
    }

    response = await MemoryUseCases().list_memories(
        user_id="user-1",
        page_size=20,
        api_config=api_config,
    )

    assert response.success is True
    assert captured == [api_config]


@pytest.mark.asyncio
async def test_failed_request_scoped_mem0_initialization_is_retried(monkeypatch):
    """A transient mem0 failure must not leave a disabled client cached forever."""
    await memory_service_module.close_agent_memory_service()
    attempts = 0

    async def fake_initialize(self):
        nonlocal attempts
        attempts += 1
        self._enabled = attempts > 1
        self._memory = object() if self._enabled else None
        return self._enabled

    monkeypatch.setattr(
        memory_service_module,
        "get_mem0_config",
        lambda _api_config=None: {"version": "test"},
    )
    monkeypatch.setattr(
        memory_service_module.AgentMemoryService,
        "initialize",
        fake_initialize,
    )

    first = await memory_service_module.get_agent_memory_service({"mem0_llm": {}})
    second = await memory_service_module.get_agent_memory_service({"mem0_llm": {}})

    assert first.is_enabled is False
    assert second.is_enabled is True
    assert attempts == 2
    assert memory_service_module.get_agent_memory_runtime_status() == {
        "mode": "request_scoped",
        "server_ready": False,
        "request_scoped_ready": 1,
        "readiness_category": "request_scoped_ready",
        "database_mode": "shared",
    }
    await memory_service_module.close_agent_memory_service()


@pytest.mark.asyncio
async def test_memory_list_applies_canonical_user_projection(monkeypatch):
    """The memory center omits assistant noise and normalized duplicates."""

    class FakeMemoryService:
        is_enabled = True

        async def get_all(self, *, user_id: str, page_size: int):
            assert user_id == "user-1"
            assert page_size == 20
            return [
                {
                    "id": "assistant",
                    "memory": "用户被建议每天刷题",
                    "metadata": {"source": "chat_turn"},
                },
                {"id": "old", "memory": "偏好 ＦａｓｔＡＰＩ！", "metadata": {}},
                {"id": "new", "memory": "偏好 fastapi", "metadata": {}},
            ]

    async def fake_get_service(_api_config=None):
        return FakeMemoryService()

    monkeypatch.setattr("ai.workflows.memory.get_agent_memory_service", fake_get_service)

    response = await MemoryUseCases().list_memories(
        user_id="user-1",
        page_size=20,
    )

    assert response.total == 1
    assert [item.id for item in response.memories] == ["old"]


@pytest.mark.asyncio
async def test_memory_search_applies_canonical_user_projection(monkeypatch):
    """Prompt retrieval uses the same user-focused canonical projection."""

    class FakeMemoryService:
        is_enabled = True

        async def search_memories(self, **kwargs):
            assert kwargs == {
                "user_id": "user-1",
                "query": "FastAPI",
                "limit": 5,
                "memory_types": None,
            }
            return [
                {
                    "id": "assistant",
                    "memory": "用户被建议每天刷题",
                    "metadata": {"source": "chat_turn"},
                    "score": 0.99,
                },
                {"id": "old", "memory": "偏好 ＦａｓｔＡＰＩ！", "metadata": {}, "score": 0.75},
                {"id": "best", "memory": "偏好 fastapi", "metadata": {}, "score": 0.95},
            ]

    async def fake_get_service(_api_config=None):
        return FakeMemoryService()

    monkeypatch.setattr("ai.workflows.memory.get_agent_memory_service", fake_get_service)

    response = await MemoryUseCases().search_memories(
        user_id="user-1",
        query="FastAPI",
        limit=5,
        memory_type=None,
    )

    assert response.total == 1
    assert [item.id for item in response.memories] == ["best"]


@pytest.mark.asyncio
async def test_memory_consolidation_requires_confirmation_and_passes_request_config(monkeypatch):
    """Historical mutation must be explicit and reuse request-scoped mem0 channels."""
    from ai.workflows.memory import MemoryUseCaseError
    from app.schemas.memory import MemoryConsolidateRequest

    captured = []

    class FakeMemoryService:
        is_enabled = True

        async def consolidate_existing_memories(self, **kwargs):
            captured.append(kwargs)
            return {
                "dry_run": kwargs["dry_run"],
                "total_before": 3,
                "total_after": 1,
                "counts": {"KEEP": 0, "UPDATE": 1, "DELETE": 2},
                "applied_counts": {"UPDATE": 1, "DELETE": 2} if not kwargs["dry_run"] else {},
                "operations": [],
            }

    async def fake_get_service(api_config=None):
        captured.append(api_config)
        return FakeMemoryService()

    monkeypatch.setattr("ai.workflows.memory.get_agent_memory_service", fake_get_service)
    api_config = {
        "mem0_llm": {"api_key": "secret", "base_url": "https://llm.example/v1", "model": "memory"},
        "mem0_embedder": {"api_key": "secret", "base_url": "https://embed.example/v1", "model": "embed"},
    }

    with pytest.raises(MemoryUseCaseError):
        await MemoryUseCases().consolidate_memories(
            user_id="user-1",
            request=MemoryConsolidateRequest(
                api_config=api_config,
                dry_run=False,
                confirm=False,
            ),
        )

    response = await MemoryUseCases().consolidate_memories(
        user_id="user-1",
        request=MemoryConsolidateRequest(
            api_config=api_config,
            dry_run=True,
            confirm=False,
            max_memories=50,
        ),
    )

    assert response.success is True
    assert response.dry_run is True
    assert captured[0]["mem0_llm"]["api_key"] == "secret"
    assert captured[0]["mem0_llm"]["base_url"] == "https://llm.example/v1"
    assert captured[0]["mem0_llm"]["model"] == "memory"
    assert captured[0]["mem0_embedder"]["model"] == "embed"
    assert captured[1] == {"user_id": "user-1", "dry_run": True, "max_memories": 50}


def test_memory_readiness_categories_are_sanitized(monkeypatch):
    """Health diagnostics distinguish safe categories without returning exception text or credentials."""
    from ai.memory import service as memory_service

    assert memory_service.classify_memory_initialization_error(
        RuntimeError("password authentication failed for user secret-user")
    ) == "database_authentication_failed"
    assert memory_service.classify_memory_initialization_error(
        RuntimeError("type vector does not exist")
    ) == "vector_schema_error"
    assert memory_service.classify_memory_initialization_error(
        RuntimeError("api_key=secret transport exploded")
    ) == "initialization_failed"


def test_memory_runtime_status_reports_missing_channels_and_shared_database(monkeypatch):
    """An unconfigured process exposes a stable readiness category and no connection details."""
    from ai.memory import service as memory_service

    monkeypatch.setattr(memory_service, "_agent_memory_service", None)
    monkeypatch.setattr(memory_service, "_agent_memory_services", {})
    monkeypatch.setattr(memory_service, "_last_memory_readiness_category", None)
    monkeypatch.setattr(memory_service, "get_mem0_config", lambda _api_config=None: None)
    monkeypatch.setattr(memory_service, "get_mem0_database_mode", lambda: "shared")

    status = memory_service.get_agent_memory_runtime_status()

    assert status["readiness_category"] == "model_channels_missing"
    assert status["database_mode"] == "shared"
    assert "secret" not in str(status).lower()
