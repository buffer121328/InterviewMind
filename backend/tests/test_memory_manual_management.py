"""Manual memory management and mem0 scope regression tests."""

import pytest

from ai.memory.service import AgentMemoryService


class _FakeMemory:
    def __init__(self):
        self.add_calls = []
        self.update_calls = []

    def add(self, *args, **kwargs):
        self.add_calls.append((args, kwargs))
        return {"results": [{"id": "memory-1", "memory": args[0] if args else ""}]}

    def get_all(self, **_kwargs):
        return {"results": [{"id": "memory-1", "memory": "old content"}]}

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"message": "Memory updated successfully!"}


@pytest.mark.asyncio
async def test_manual_add_stores_raw_content_without_inference():
    memory = _FakeMemory()
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    result = await service.add_memory(
        user_id="user-1",
        content="我偏好使用 FastAPI",
        memory_type="preference",
    )

    assert result["results"][0]["id"] == "memory-1"
    args, kwargs = memory.add_calls[0]
    assert args == ("我偏好使用 FastAPI",)
    assert kwargs["user_id"] == "user-1"
    assert kwargs["agent_id"] == "interview-agent"
    assert kwargs["infer"] is False
    assert kwargs["run_id"] == "manual-memory"
    assert kwargs["metadata"]["memory_type"] == "preference"


@pytest.mark.asyncio
async def test_update_memory_checks_owner_before_calling_mem0():
    memory = _FakeMemory()
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    result = await service.update_memory(
        user_id="user-1",
        memory_id="memory-1",
        content="我偏好使用 Python",
    )

    assert result == {"message": "Memory updated successfully!"}
    assert memory.update_calls == [{"memory_id": "memory-1", "data": "我偏好使用 Python"}]


@pytest.mark.asyncio
async def test_interaction_uses_agent_and_run_scope_for_contextual_memory():
    memory = _FakeMemory()
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    await service.add_interaction(
        user_id="user-1",
        session_id="session-1",
        user_message="我今天完成了 FastAPI 项目",
        assistant_message="记下了。",
    )

    _, kwargs = memory.add_calls[0]
    assert kwargs["agent_id"] == "interview-agent"
    assert kwargs["run_id"] == "session-1"
