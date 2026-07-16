"""真实 Redis WATCH/MULTI 集成测试。

默认不连接外部基础设施；设置 TEST_REDIS_URL 后可单独运行：

    uv run pytest -q -m "integration and requires_redis" tests/integration/test_redis_watch_integration.py
"""

import os
import uuid

import pytest


@pytest.mark.integration
@pytest.mark.requires_redis
@pytest.mark.asyncio
async def test_redis_watch_multi_detects_conflicting_write():
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis WATCH/MULTI 测试")

    redis_module = pytest.importorskip("redis.asyncio")
    client = redis_module.from_url(redis_url, decode_responses=True)
    key = f"agent-interview:test:watch:{uuid.uuid4()}"
    try:
        await client.set(key, "0")
        async with client.pipeline() as pipe:
            await pipe.watch(key)
            assert await pipe.get(key) == "0"
            await client.set(key, "1")
            pipe.multi()
            pipe.set(key, "2")
            with pytest.raises(redis_module.WatchError):
                await pipe.execute()
        assert await client.get(key) == "1"
    finally:
        await client.delete(key)
        await client.aclose()
