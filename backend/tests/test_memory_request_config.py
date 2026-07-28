"""Regression tests for request-scoped mem0 model configuration."""

import pytest

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
