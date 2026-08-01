"""真实 Redis 模型池集成测试。

默认不连接外部基础设施；设置 TEST_REDIS_URL 后可单独运行：

    uv run pytest -q -m "integration and requires_redis" tests/integration/test_redis_model_pool_integration.py
"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest


def _pool_fixture(llms):
    """Build isolated synthetic pool names, configs, identities, and Redis keys for one test."""

    token = uuid.uuid4().hex
    pool_name = f"integration-pool-{token}"
    configs = [
        {"base_url": f"https://example.test/{token}/a", "model": "model-a", "api_key": f"key-a-{token}", "weight": 1},
        {"base_url": f"https://example.test/{token}/b", "model": "model-b", "api_key": f"key-b-{token}", "weight": 1},
    ]
    identities = [llms._identity(item) for item in configs]
    scheduler = llms.ModelPoolScheduler(redis_client=None)
    cursor_key = f"agent_interview:model_pool:cursor:{scheduler._pool_token(pool_name, configs)}"
    member_keys = [
        scheduler._member_key(kind, identity)
        for identity in identities
        for kind in ("inflight", "cooldown", "failures")
    ]
    return pool_name, configs, identities, cursor_key, member_keys


@pytest.mark.integration
@pytest.mark.requires_redis
def test_model_pool_reserve_order_uses_real_redis_watch_multi():
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 模型池测试")

    redis_module = pytest.importorskip("redis")
    from ai.llm import llms

    client = redis_module.Redis.from_url(redis_url, decode_responses=True)
    pool_name, configs, identities, cursor_key, member_keys = _pool_fixture(llms)
    scheduler_a = llms.ModelPoolScheduler(redis_client=client)
    scheduler_b = llms.ModelPoolScheduler(redis_client=client)

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


@pytest.mark.integration
@pytest.mark.requires_redis
def test_model_pool_concurrent_reservations_use_distinct_members() -> None:
    """Concurrent schedulers resolve WATCH conflicts and atomically reserve separate idle members."""

    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 并发模型池测试")

    redis_module = pytest.importorskip("redis")
    from ai.llm import llms

    cleanup_client = redis_module.Redis.from_url(redis_url, decode_responses=True)
    client_a = redis_module.Redis.from_url(redis_url, decode_responses=True)
    client_b = redis_module.Redis.from_url(redis_url, decode_responses=True)
    pool_name, configs, identities, cursor_key, member_keys = _pool_fixture(llms)
    schedulers = [
        llms.ModelPoolScheduler(redis_client=client_a),
        llms.ModelPoolScheduler(redis_client=client_b),
    ]
    try:
        cleanup_client.delete(cursor_key, *member_keys)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda scheduler: scheduler.reserve_order(pool_name, configs),
                    schedulers,
                )
            )

        assert {identity for _order, identity in results} == set(identities)
        assert {order[0]["model"] for order, _identity in results} == {"model-a", "model-b"}
    finally:
        cleanup_client.delete(cursor_key, *member_keys)
        client_a.close()
        client_b.close()
        cleanup_client.close()


@pytest.mark.integration
@pytest.mark.requires_redis
def test_model_pool_state_survives_scheduler_and_client_restart() -> None:
    """A fresh scheduler/client observes the prior reservation instead of resetting global state."""

    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Redis 模型池重启测试")

    redis_module = pytest.importorskip("redis")
    from ai.llm import llms

    pool_name, configs, identities, cursor_key, member_keys = _pool_fixture(llms)
    first_client = redis_module.Redis.from_url(redis_url, decode_responses=True)
    try:
        first_client.delete(cursor_key, *member_keys)
        first_scheduler = llms.ModelPoolScheduler(redis_client=first_client)
        _first_order, first_identity = first_scheduler.reserve_order(pool_name, configs)
        assert first_identity == identities[0]
    finally:
        first_client.close()

    second_client = redis_module.Redis.from_url(redis_url, decode_responses=True)
    try:
        restarted_scheduler = llms.ModelPoolScheduler(redis_client=second_client)
        second_order, second_identity = restarted_scheduler.reserve_order(pool_name, configs)

        assert restarted_scheduler.get_inflight(identities[0]) == 1
        assert second_identity == identities[1]
        assert second_order[0]["model"] == "model-b"
    finally:
        second_client.delete(cursor_key, *member_keys)
        second_client.close()
