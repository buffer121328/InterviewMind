"""真实 Redis Broker / Dramatiq 集成测试。

默认不连接外部基础设施；设置 TEST_REDIS_URL 后可单独运行：

    uv run pytest -q -m "integration and requires_dramatiq" tests/integration/test_dramatiq_redis_broker_integration.py
"""

import os
import uuid

import pytest


@pytest.mark.integration
@pytest.mark.requires_redis
@pytest.mark.requires_dramatiq
def test_dramatiq_redis_broker_delivers_message_to_worker():
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("需要 TEST_REDIS_URL 才运行真实 Dramatiq Redis Broker 测试")

    dramatiq = pytest.importorskip("dramatiq")
    redis_module = pytest.importorskip("redis")
    broker_module = pytest.importorskip("dramatiq.brokers.redis")

    namespace = f"agent-interview-test-{uuid.uuid4()}"
    queue_name = f"queue-{uuid.uuid4().hex}"
    result_key = f"{namespace}:result"
    broker = broker_module.RedisBroker(url=redis_url, namespace=namespace)
    client = redis_module.Redis.from_url(redis_url, decode_responses=True)
    worker = None

    @dramatiq.actor(broker=broker, queue_name=queue_name, max_retries=0)
    def record_delivery(value: str) -> None:
        local_client = redis_module.Redis.from_url(redis_url, decode_responses=True)
        try:
            local_client.rpush(result_key, value)
        finally:
            local_client.close()

    try:
        worker = dramatiq.Worker(broker, queues={queue_name}, worker_threads=1, worker_timeout=100)
        worker.start()
        record_delivery.send("delivered")
        broker.join(queue_name, timeout=5000)
        assert client.lrange(result_key, 0, -1) == ["delivered"]
    finally:
        if worker is not None:
            worker.stop(timeout=5000)
        broker.flush(queue_name)
        client.delete(result_key)
        client.close()
        broker.close()
