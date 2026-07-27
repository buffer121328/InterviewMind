"""mem0 搜索参数适配回归测试。"""

import pytest

from ai.memory.service import AgentMemoryService


class _FakeMemory:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": [{"memory": "FastAPI"}]}


@pytest.mark.asyncio
async def test_search_memories_uses_mem0_v2_filters_and_top_k():
    memory = _FakeMemory()
    service = AgentMemoryService({})
    service._memory = memory
    service._enabled = True

    result = await service.search_memories(
        user_id="user-1",
        query="后端经验",
        limit=7,
    )

    assert result == [{"memory": "FastAPI"}]
    assert memory.calls == [{
        "query": "后端经验",
        "top_k": 7,
        "filters": {"user_id": "user-1"},
    }]
