"""Dramatiq Worker 入口，部署时固定一个进程和一个线程。"""

import logging
import os
import asyncio
import contextlib

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

from app.services.agent_runs.executors import execute_registered_task
from app.services.agent_runs.service import AgentRunService
from app.services.runtime_gate import get_run_gate
from app.services.security import safe_error_message

logger = logging.getLogger(__name__)

broker = RedisBroker(url=os.getenv("REDIS_URL", "redis://redis:6379/0"))
broker.add_middleware(AsyncIO())
dramatiq.set_broker(broker)


@dramatiq.actor(queue_name="interactive", max_retries=10, min_backoff=1000)
async def execute_agent_run(run_id: str) -> None:
    service = AgentRunService()
    lease = await get_run_gate().acquire()
    if lease is None:
        raise RuntimeError("single-user LLM run is active")
    try:
        claimed = await service.claim(run_id)
        if not claimed:
            return
        run, payload = claimed
        payload = {**payload, "_agent_run_id": run.id}
        heartbeat_seconds = max(5, int(os.getenv("AGENT_RUN_HEARTBEAT_SECONDS", "30")))

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(heartbeat_seconds)
                try:
                    await service.touch(run_id)
                except Exception as exc:
                    logger.warning("Agent 任务心跳刷新失败: run_id=%s error=%s", run_id, type(exc).__name__)

        heartbeat_task = asyncio.create_task(heartbeat(), name=f"agent-run-heartbeat:{run_id}")
        try:
            result = await execute_registered_task(
                run.task_type,
                payload,
                run.user_id,
                progress=lambda stage: service.mark_stage(run_id, stage),
            )
            await service.succeed(run_id, result)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("Agent 任务失败: run_id=%s error=%s", run_id, message)
        await service.fail(run_id, message)
    finally:
        await lease.release()
