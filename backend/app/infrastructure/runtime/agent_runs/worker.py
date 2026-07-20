"""Dramatiq Worker：领取、执行、心跳、协作取消并完成 AgentRun。"""

import asyncio
import contextlib
import logging
import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

from app.infrastructure.runtime.agent_runs.executors import DeferredExecutionResult, execute_registered_task
from app.infrastructure.runtime.agent_runs.service import AgentRunService
from app.infrastructure.runtime.runtime_gate import get_run_gate
from app.infrastructure.security.security import safe_error_message

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
    claimed = False
    try:
        claimed_run = await service.claim(run_id)
        if not claimed_run:
            return
        claimed = True
        run, payload = claimed_run
        payload = {**payload, "_agent_run_id": run.id}
        heartbeat_seconds = max(5, int(os.getenv("AGENT_RUN_HEARTBEAT_SECONDS", "30")))
        cancel_poll_seconds = max(1, int(os.getenv("AGENT_RUN_CANCEL_POLL_SECONDS", "2")))

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(heartbeat_seconds)
                try:
                    await service.touch(run_id)
                except Exception as exc:
                    logger.warning("Agent 任务心跳刷新失败: run_id=%s error=%s", run_id, type(exc).__name__)

        execution_task = asyncio.create_task(
            execute_registered_task(
                run.task_type,
                payload,
                run.user_id,
                progress=lambda stage: service.mark_stage(run_id, stage),
            ),
            name=f"agent-run-execution:{run_id}",
        )

        async def watch_cancellation() -> None:
            while not execution_task.done():
                await asyncio.sleep(cancel_poll_seconds)
                if await service.is_cancel_requested(run_id):
                    execution_task.cancel()
                    return

        heartbeat_task = asyncio.create_task(heartbeat(), name=f"agent-run-heartbeat:{run_id}")
        cancel_task = asyncio.create_task(watch_cancellation(), name=f"agent-run-cancel-watch:{run_id}")
        try:
            result = await execution_task
            if isinstance(result, DeferredExecutionResult):
                await service.succeed_with_result_writer(run_id, result.persist)
            else:
                await service.succeed(run_id, result)
        except asyncio.CancelledError:
            if await service.is_cancel_requested(run_id):
                await service.mark_cancelled(run_id)
                return
            raise
        finally:
            for task in (heartbeat_task, cancel_task):
                task.cancel()
            for task in (heartbeat_task, cancel_task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    except asyncio.CancelledError:
        if claimed:
            await service.requeue(run_id)
        raise
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("Agent 任务失败: run_id=%s error=%s", run_id, message)
        await service.fail(run_id, message)
    finally:
        await lease.release()
