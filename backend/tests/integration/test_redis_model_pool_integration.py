"""真实 Redis 模型池集成测试。

默认不连接外部基础设施；设置 TEST_REDIS_URL 后可单独运行：

    uv run pytest -q -m "integration and requires_redis" tests/integration/test_redis_model_pool_integration.py
"""

import os
import uuid

import pytest


@pytest.mark.integration
@pytest.mark.requires_redis
def test_model_pool_reserve_order_uses_real_redis_watch_multi():
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 模型池测试")

    redis_module = pytest.importorskip("redis")
    from app.services import llms

    client = redis_module.Redis.from_url(redis_url, decode_responses=True)
    token = uuid.uuid4().hex
    pool_name = f"integration-pool-{token}"
    configs = [
        {"base_url": f"https://example.test/{token}/a", "model": "model-a", "api_key": f"key-a-{token}", "weight": 1},
        {"base_url": f"https://example.test/{token}/b", "model": "model-b", "api_key": f"key-b-{token}", "weight": 1},
    ]
    identities = [llms._identity(item) for item in configs]
    scheduler_a = llms.ModelPoolScheduler(redis_client=client)
    scheduler_b = llms.ModelPoolScheduler(redis_client=client)
    cursor_key = f"agent_interview:model_pool:cursor:{scheduler_a._pool_token(pool_name, configs)}"
    member_keys = [
        scheduler_a._member_key(kind, identity)
        for identity in identities
        for kind in ("inflight", "cooldown", "failures")
    ]

    try:
        client.delete(cursor_key, *member_keys)

        first_order, first_identity = scheduler_a.reserve_order(pool_name, configs)
        second_order, second_identity = scheduler_b.reserve_order(pool_name, configs)

        assert first_order[0]["model"] == "model-a"
        assert second_order[0]["model"] == "model-b"
        assert first_identity == identities[0]
        assert second_identity == identities[1]
        assert scheduler_a.get_inflight(first_identity) == 1
        assert scheduler_b.get_inflight(second_identity) == 1
    finally:
        client.delete(cursor_key, *member_keys)
        client.close()
