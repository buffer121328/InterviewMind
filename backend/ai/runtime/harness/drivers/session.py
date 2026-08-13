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
    ) -> tuple[Any, bool]:
        """按幂等键创建或获取 run，返回 (run, 是否新建)。"""

    async def mark_stage(self, run_id: str, stage: str) -> None:
        """记录当前执行阶段。"""

    async def succeed(self, run_id: str, result: dict[str, Any]) -> None:
        """写入成功终态。"""

    async def fail(self, run_id: str, message: str) -> None:
        """写入失败终态（安全摘要）。"""

    async def is_cancel_requested(self, run_id: str) -> bool:
        """查询该任务是否已被请求取消。"""

    async def mark_cancelled(self, run_id: str, message: str = "任务已取消") -> None:
        """写入取消终态。"""


class LeaseProtocol(Protocol):
    """运行门租约的最小释放协议。"""

    async def release(self) -> None:
        """释放运行锁或租约。"""


GateAcquire = Callable[[], Awaitable[LeaseProtocol | None]]  # 获取全局运行门租约的工厂：成功返回租约，被占用返回 None


class SessionDriverConflict(Exception):
    """session continuation 无法唯一执行或已经结束。"""

    def __init__(self, message: str) -> None:
        """保存冲突原因。

        Args:
            message: 对上层工作流返回的稳定错误语义。
        """

        self.message = message
        super().__init__(message)


# 会话错误脱敏正则：把错误消息中"敏感字段 :/ 值"整段替换为"字段=***REDACTED***"。
# 覆盖两类敏感信息：
#   - 凭据类：authorization、api_key/api-key/api key、token
#   - 业务材料：answer(s)（面试回答）、resume(_content)（简历内容）、job_description（职位描述）
# 说明：(?i) 忽略大小写；\s*[:=]\s* 匹配冒号或等号分隔；[^\n]* 取到行尾作为待脱敏的值。
_SESSION_PRIVATE_VALUE = re.compile(
    r"(?i)\b(authorization|api[_ -]?key|token|answer(?:s)?|resume(?:_content)?|job_description)\s*[:=]\s*[^\n]*"
)


def _safe_session_error(value: BaseException | str) -> str:
    """生成不会携带补充答案、材料或凭据的错误摘要。

    Args:
        value: 原始异常或错误消息。
    """

    message = safe_error_message(
        value if isinstance(value, BaseException) else RuntimeError(value)
    )
    # 保留字段名、把值整段替换为 ***REDACTED***，便于定位是哪类敏感信息被抹掉。
    return _SESSION_PRIVATE_VALUE.sub(r"\1=***REDACTED***", message)


class SessionDriver:
    """为一次 session continuation 唯一持有 AgentRun lifecycle。"""

    def __init__(
        self,
        *,
        service: AgentRunServiceProtocol,
        gate_acquire: GateAcquire | None = None,
    ) -> None:
        """初始化 SessionDriver 的依赖，不创建连接或执行业务写入。

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
        session_id: str,
        idempotency_key: str,
        initial_stage: str,
        execution: SessionExecution,
        requires_global_gate: bool = False,
    ) -> dict[str, Any]:
        """创建唯一 continuation run，执行业务并收敛 run 终态。

        Args:
            task_type: 任务类型名。
            payload: 任务入参。
            user_id: 发起用户。
            session_id: 会话 ID。
            idempotency_key: 幂等键，防止同一会话重复创建 run。
            initial_stage: 初始执行阶段。
            execution: 会话执行契约（业务回调集合）。
            requires_global_gate: 是否要求全局单用户运行门禁。
        """

        # ① 创建或获取 run：按幂等键保证唯一 continuation。
        run, created = await self._service.create_inline_or_get(
            user_id=user_id,
            payload=payload,
            idempotency_key=idempotency_key,
            task_type=task_type,
            initial_stage=initial_stage,
            session_id=session_id,
        )
        if not created:
            # 已存在：终态则提示完成，进行中则提示等待，均不重复执行。
            if getattr(run, "status", None) in TERMINAL_STATUSES:
                raise SessionDriverConflict("该简历生成请求已完成，请刷新会话后再继续")
            raise SessionDriverConflict("同一简历生成请求正在执行，请等待当前生成完成")

        lease: LeaseProtocol | None = None
        try:
            await execution.bind_run(run.id)
            # ② 全局门禁：要求单用户运行时先拿租约，拿不到则失败并提示等待。
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

            # ③ 阶段推进回调：每推进前先查取消，取消则收敛并中断。
            async def mark_stage(stage: str) -> None:
                if await self._service.is_cancel_requested(run.id):
                    await self._cancel(run.id, execution)
                    raise SessionDriverConflict("任务已取消")
                await self._service.mark_stage(run.id, stage)

            # ④ 执行业务：由 execution.run 调用真实业务逻辑。
            result = await execution.run(run.id, mark_stage)
            if await self._service.is_cancel_requested(run.id):
                await self._cancel(run.id, execution)
                raise SessionDriverConflict("任务已取消")
            # ⑤ 收敛成功：业务结果映射为摘要后写入 succeed。
            summary = execution.result(result)
            await self._service.succeed(run.id, summary)
            return result
        except asyncio.CancelledError:
            await self._cancel(run.id, execution)
            raise
        except SessionDriverConflict:
            raise
        except Exception as exc:
            # ⑥ 收敛失败：脱敏摘要写 fail，并同步收敛 session。
            message = _safe_session_error(exc)
            await self._service.fail(run.id, message)
            await execution.fail_session(message)
            raise
        finally:
            # ⑦ 释放全局门租约。
            if lease is not None:
                await lease.release()

    async def _cancel(self, run_id: str, execution: SessionExecution) -> None:
        """在 session callback 前收敛 run 的取消终态。

        Args:
            run_id: 要取消的 AgentRun 运行 ID。
            execution: 会话执行契约，用于通知业务侧取消。
        """

        await self._service.mark_cancelled(run_id)
        if execution.cancel_session is not None:
            await execution.cancel_session("任务已取消")
