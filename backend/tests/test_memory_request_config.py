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
    }
    await memory_service_module.close_agent_memory_service()
