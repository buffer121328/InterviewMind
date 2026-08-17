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

# 接口类，每个dirvers就近定义和实现
class AgentRunServiceProtocol(Protocol):
    """QueuedDriver 所需的最小 AgentRunService 能力。"""

    async def get_task_type_for_worker(self, run_id: str) -> str | None:
        """查询 run_id 对应的任务类型；未知返回 None。

        Args:
            run_id: 任务运行 ID。
        """

    async def claim(self, run_id: str) -> tuple[Any, dict[str, Any]] | None:
        """领取任务，返回 (run, payload)；已被领取/不存在返回 None。

        Args:
            run_id: 任务运行 ID。
        """

    async def mark_stage(self, run_id: str, stage: str) -> None:
        """记录当前执行阶段。

        Args:
            run_id: 任务运行 ID。
            stage: 阶段标识。
        """

    async def touch(self, run_id: str) -> None:
        """刷新心跳，防止任务被误判为超时。

        Args:
            run_id: 任务运行 ID。
        """

    async def is_cancel_requested(self, run_id: str) -> bool:
        """查询该任务是否已被请求取消。

        Args:
            run_id: 任务运行 ID。
        """

    async def succeed(self, run_id: str, result: dict[str, Any]) -> None:
        """写入成功终态。

        Args:
            run_id: 任务运行 ID。
            result: 结果对象。
        """

    async def succeed_with_result_writer(self, run_id: str, writer: Any) -> None:
        """用延迟写入器在成功事务内写结果。

        Args:
            run_id: 任务运行 ID。
            writer: 传入的 writer 值。
        """

    async def mark_cancelled(self, run_id: str) -> None:
        """写入取消终态。

        Args:
            run_id: 任务运行 ID。
        """

    async def requeue(self, run_id: str) -> None:
        """把任务重新放回队列等待下次执行。

        Args:
            run_id: 任务运行 ID。
        """

    async def fail(self, run_id: str, message: str) -> None:
        """写入失败终态（安全摘要）。

        Args:
            run_id: 任务运行 ID。
            message: 单条消息。
        """


class LeaseProtocol(Protocol):
    """全局运行门租约。"""

    async def release(self) -> None:
        """释放已持有的全局运行门租约。"""


GateAcquire = Callable[[], Awaitable[LeaseProtocol | None]]  # 获取全局运行门租约的工厂：成功返回租约，被占用返回 None


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
        """初始化 QueuedDriver 的依赖与运行参数，不创建连接或执行业务写入。

        Args:
            catalog: 任务目录，用于把 task_type 解析为 adapter。
            service: 提供 AgentRun 生命周期能力的服务（claim/touch/succeed/fail 等）。
            gate_acquire: 获取全局运行门租约的工厂；不传则禁用全局门禁。
            heartbeat_seconds: 心跳间隔秒数，运行中周期性刷新防止误判超时。
            cancel_poll_seconds: 取消轮询间隔秒数。
            event_sink: 事件投影 sink，可选。
        """

        self._catalog = catalog
        self._service = service
        self._gate_acquire = gate_acquire
        self._heartbeat_seconds = heartbeat_seconds
        self._cancel_poll_seconds = cancel_poll_seconds
        self._event_sink = event_sink

    async def run(self, run_id: str) -> None:
        """领取并执行一个 queued AgentRun，保持既有终态与恢复语义。

        Args:
            run_id: 要执行的 AgentRun 运行 ID。
        """

        # ① 解析任务：先查 task_type，未知任务直接跳过。
        task_type = await self._service.get_task_type_for_worker(run_id)
        if task_type is None:
            return
        entry = self._catalog.resolve(task_type, execution_mode="queued")
        # ② 全局门禁：任务声明 global 策略时需先拿到单用户运行租约。
        lease: LeaseProtocol | None = None
        if entry.definition.run_gate_policy == "global":
            if self._gate_acquire is None:
                raise RuntimeError("global run gate is not configured")
            lease = await self._gate_acquire()
            if lease is None:
                raise RuntimeError("single-user LLM run is active")

        claimed = False
        try:
            # ③ 领取任务：claim 失败（已被他人领取/不存在）则静默返回。
            claimed_run = await self._service.claim(run_id)
            if not claimed_run:
                return
            claimed = True
            run, stored_payload = claimed_run
            payload = {**stored_payload, "_agent_run_id": run.id}
            # ④ 组装执行上下文：进度回调映射到 mark_stage，副作用策略来自定义。
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
                # 周期 touch 刷新运行状态，失败仅告警不中断执行（best-effort）。
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
                # 轮询是否被取消；是则取消执行任务。
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
                # ⑤ 收敛成功终态：Deferred 用结果写入器，普通 dict 直接 succeed。
                result = await execution_task
                if isinstance(result, DeferredExecutionResult):
                    await self._service.succeed_with_result_writer(run_id, result.persist)
                elif isinstance(result, dict):
                    await self._service.succeed(run_id, result)
                else:
                    raise TypeError("production queued adapter must return an object result")
            except asyncio.CancelledError:
                # 执行被取消：若确认是用户取消则标记取消，否则上抛。
                if await self._service.is_cancel_requested(run_id):
                    await self._service.mark_cancelled(run_id)
                    return
                raise
            finally:
                # 无论结果如何，停掉心跳和取消监听协程。
                for task in (heartbeat_task, cancel_task):
                    task.cancel()
                for task in (heartbeat_task, cancel_task):
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
        except asyncio.CancelledError:
            # 外部中断：若已 claim 则重新入队，等待下次执行（可恢复）。
            if claimed:
                await self._service.requeue(run_id)
            raise
        except Exception as exc:  # noqa: BLE001 - failure is persisted as safe AgentRun state
            # ⑥ 收敛失败终态：安全摘要写入 fail。
            message = "任务执行超时，请稍后重试" if isinstance(exc, TimeoutError) else safe_error_message(exc)
            logger.error("Agent 任务失败: run_id=%s error=%s", run_id, message)
            await self._service.fail(run_id, message)
        finally:
            # ⑦ 释放全局门租约。
            if lease is not None:
                await lease.release()
