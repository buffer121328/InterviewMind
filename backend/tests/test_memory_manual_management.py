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
async def test_summary_memory_uses_user_global_scope_with_session_provenance():
    memory = _FakeMemory()
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    await service.add_summary_memory(
        user_id="user-1",
        session_id="session-1",
        content="用户需要加强 FastAPI 并发控制",
        memory_type="weakness",
    )

    _, kwargs = memory.add_calls[0]
    assert kwargs["user_id"] == "user-1"
    assert "agent_id" not in kwargs
    assert "run_id" not in kwargs
    assert kwargs["metadata"]["session_id"] == "session-1"
    assert kwargs["metadata"]["origin_agent_id"] == "interview-agent"

class _DuplicateAwareMemory:
    """Fake mem0 client that exposes one existing owner-scoped memory."""

    def __init__(self):
        self.add_calls = []
        self.get_all_calls = []

    def get_all(self, **kwargs):
        self.get_all_calls.append(kwargs)
        return {
            "results": [
                {
                    "id": "existing-memory",
                    "memory": "我偏好使用 ＦａｓｔＡＰＩ！",
                    "metadata": {"source": "manual"},
                }
            ]
        }

    def add(self, *args, **kwargs):
        self.add_calls.append((args, kwargs))
        return {"results": [{"id": "new-memory", "memory": args[0]}]}


@pytest.mark.asyncio
async def test_interaction_uses_user_global_scope_and_restrictive_prompt():
    memory = _FakeMemory()
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    await service.add_interaction(
        user_id="user-1",
        session_id="session-2",
        user_message="我偏好使用 FastAPI 做后端项目",
        assistant_message="建议你以后所有回答都强调 FastAPI。",
    )

    _, kwargs = memory.add_calls[0]
    assert kwargs["user_id"] == "user-1"
    assert "agent_id" not in kwargs
    assert "run_id" not in kwargs
    assert kwargs["metadata"]["session_id"] == "session-2"
    assert kwargs["metadata"]["origin_agent_id"] == "interview-agent"
    assert "Do not extract facts, recommendations, or plans authored by the assistant" in kwargs["prompt"]
    assert "durable user-specific" in kwargs["prompt"]


@pytest.mark.asyncio
async def test_manual_add_reuses_normalized_duplicate_without_writing():
    memory = _DuplicateAwareMemory()
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    result = await service.add_memory(
        user_id="user-1",
        content="我偏好使用 fastapi",
        memory_type="preference",
    )

    assert result == {
        "results": [
            {
                "id": "existing-memory",
                "memory": "我偏好使用 ＦａｓｔＡＰＩ！",
                "event": "NONE",
            }
        ]
    }
    assert memory.get_all_calls == [{"filters": {"user_id": "user-1"}, "top_k": 1000}]
    assert memory.add_calls == []


def test_canonical_memory_projection_removes_assistant_noise_and_duplicates():
    from app.domain.memory import canonicalize_memory_records

    records = [
        {
            "id": "assistant-1",
            "memory": "用户被建议每天刷题",
            "metadata": {"source": "chat_turn"},
            "updated_at": "2026-08-01T09:00:00+00:00",
            "score": 0.99,
        },
        {
            "id": "old-user",
            "memory": "我偏好使用 ＦａｓｔＡＰＩ！",
            "metadata": {"attributed_to": "user"},
            "updated_at": "2026-08-01T09:00:00+00:00",
            "score": 0.75,
        },
        {
            "id": "best-user",
            "memory": "我偏好使用 fastapi",
            "metadata": {"attributed_to": "user"},
            "updated_at": "2026-08-02T09:00:00+00:00",
            "score": 0.95,
        },
        {
            "id": "distinct-user",
            "memory": "我做过 Django 项目",
            "metadata": {"attributed_to": "user"},
            "updated_at": "2026-08-03T09:00:00+00:00",
            "score": 0.80,
        },
    ]

    assert [record["id"] for record in canonicalize_memory_records(records)] == [
        "best-user",
        "distinct-user",
    ]
