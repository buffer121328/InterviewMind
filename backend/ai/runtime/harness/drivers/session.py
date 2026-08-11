"""等待用户输入的 AgentRun 统一生命周期 driver。"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.domain.agent_runs import TERMINAL_STATUSES
from app.security.security import safe_error_message

from ..contracts import SessionExecution


class AgentRunServiceProtocol(Protocol):
    """SessionDriver 所需的最小 AgentRun 生命周期能力。"""

    async def create_inline_or_get(
        self,
        *,
        user_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
        task_type: str,
        initial_stage: str,
        session_id: str | None,
    ) -> tuple[Any, bool]: ...

    async def mark_stage(self, run_id: str, stage: str) -> None: ...

    async def succeed(self, run_id: str, result: dict[str, Any]) -> None: ...

    async def fail(self, run_id: str, message: str) -> None: ...

    async def is_cancel_requested(self, run_id: str) -> bool: ...

    async def mark_cancelled(self, run_id: str, message: str = "任务已取消") -> None: ...


class LeaseProtocol(Protocol):
    """运行门租约的最小释放协议。"""

    async def release(self) -> None: ...


GateAcquire = Callable[[], Awaitable[LeaseProtocol | None]]


class SessionDriverConflict(Exception):
    """session continuation 无法唯一执行或已经结束。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


_SESSION_PRIVATE_VALUE = re.compile(
    r"(?i)\b(authorization|api[_ -]?key|token|answer(?:s)?|resume(?:_content)?|job_description)\s*[:=]\s*[^\n]*"
)


def _safe_session_error(value: BaseException | str) -> str:
    """生成不会携带补充答案、材料或凭据的错误摘要。"""

    message = safe_error_message(
        value if isinstance(value, BaseException) else RuntimeError(value)
    )
    return _SESSION_PRIVATE_VALUE.sub(r"\1=***REDACTED***", message)


class SessionDriver:
    """为一次 session continuation 唯一持有 AgentRun lifecycle。"""

    def __init__(
        self,
        *,
        service: AgentRunServiceProtocol,
        gate_acquire: GateAcquire | None = None,
    ) -> None:
        self._service = service
        self._gate_acquire = gate_acquire

    async def start(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        session_id: str,
        idempotency_key: str,
        initial_stage: str,
        execution: SessionExecution,
        requires_global_gate: bool = False,
    ) -> dict[str, Any]:
        """创建唯一 continuation run，并由 driver 收敛 run terminal。"""

        run, created = await self._service.create_inline_or_get(
            user_id=user_id,
            payload=payload,
            idempotency_key=idempotency_key,
            task_type=task_type,
            initial_stage=initial_stage,
            session_id=session_id,
        )
        if not created:
            if getattr(run, "status", None) in TERMINAL_STATUSES:
                raise SessionDriverConflict("该简历生成请求已完成，请刷新会话后再继续")
            raise SessionDriverConflict("同一简历生成请求正在执行，请等待当前生成完成")

        lease: LeaseProtocol | None = None
        try:
            await execution.bind_run(run.id)
            if requires_global_gate:
                if self._gate_acquire is None:
                    raise RuntimeError("global run gate is not configured")
                lease = await self._gate_acquire()
                if lease is None:
                    message = "当前仍有生成任务在执行，请等待当前任务完成"
                    await self._service.fail(run.id, message)
                    await execution.fail_session(message)
                    raise SessionDriverConflict(message)

            if await self._service.is_cancel_requested(run.id):
                await self._cancel(run.id, execution)
                raise SessionDriverConflict("任务已取消")

            async def mark_stage(stage: str) -> None:
                if await self._service.is_cancel_requested(run.id):
                    await self._cancel(run.id, execution)
                    raise SessionDriverConflict("任务已取消")
                await self._service.mark_stage(run.id, stage)

            result = await execution.run(run.id, mark_stage)
            if await self._service.is_cancel_requested(run.id):
                await self._cancel(run.id, execution)
                raise SessionDriverConflict("任务已取消")
            summary = execution.result(result)
            await self._service.succeed(run.id, summary)
            return result
        except asyncio.CancelledError:
            await self._cancel(run.id, execution)
            raise
        except SessionDriverConflict:
            raise
        except Exception as exc:
            message = _safe_session_error(exc)
            await self._service.fail(run.id, message)
            await execution.fail_session(message)
            raise
        finally:
            if lease is not None:
                await lease.release()

    async def _cancel(self, run_id: str, execution: SessionExecution) -> None:
        """在 session callback 前收敛 run 的取消终态。"""

        await self._service.mark_cancelled(run_id)
        if execution.cancel_session is not None:
            await execution.cancel_session("任务已取消")
