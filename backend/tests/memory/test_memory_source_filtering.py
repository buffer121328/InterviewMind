"""Regression coverage for public long-term-memory source classification."""

from __future__ import annotations

import asyncio

import pytest

from ai.workflows.interview.chat.memory import write_memory_background
from ai.workflows.memory.use_cases import MemoryUseCases
from app.domain.memory import MemorySource, MemoryWriteSource
from app.schemas.memory import MemoryCreateRequest


@pytest.mark.asyncio
async def test_list_projects_legacy_source_as_unknown_and_filters_canonical_records(monkeypatch):
    """Source filters are applied after owner-scoped canonical projection."""

    class FakeMemoryService:
        is_enabled = True

        async def get_all(self, *, user_id: str, page_size: int):
            assert (user_id, page_size) == ("user-1", 20)
            return [
                {
                    "id": "resume-1",
                    "memory": "在支付平台负责后端开发",
                    "metadata": {"memory_source": "resume", "source": "manual"},
                },
                {
                    "id": "preference-1",
                    "memory": "偏好使用中文进行模拟面试",
                    "metadata": {"memory_source": "user_preference", "source": "chat_turn"},
                },
                {
                    "id": "legacy-1",
                    "memory": "旧记忆",
                    "metadata": {"source": "manual"},
                },
            ]

    async def fake_get_owner_memory_service(_user_id: str, _api_config):
        return FakeMemoryService()

    monkeypatch.setattr(
        "ai.workflows.memory.use_cases.get_owner_memory_service",
        fake_get_owner_memory_service,
    )

    use_cases = MemoryUseCases()
    unfiltered = await use_cases.list_memories(user_id="user-1", page_size=20)
    filtered = await use_cases.list_memories(
        user_id="user-1",
        page_size=20,
        sources=[MemorySource.USER_PREFERENCE],
    )

    assert [(item.id, item.source) for item in unfiltered.memories] == [
        ("resume-1", MemorySource.RESUME),
        ("preference-1", MemorySource.USER_PREFERENCE),
        ("legacy-1", MemorySource.UNKNOWN),
    ]
    assert [(item.id, item.source) for item in filtered.memories] == [
        ("preference-1", MemorySource.USER_PREFERENCE),
    ]
    assert filtered.total == 1


@pytest.mark.asyncio
async def test_search_filters_by_multiple_public_sources_without_changing_mem0_query(monkeypatch):
    """Semantic search remains owner-scoped; sources are projected safely afterwards."""

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
                    "id": "resume-1",
                    "memory": "简历信息：熟悉 FastAPI",
                    "metadata": {"memory_source": "resume"},
                    "score": 0.91,
                },
                {
                    "id": "weakness-1",
                    "memory": "面试短板：系统设计容量估算不足",
                    "metadata": {"memory_source": "interview_weakness"},
                    "score": 0.89,
                },
                {
                    "id": "preference-1",
                    "memory": "偏好 FastAPI",
                    "metadata": {"memory_source": "user_preference"},
                    "score": 0.87,
                },
            ]

    async def fake_get_owner_memory_service(_user_id: str, _api_config):
        return FakeMemoryService()

    monkeypatch.setattr(
        "ai.workflows.memory.use_cases.get_owner_memory_service",
        fake_get_owner_memory_service,
    )

    response = await MemoryUseCases().search_memories(
        user_id="user-1",
        query="FastAPI",
        limit=5,
        memory_type=None,
        sources=[MemorySource.RESUME, MemorySource.INTERVIEW_WEAKNESS],
    )

    assert [item.id for item in response.memories] == ["resume-1", "weakness-1"]
    assert [item.source for item in response.memories] == [
        MemorySource.RESUME,
        MemorySource.INTERVIEW_WEAKNESS,
    ]


@pytest.mark.asyncio
async def test_manual_memory_persists_selected_source_without_changing_legacy_callers(monkeypatch):
    """The optional create field is passed through only when a caller provides it."""

    captured: dict[str, object] = {}

    class FakeMemoryService:
        is_enabled = True

        async def add_memory(self, **kwargs):
            captured.update(kwargs)
            return {"results": [{"id": "resume-1"}]}

    async def fake_get_owner_memory_service(_user_id: str, _api_config):
        return FakeMemoryService()

    monkeypatch.setattr(
        "ai.workflows.memory.use_cases.get_owner_memory_service",
        fake_get_owner_memory_service,
    )

    response = await MemoryUseCases().add_memory(
        user_id="user-1",
        request=MemoryCreateRequest(
            content="在支付平台负责 FastAPI 后端开发",
            memory_source=MemoryWriteSource.RESUME,
        ),
    )

    assert response.success is True
    assert captured["memory_source"] == "resume"


@pytest.mark.asyncio
async def test_chat_background_write_only_submits_explicit_user_preference(monkeypatch):
    """One-off candidate facts do not enter the narrowed long-term-memory scope."""

    calls: list[dict[str, object]] = []
    tasks: list[asyncio.Task[object]] = []

    class FakeMemoryService:
        is_enabled = True

        async def add_interaction(self, **kwargs):
            calls.append(kwargs)
            return {"results": []}

    async def fake_get_service(_api_config=None):
        return FakeMemoryService()

    def fake_create_background_task(coro, *, name: str):
        task = asyncio.create_task(coro, name=name)
        tasks.append(task)
        return task

    monkeypatch.setattr("ai.memory.get_agent_memory_service", fake_get_service)
    monkeypatch.setattr(
        "ai.runtime.execution.background.create_background_task",
        fake_create_background_task,
    )

    await write_memory_background(
        "session-1",
        "我偏好使用中文进行系统设计模拟面试",
        "好的，后续会优先用中文进行系统设计追问。",
        {"round_index": 1, "round_type": "tech_initial"},
        "user-1",
    )
    await asyncio.gather(*tasks)

    assert calls[0]["metadata"] == {
        "session_id": "session-1",
        "round_index": 1,
        "round_type": "tech_initial",
        "memory_type_hint": "preference",
        "memory_source": "user_preference",
    }

    calls.clear()
    tasks.clear()
    await write_memory_background(
        "session-1",
        "我的项目是一个支付平台，我负责 FastAPI 后端开发",
        "请介绍一下接口设计的取舍。",
        {"round_index": 1, "round_type": "tech_initial"},
        "user-1",
    )

    assert calls == []
    assert tasks == []
