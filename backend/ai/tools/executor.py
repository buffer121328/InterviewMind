"""统一的工具执行、安全治理和运行时观测边界。"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Collection
from urllib.parse import urlparse

from ai.runtime.context import AgentContext
from app.schemas.tools import ToolEffect
from app.security.security import redact_secrets, safe_error_message
from observability import record_approval_event, record_tool_event
from observability.runtime_events import (
    ApprovalStatus,
    ApprovalObservationEvent,
    ToolObservationEvent,
    ToolStatus,
    new_runtime_event_id,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    """定义一次 Agent 运行内工具调用的超时、次数、重试和脱敏策略。"""

    timeout_seconds: float = 30.0  # 单次工具调用超时
    max_calls: int = 10  # 单次运行内工具调用上限
    max_retries: int = 1  # 可重试次数
    retry_effects: frozenset[ToolEffect] = frozenset({"none", "read"})  # 仅这些副作用可重试
    redact_results: bool = True  # 是否脱敏工具结果


class ToolApprovalRequired(PermissionError):
    """工具需要人工确认后才能执行。"""

    run_status = "awaiting_approval"

    def __init__(
        self,
        tool_name: str,
        message: str = "tool requires explicit confirmation",
    ) -> None:
        """保存待审批工具名，不执行工具或任何外部副作用。

        Args:
            tool_name: 等待人工确认的工具名称。
            message: 对上层工作流返回的稳定错误语义。
        """

        super().__init__(message)       #  调用父类 PermissionError 的构造，把 message 传进去
        self.tool_name = tool_name


class ToolExecutionGuard:
    """一次运行内共享的工具权限、审批、重试、审计和观测边界。"""

    def __init__(self, policy: ToolExecutionPolicy | None = None) -> None:
        """初始化执行策略，不创建连接或执行业务写入。

        Args:
            policy: 当前运行使用的工具执行策略；为空时采用安全默认值。
        """

        self.policy = policy or ToolExecutionPolicy()
        self.calls = 0

    async def execute(
        self,
        call: Callable[..., Awaitable[Any]],
        /,
        *args: Any,
        context: AgentContext,
        effect: ToolEffect = "read",
        required_permissions: Collection[str] = (),
        requires_confirmation: bool | None = None,
        confirmed: bool = False,
        tool_name: str | None = None,
        audit_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
        call_id: str | None = None,
        parent_call_id: str | None = None,
        workflow_name: str | None = None,
        stage: str | None = None,
        simulated: bool = False,
        **kwargs: Any,
    ) -> Any:
        """在执行工具前应用权限、审批、出站校验和调用预算。

        同一次逻辑调用使用一个 `call_id`，所有 started/completed/failed/blocked
        事件均由统一 ToolObservation 契约生成，再投影到活动观测上下文和可选
        AgentRun audit callback。工具参数和结果正文不会进入 Langfuse 投影。

        Args:
            call: 实际异步工具函数。
            context: 不向模型暴露的可信用户、运行和权限上下文。
            effect: 工具对业务世界产生的副作用等级。
            required_permissions: 工具执行所需权限。
            requires_confirmation: 是否要求人工确认；为空时 external 默认要求。
            confirmed: 当前调用是否已经取得明确确认。
            tool_name: 稳定工具名称；为空时使用函数名。
            audit_callback: 可选本地审计 Sink，接收脱敏 ToolObservation payload。
            call_id: 调用方提供的稳定逻辑调用 ID；为空时自动生成。
            parent_call_id: 上层 Tool 或工作流调用 ID。
            workflow_name: 当前工作流名称，仅允许短标识。
            stage: 当前执行阶段，仅允许短标识。
            simulated: 是否为评测或沙箱中的模拟副作用。
            *args: 传给工具的位置参数，仅用于实际执行和本地脱敏摘要。
            **kwargs: 传给工具的关键字参数，仅用于实际执行和本地脱敏摘要。

        Returns:
            经策略决定是否脱敏后的工具结果。

        Raises:
            PermissionError: 权限不足、出站目标非法或需要人工确认。
            RuntimeError: 超出调用预算。
            Exception: 工具最终执行失败时保留原异常语义。
        """

        resolved_tool_name = str(tool_name or getattr(call, "__name__", "tool"))
        resolved_call_id = call_id or new_runtime_event_id("tool")
        required = tuple(sorted(set(required_permissions)))
        granted = tuple(sorted(set(required).intersection(context.permissions)))
        # external 副作用默认需要人工确认；显式传入则覆盖默认。
        needs_confirmation = (
            effect == "external" if requires_confirmation is None else requires_confirmation
        )
        approval_status: ApprovalStatus = (
            "approved"
            if needs_confirmation and confirmed
            else "pending"
            if needs_confirmation
            else "not_required"
        )
        input_summary = _summarize_for_audit({"args": args, "kwargs": kwargs}, limit=200)

        def build_event(
            *,
            event_type: str,
            status: ToolStatus,
            attempt: int = 1,
            duration_ms: int | None = None,
            output_summary: str | None = None,
            error_type: str | None = None,
            error_category: str | None = None,
            error_message: str | None = None,
        ) -> ToolObservationEvent:
            """构造共享调用 ID 的不可变工具事件，不写入外部系统。

            Args:
                event_type: 事件类型（tool.requested/started/completed/failed/blocked 等）。
                status: 工具状态。
                attempt: 第几次尝试，默认 1。
                duration_ms: 执行耗时（毫秒）。
                output_summary: 脱敏后的输出摘要。
                error_type: 异常类型名。
                error_category: 归一化错误类别。
                error_message: 安全错误消息。
            """

            return ToolObservationEvent(
                event_type=event_type,
                tool_name=resolved_tool_name,
                effect=effect,
                status=status,
                call_id=resolved_call_id,
                agent_run_id=context.run_id,
                parent_call_id=parent_call_id,
                workflow_name=workflow_name,
                stage=stage,
                attempt=attempt,
                duration_ms=duration_ms,
                requires_confirmation=needs_confirmation,
                approval_status=approval_status,
                simulated=simulated,
                error_type=error_type,
                error_category=error_category,
                required_permissions=required,
                granted_permissions=granted,
                input_summary=input_summary,
                output_summary=output_summary,
                error_message=error_message,
            )

        await _publish_tool_event(
            build_event(event_type="tool.requested", status="requested"),
            audit_callback,
        )

        # ① 权限校验：缺少任一所需权限则拒绝执行。
        missing = set(required).difference(context.permissions)
        if missing:
            await _publish_tool_event(
                build_event(
                    event_type="tool.blocked",
                    status="blocked",
                    error_type="PermissionError",
                    error_category="permission_denied",
                    error_message=(
                        f"tool requires permissions: {', '.join(sorted(missing))}"
                    ),
                ),
                audit_callback,
            )
            raise PermissionError(
                f"tool requires permissions: {', '.join(sorted(missing))}"
            )

        # ② 人工审批：需要确认时先发审批事件；未确认则中断，不执行任何副作用。
        if needs_confirmation:
            approval_id = f"approval:{resolved_call_id}"
            await _publish_approval_event(
                ApprovalObservationEvent(
                    event_type="approval.requested",
                    approval_id=approval_id,
                    action=resolved_tool_name,
                    status="pending",
                    call_id=resolved_call_id,
                    agent_run_id=context.run_id,
                    parent_call_id=parent_call_id,
                    workflow_name=workflow_name,
                    stage=stage,
                ),
                audit_callback,
            )
            if not confirmed:
                await _publish_tool_event(
                    build_event(
                        event_type="tool.approval_required",
                        status="blocked",
                        error_type="ToolApprovalRequired",
                        error_category="approval_required",
                        error_message="tool requires explicit confirmation",
                    ),
                    audit_callback,
                )
                raise ToolApprovalRequired(resolved_tool_name)
            await _publish_approval_event(
                ApprovalObservationEvent(
                    event_type="approval.resolved",
                    approval_id=approval_id,
                    action=resolved_tool_name,
                    status="approved",
                    call_id=resolved_call_id,
                    agent_run_id=context.run_id,
                    parent_call_id=parent_call_id,
                    workflow_name=workflow_name,
                    stage=stage,
                ),
                audit_callback,
            )

        # ③ 出站校验：仅 external 副作用需校验参数中的 URL，防 SSRF。
        if effect == "external":
            try:
                _validate_outbound_values((args, kwargs))
            except Exception as exc:
                await _publish_tool_event(
                    build_event(
                        event_type="tool.blocked",
                        status="blocked",
                        error_type=type(exc).__name__,
                        error_category="validation_error",
                        error_message=safe_error_message(exc),
                    ),
                    audit_callback,
                )
                raise

        # ④ 调用预算：超过单次运行的工具调用上限则拒绝。
        if self.calls >= self.policy.max_calls:
            message = f"tool call limit exceeded: {self.policy.max_calls}"
            await _publish_tool_event(
                build_event(
                    event_type="tool.blocked",
                    status="blocked",
                    error_type="RuntimeError",
                    error_category="business_rule_error",
                    error_message=message,
                ),
                audit_callback,
            )
            raise RuntimeError(message)

        self.calls += 1
        # ⑤ 执行：仅 read/none 副作用可重试；每次执行带超时，成功结果按策略脱敏。
        attempts = 1 + (
            self.policy.max_retries if effect in self.policy.retry_effects else 0
        )
        started = time.perf_counter()
        await _publish_tool_event(
            build_event(event_type="tool.started", status="started"),
            audit_callback,
        )

        for attempt_index in range(attempts):
            attempt = attempt_index + 1
            try:
                result = await asyncio.wait_for(
                    call(*args, **kwargs), timeout=self.policy.timeout_seconds
                )
                output = _redact(result) if self.policy.redact_results else result
                await _publish_tool_event(
                    build_event(
                        event_type="tool.completed",
                        status="completed",
                        attempt=attempt,
                        duration_ms=_elapsed_ms(started),
                        output_summary=_summarize_for_audit(output, limit=300),
                    ),
                    audit_callback,
                )
                return output
            except Exception as exc:
                if attempt_index == attempts - 1:
                    await _publish_tool_event(
                        build_event(
                            event_type="tool.failed",
                            status="failed",
                            attempt=attempt,
                            duration_ms=_elapsed_ms(started),
                            error_type=type(exc).__name__,
                            error_category=_tool_error_category(exc),
                            error_message=safe_error_message(exc),
                        ),
                        audit_callback,
                    )
                    raise
        raise RuntimeError("tool execution exhausted without terminal result")


async def _publish_tool_event(
    event: ToolObservationEvent,
    callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
) -> ToolObservationEvent:
    """一次生成工具事实，再 best-effort 投影到观测和本地审计。

    Args:
        event: 要投影的工具观测事件。
        callback: 可选本地审计 Sink，接收脱敏 payload。
    """

    bound_event = record_tool_event(event)
    await _publish_audit_projection(callback, bound_event.to_local_payload())
    return bound_event


async def _publish_approval_event(
    event: ApprovalObservationEvent,
    callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
) -> ApprovalObservationEvent:
    """把审批事实投影到统一 Sink；审计失败不得改变审批/工具业务终态。

    Args:
        event: 要投影的审批观测事件。
        callback: 可选本地审计 Sink，接收脱敏 payload。
    """

    bound_event = record_approval_event(event)
    await _publish_audit_projection(callback, bound_event.to_local_payload())
    return bound_event


async def _publish_audit_projection(
    callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
    event: dict[str, Any],
) -> None:
    """best-effort 调用本地审计 Sink，避免观测故障掩盖工具结果。

    Args:
        callback: 本地审计 Sink，可为 None。
        event: 已脱敏的审计 payload。
    """

    if callback is None:
        return
    try:
        await _emit_audit(callback, event)
    except Exception as exc:  # noqa: BLE001 - 审计 Sink 不能改变业务终态。
        logger.warning("工具审计 Sink 失败，继续工具执行: %s", type(exc).__name__)


async def _emit_audit(
    callback: Callable[[dict[str, Any]], Awaitable[None] | None],
    event: dict[str, Any],
) -> None:
    """投递审计事件；兼容同步和异步 Sink。

    Args:
        callback: 本地审计 Sink。
        event: 已脱敏的审计 payload。
    """

    result = callback(event)
    if inspect.isawaitable(result):
        await result


def _elapsed_ms(started: float) -> int:
    """返回非负整数毫秒耗时。

    Args:
        started: 开始时的时间戳（time.perf_counter()）。
    """

    return max(0, int((time.perf_counter() - started) * 1000))


def _tool_error_category(exc: Exception) -> str:
    """把工具异常归一成可聚合的稳定错误类别。

    Args:
        exc: 捕获的工具异常。
    """

    if isinstance(exc, TimeoutError):
        return "tool_timeout"
    return "tool_error"


def _summarize_for_audit(value: Any, *, limit: int) -> str:
    """生成脱敏且有长度上限的本地审计摘要。

    Args:
        value: 待摘要的值。
        limit: 摘要最大字符数。
    """

    return str(redact_secrets(_redact(value)))[:limit]


_SECRET_KEYS = {"api_key", "apikey", "authorization", "token", "secret", "password"}


def _validate_outbound_values(value: Any) -> None:
    """递归校验 external Tool 参数中的 URL，拒绝凭据和非公网目标。

    Args:
        value: 待校验的参数值（可嵌套 dict/list/tuple/set）。
    """

    if isinstance(value, str):
        if value.lower().startswith(("http://", "https://")):
            _validate_public_url(value)
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_outbound_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _validate_outbound_values(item)


def _validate_public_url(value: str) -> None:
    """拒绝带凭据、localhost、私网或保留地址的 external Tool URL。

    Args:
        value: 待校验的 URL 字符串。
    """

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.username or parsed.password:
        raise PermissionError("outbound URL must not contain credentials")
    if (
        not hostname
        or hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal"))
    ):
        raise PermissionError("outbound URL targets a local host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise PermissionError("outbound URL targets a non-public address")


def _redact(value: Any) -> Any:
    """递归脱敏工具结果中的凭据字段。

    Args:
        value: 待脱敏的工具结果。
    """

    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in _SECRET_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value
