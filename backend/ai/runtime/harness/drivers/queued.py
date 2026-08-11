"""Dramatiq Worker 使用的 AgentRun lifecycle driver。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.security.security import safe_error_message

from ..catalog import AgentCatalog
from ..contracts import DeferredExecutionResult, EventSink, ExecutionContext

logger = logging.getLogger(__name__)


class AgentRunServiceProtocol(Protocol):
    """QueuedDriver 所需的最小 AgentRunService 能力。"""

    async def get_task_type_for_worker(self, run_id: str) -> str | None: ...
    async def claim(self, run_id: str) -> tuple[Any, dict[str, Any]] | None: ...
    async def mark_stage(self, run_id: str, stage: str) -> None: ...
    async def touch(self, run_id: str) -> None: ...
    async def is_cancel_requested(self, run_id: str) -> bool: ...
    async def succeed(self, run_id: str, result: dict[str, Any]) -> None: ...
    async def succeed_with_result_writer(self, run_id: str, writer: Any) -> None: ...
    async def mark_cancelled(self, run_id: str) -> None: ...
    async def requeue(self, run_id: str) -> None: ...
    async def fail(self, run_id: str, message: str) -> None: ...


class LeaseProtocol(Protocol):
    """全局运行门租约。"""

    async def release(self) -> None: ...


GateAcquire = Callable[[], Awaitable[LeaseProtocol | None]]


class QueuedDriver:
    """唯一拥有 queued AgentRun claim、取消与终态的生命周期 driver。"""

    def __init__(
        self,
        *,
        catalog: AgentCatalog,
        service: AgentRunServiceProtocol,
        gate_acquire: GateAcquire | None = None,
        heartbeat_seconds: float = 30,
        cancel_poll_seconds: float = 2,
        event_sink: EventSink | None = None,
    ) -> None:
        self._catalog = catalog
        self._service = service
        self._gate_acquire = gate_acquire
        self._heartbeat_seconds = heartbeat_seconds
        self._cancel_poll_seconds = cancel_poll_seconds
        self._event_sink = event_sink

    async def run(self, run_id: str) -> None:
        """领取并执行一个 queued AgentRun，保持既有终态与恢复语义。"""

        task_type = await self._service.get_task_type_for_worker(run_id)
        if task_type is None:
            return
        entry = self._catalog.resolve(task_type, execution_mode="queued")
        lease: LeaseProtocol | None = None
        if entry.definition.run_gate_policy == "global":
            if self._gate_acquire is None:
                raise RuntimeError("global run gate is not configured")
            lease = await self._gate_acquire()
            if lease is None:
                raise RuntimeError("single-user LLM run is active")

        claimed = False
        try:
            claimed_run = await self._service.claim(run_id)
            if not claimed_run:
                return
            claimed = True
            run, stored_payload = claimed_run
            payload = {**stored_payload, "_agent_run_id": run.id}
            context = ExecutionContext(
                run_id=run.id,
                task_type=run.task_type,
                agent_name=entry.definition.name,
                agent_version=entry.definition.version,
                user_id=run.user_id,
                session_id=getattr(run, "session_id", None),
                owner_scope=f"user:{run.user_id}",
                execution_mode="queued",
                environment="production",
                external_tools_enabled=entry.definition.side_effect_policy == "external_effect",
                side_effect_policy=entry.definition.side_effect_policy,
                progress=lambda stage: self._service.mark_stage(run_id, stage),
                event_sink=self._event_sink,
            )

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(self._heartbeat_seconds)
                    try:
                        await self._service.touch(run_id)
                    except Exception as exc:  # noqa: BLE001 - heartbeat is best effort
                        logger.warning(
                            "Agent 任务心跳刷新失败: run_id=%s error=%s",
                            run_id,
                            type(exc).__name__,
                        )

            execution_task = asyncio.create_task(
                entry.adapter.run(payload, context),
                name=f"agent-run-execution:{run_id}",
            )

            async def watch_cancellation() -> None:
                while not execution_task.done():
                    await asyncio.sleep(self._cancel_poll_seconds)
                    if await self._service.is_cancel_requested(run_id):
                        execution_task.cancel()
                        return

            heartbeat_task = asyncio.create_task(
                heartbeat(), name=f"agent-run-heartbeat:{run_id}"
            )
            cancel_task = asyncio.create_task(
                watch_cancellation(), name=f"agent-run-cancel-watch:{run_id}"
            )
            try:
                result = await execution_task
                if isinstance(result, DeferredExecutionResult):
                    await self._service.succeed_with_result_writer(run_id, result.persist)
                elif isinstance(result, dict):
                    await self._service.succeed(run_id, result)
                else:
                    raise TypeError("production queued adapter must return an object result")
            except asyncio.CancelledError:
                if await self._service.is_cancel_requested(run_id):
                    await self._service.mark_cancelled(run_id)
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
                await self._service.requeue(run_id)
            raise
        except Exception as exc:  # noqa: BLE001 - failure is persisted as safe AgentRun state
            message = safe_error_message(exc)
            logger.error("Agent 任务失败: run_id=%s error=%s", run_id, message)
            await self._service.fail(run_id, message)
        finally:
            if lease is not None:
                await lease.release()
