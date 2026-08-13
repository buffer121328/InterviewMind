"""交互式 SSE AgentRun 的统一生命周期 driver。"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from inspect import isawaitable
from typing import Any, Protocol

from ai.runtime.agent_runs.event_stream import build_run_event_envelope
from app.domain.agent_runs import TERMINAL_STATUSES
from app.security.security import safe_error_message

from ..contracts import StreamErrorEncoder, StreamEventEncoder, StreamExecution


class AgentRunServiceProtocol(Protocol):
    """StreamDriver 所需的最小 AgentRun 生命周期能力。"""

    async def create_or_get(
        self,
        *,
        user_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
        task_type: str,
        session_id: str | None,
    ) -> tuple[Any, bool]:
        """按幂等键创建或获取 run，返回 (run, 是否新建)。"""

    async def claim(self, run_id: str) -> tuple[Any, dict[str, Any]] | None:
        """领取任务，返回 (run, payload)；已被领取/不存在返回 None。"""

    async def mark_stage(self, run_id: str, stage: str) -> None:
        """记录当前执行阶段。"""

    async def succeed(self, run_id: str, result: dict[str, Any]) -> None:
        """写入成功终态。"""

    async def fail(self, run_id: str, message: str) -> None:
        """写入失败终态（安全摘要）。"""


class LeaseProtocol(Protocol):
    """运行门租约的最小释放协议。"""

    async def release(self) -> None:
        """释放运行锁或租约。"""


StreamFactory = Callable[[str], Awaitable[StreamExecution]]  # 由 run_id 构造 StreamExecution 的工厂
GateAcquire = Callable[[], Awaitable[LeaseProtocol | None]]  # 获取全局运行门租约的工厂：成功返回租约，被占用返回 None


class StreamDriverConflict(Exception):
    """流式运行无法被唯一领取或运行门拒绝。"""

    def __init__(self, message: str) -> None:
        """保存冲突原因。

        Args:
            message: 对上层工作流返回的稳定错误语义。
        """

        self.message = message
        super().__init__(message)


_STREAM_PRIVATE_VALUE = re.compile(
    r"(?i)\b(audio(?:_base64)?|transcript(?:ion)?)\s*[:=]\s*[^\n]*"
)


def _safe_stream_error(value: BaseException | str) -> str:
    """生成不会包含音频或完整转写的受限流式错误摘要。

    Args:
        value: 原始异常或错误消息。
    """

    message = safe_error_message(
        value if isinstance(value, BaseException) else RuntimeError(value)
    )
    return _STREAM_PRIVATE_VALUE.sub(r"\1=***REDACTED***", message)


def _default_run_event_encoder(envelope: dict[str, Any]) -> str:
    """为适配器准备失败前提供最小兼容 lifecycle SSE。

    Args:
        envelope: run 事件信封（dict）。
    """

    import json

    return f"data: {json.dumps({'type': 'agent_run_event', 'content': envelope}, ensure_ascii=False)}\n\n"


def _default_error_encoder(message: str) -> str:
    """为适配器准备失败前提供最小兼容错误 SSE。

    Args:
        message: 错误消息。
    """

    import json

    return f"data: {json.dumps({'type': 'error', 'content': message}, ensure_ascii=False)}\n\n"


class StreamDriver:
    """为请求内 SSE 流唯一持有 AgentRun lifecycle。"""

    def __init__(
        self,
        *,
        service: AgentRunServiceProtocol,
        gate_acquire: GateAcquire | None = None,
    ) -> None:
        """初始化 StreamDriver 的依赖，不创建连接或执行业务写入。

        Args:
            service: 提供 AgentRun 生命周期能力的服务。
            gate_acquire: 获取全局运行门租约的工厂；不传则禁用全局门禁。
        """

        self._service = service
        self._gate_acquire = gate_acquire

    async def start(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        session_id: str | None,
        idempotency_key: str,
        initial_stage: str,
        stream_factory: StreamFactory,
        requires_global_gate: bool = False,
        fallback_run_event_encoder: StreamEventEncoder | None = None,
        fallback_error_encoder: StreamErrorEncoder | None = None,
    ) -> AsyncGenerator[str, None]:
        """创建、claim 并返回由 driver 管理终态的 SSE 生成器。

        Args:
            task_type: 任务类型名。
            payload: 任务入参。
            user_id: 发起用户。
            session_id: 会话 ID，可选。
            idempotency_key: 幂等键，防止同一会话重复创建 run。
            initial_stage: 初始执行阶段。
            stream_factory: 由 run_id 构造 StreamExecution 的工厂。
            requires_global_gate: 是否要求全局单用户运行门禁。
            fallback_run_event_encoder: 失败前兜底的 run 事件编码器。
            fallback_error_encoder: 失败前兜底的错误编码器。
        """

        # ① 创建或获取 run：按幂等键保证唯一，已存在则不重复。
        run, created = await self._service.create_or_get(
            user_id=user_id,
            task_type=task_type,
            idempotency_key=idempotency_key,
            session_id=session_id,
            payload=payload,
        )
        if not created:
            if getattr(run, "status", None) in TERMINAL_STATUSES:
                raise StreamDriverConflict("该请求已完成，请刷新面试会话后再继续")
            raise StreamDriverConflict("同一面试请求正在执行，请等待当前回复完成")

        # ② 领取任务：claim 失败（状态异常）则拒绝。
        claimed = await self._service.claim(run.id)
        if claimed is None:
            raise StreamDriverConflict("当前面试生成任务状态异常，请稍后重试")

        lease: LeaseProtocol | None = None
        try:
            await self._service.mark_stage(run.id, initial_stage)
            # ③ 全局门禁：要求单用户运行时先拿租约，拿不到则失败并提示等待。
            if requires_global_gate:
                if self._gate_acquire is None:
                    raise RuntimeError("global run gate is not configured")
                lease = await self._gate_acquire()
                if lease is None:
                    message = "当前仍有面试任务在生成，请等待当前回复完成"
                    await self._service.fail(run.id, message)
                    raise StreamDriverConflict(message)
            # ④ 返回 SSE 生成器，由 _run_stream 负责投影业务流并收敛终态。
            return self._run_stream(
                run_id=run.id,
                user_id=user_id,
                initial_stage=initial_stage,
                stream_factory=stream_factory,
                lease=lease,
                fallback_run_event_encoder=fallback_run_event_encoder or _default_run_event_encoder,
                fallback_error_encoder=fallback_error_encoder or _default_error_encoder,
            )
        except asyncio.CancelledError:
            await self._service.fail(run.id, "client_disconnected")
            if lease is not None:
                await self._release_lease(lease)
            raise
        except StreamDriverConflict:
            if lease is not None:
                await self._release_lease(lease)
            raise
        except Exception as exc:
            await self._service.fail(run.id, _safe_stream_error(exc))
            if lease is not None:
                await self._release_lease(lease)
            raise

    async def _run_stream(
        self,
        *,
        run_id: str,
        user_id: str,
        initial_stage: str,
        stream_factory: StreamFactory,
        lease: LeaseProtocol | None,
        fallback_run_event_encoder: StreamEventEncoder,
        fallback_error_encoder: StreamErrorEncoder,
    ) -> AsyncGenerator[str, None]:
        """投影业务 SSE，并以唯一 lifecycle owner 写入终态。

        Args:
            run_id: 要执行的 AgentRun 运行 ID。
            user_id: 发起用户。
            initial_stage: 初始执行阶段。
            stream_factory: 由 run_id 构造 StreamExecution 的工厂。
            lease: 已获取的全局运行门租约，结束时释放。
            fallback_run_event_encoder: 兜底 run 事件编码器。
            fallback_error_encoder: 兜底错误编码器。
        """

        execution: StreamExecution | None = None
        terminal_written = False  # 是否已写入终态，防止重复收敛
        sequence = 0  # 事件序号，保证 SSE 有序

        def lifecycle_event(
            event_type: str,
            *,
            stage: str | None = None,
            payload: dict[str, Any] | None = None,
        ) -> str:
            """构造并编码一个 run 生命周期 SSE 事件。

            Args:
                event_type: 事件类型（run.started/completed/failed/cancelled 等）。
                stage: 事件阶段，可选。
                payload: 事件载荷，可选。
            """

            nonlocal sequence
            sequence += 1
            envelope = build_run_event_envelope(
                run_id=run_id,
                event_type=event_type,
                stage=stage,
                payload=payload,
                sequence=sequence,
                event_id=f"inline:{run_id}:{sequence}",
            )
            encoder = execution.encode_run_event if execution is not None else fallback_run_event_encoder
            return encoder(envelope)

        async def fail_once(message: str) -> None:
            """只写一次失败终态，避免重复收敛。

            Args:
                message: 安全错误消息。
            """

            nonlocal terminal_written
            if terminal_written:
                return
            terminal_written = True
            await self._service.fail(run_id, message)

        async def cancellation_requested() -> bool:
            """best-effort 查询是否被取消。"""

            checker = getattr(self._service, "is_cancel_requested", None)
            if checker is None:
                return False
            try:
                return bool(await checker(run_id))
            except Exception:  # noqa: BLE001 - cancellation polling is best effort
                return False

        async def emit_cancelled() -> str:
            """写取消终态并返回取消 SSE 事件。"""

            await fail_once("任务已取消")
            return lifecycle_event(
                "run.cancelled",
                stage="cancelled",
                payload={"message": "任务已取消"},
            )

        try:
            # ① 构造业务流：先输出前置事件，再广播 started。
            execution = await stream_factory(run_id)
            for event in execution.preamble:
                yield event
            yield lifecycle_event("run.started", stage=initial_stage)
            # ② 逐块投影业务 SSE；期间检查取消和错误检测。
            async for chunk in execution.source:
                if await cancellation_requested():
                    yield await emit_cancelled()
                    await self._close_source(execution.source)
                    return
                yield chunk
                if execution.detect_error is None:
                    continue
                reported_error = execution.detect_error(chunk)
                if reported_error is None:
                    continue
                # 检测到错误：写失败终态 + 广播 run.failed + 关闭流。
                safe_message = _safe_stream_error(reported_error)
                await fail_once(safe_message)
                yield lifecycle_event("run.failed", payload={"message": safe_message})
                await self._close_source(execution.source)
                return

            if await cancellation_requested():
                yield await emit_cancelled()
                return

            # ③ 正常收尾：取结果，写 succeed 终态，广播 completed。
            result = execution.result()
            if isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise TypeError("stream execution result must be an object")
            await self._service.succeed(run_id, result)
            terminal_written = True
            # ④ 终态复核：若底层已是 cancelled，则投影 cancelled 而非 completed。
            get_run = getattr(self._service, "get", None)
            if get_run is not None:
                try:
                    completed_run = await get_run(run_id, user_id)
                except Exception:  # noqa: BLE001 - terminal status read is best effort
                    completed_run = None
                if getattr(completed_run, "status", None) == "cancelled":
                    yield lifecycle_event("run.cancelled", stage="cancelled")
                    return
            yield lifecycle_event("run.completed", stage="succeeded")
        except asyncio.CancelledError:
            await fail_once("client_disconnected")
            raise
        except Exception as exc:  # noqa: BLE001 - persisted terminal must be safe
            # ⑤ 异常兜底：写失败终态，投影 run.failed 和错误 SSE。
            safe_message = _safe_stream_error(exc)
            await fail_once(safe_message)
            yield lifecycle_event("run.failed", payload={"message": safe_message})
            encoder = execution.encode_error if execution is not None else fallback_error_encoder
            yield encoder(safe_message)
        finally:
            # ⑥ 释放全局门租约。
            if lease is not None:
                await self._release_lease(lease)

    @staticmethod
    async def _close_source(source: Any) -> None:
        """尽力关闭提前失败的业务流，避免继续产出终态冲突。

        Args:
            source: 业务 SSE 异步迭代器。
        """

        close = getattr(source, "aclose", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await close()

    @staticmethod
    async def _release_lease(lease: LeaseProtocol) -> None:
        """尽力释放运行门；释放异常不得覆盖已持久化运行终态。

        Args:
            lease: 要释放的运行门租约。
        """

        with contextlib.suppress(Exception):
            await lease.release()
