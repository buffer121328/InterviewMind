"""mem0 搜索参数适配回归测试。"""

import pytest

from ai.memory.service import AgentMemoryService


class _FakeMemory:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": [
            {"id": "assistant", "memory": "用户被建议每天刷题", "metadata": {"source": "chat_turn"}},
            {"id": "old", "memory": "偏好 ＦａｓｔＡＰＩ！", "metadata": {}, "score": 0.7},
            {"id": "best", "memory": "偏好 fastapi", "metadata": {}, "score": 0.9},
        ]}


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

    assert [item["id"] for item in result] == ["best"]
    assert memory.calls == [{
        "query": "后端经验",
        "top_k": 7,
        "filters": {"user_id": "user-1"},
    }]
