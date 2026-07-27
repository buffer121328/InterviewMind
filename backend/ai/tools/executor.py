"""统一的工具执行边界。"""

import asyncio
import inspect
import ipaddress
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Collection

from app.security.security import redact_secrets, safe_error_message
from urllib.parse import urlparse

from ai.runtime.context import AgentContext

from .registry import ToolEffect


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    """定义策略规则。"""
    timeout_seconds: float = 30.0
    max_calls: int = 20
    max_retries: int = 0
    retry_effects: frozenset[ToolEffect] = frozenset({"none", "read"})
    redact_results: bool = True




@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
    """表示持久化记录。"""
    tool_name: str
    effect: ToolEffect
    status: str
    duration_ms: int | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class ToolApprovalRequired(PermissionError):
    """工具需要人工确认后才能执行。"""

    run_status = "awaiting_approval"

    def __init__(
        self,
        tool_name: str,
        message: str = "tool requires explicit confirmation",
    ) -> None:
        """初始化 `ToolApprovalRequired` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            tool_name: tool 名称。
            message: 消息内容。
        """
        super().__init__(message)
        self.tool_name = tool_name


class ToolExecutionGuard:
    """一次运行内共享的工具安全边界。"""

    def __init__(self, policy: ToolExecutionPolicy | None = None) -> None:
        """初始化 `ToolExecutionGuard` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            policy: 经过类型边界校验的 `policy`；其格式和可选值由参数类型及调用流程约束。
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
        **kwargs: Any,
    ) -> Any:
        """执行当前工具或任务调用，先通过契约、权限、审批和审计校验，再把结果返回给上层工作流。

        Args:
            call: 经过类型边界校验的 `call`；其格式和可选值由参数类型及调用流程约束。
            context: 运行上下文。
            effect: 经过类型边界校验的 `effect`；其格式和可选值由参数类型及调用流程约束。
            required_permissions: 经过类型边界校验的 `required_permissions`；其格式和可选值由参数类型及调用流程约束。
            requires_confirmation: 经过类型边界校验的 `requires_confirmation`；其格式和可选值由参数类型及调用流程约束。
            confirmed: 经过类型边界校验的 `confirmed`；其格式和可选值由参数类型及调用流程约束。
            tool_name: tool 名称。
            audit_callback: 经过类型边界校验的 `audit_callback`；其格式和可选值由参数类型及调用流程约束。
            *args: 经过类型边界校验的 `args`；其格式和可选值由参数类型及调用流程约束。
            **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
        """
        missing = set(required_permissions).difference(context.permissions)
        if missing:
            raise PermissionError(f"tool requires permissions: {', '.join(sorted(missing))}")
        needs_confirmation = effect == "external" if requires_confirmation is None else requires_confirmation
        if needs_confirmation and not confirmed:
            name = tool_name or getattr(call, "__name__", "tool")
            raise ToolApprovalRequired(str(name))
        if effect == "external":
            _validate_outbound_values((args, kwargs))
        if self.calls >= self.policy.max_calls:
            raise RuntimeError(f"tool call limit exceeded: {self.policy.max_calls}")

        self.calls += 1
        attempts = 1 + (self.policy.max_retries if effect in self.policy.retry_effects else 0)
        started = time.perf_counter()
        input_summary = _summarize_for_audit({"args": args, "kwargs": kwargs}, limit=200)
        if audit_callback is not None:
            await _emit_audit(
                audit_callback,
                asdict(
                    ToolAuditRecord(
                        tool_name=tool_name or getattr(call, "__name__", "tool"),
                        effect=effect,
                        status="started",
                        input_summary=input_summary,
                    )
                ),
            )
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    call(*args, **kwargs), timeout=self.policy.timeout_seconds
                )
                output = _redact(result) if self.policy.redact_results else result
                if audit_callback is not None:
                    await _emit_audit(
                        audit_callback,
                        asdict(
                            ToolAuditRecord(
                                tool_name=tool_name or getattr(call, "__name__", "tool"),
                                effect=effect,
                                status="completed",
                                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                                input_summary=input_summary,
                                output_summary=_summarize_for_audit(output, limit=300),
                            )
                        ),
                    )
                return output
            except Exception as exc:
                if attempt == attempts - 1:
                    if audit_callback is not None:
                        await _emit_audit(
                            audit_callback,
                            asdict(
                                ToolAuditRecord(
                                    tool_name=tool_name or getattr(call, "__name__", "tool"),
                                    effect=effect,
                                    status="failed",
                                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                                    input_summary=input_summary,
                                    error_type=type(exc).__name__,
                                    error_message=safe_error_message(exc),
                                )
                            ),
                        )
                    raise


async def _emit_audit(
    callback: Callable[[dict[str, Any]], Awaitable[None] | None],
    event: dict[str, Any],
) -> None:
    """投递审计事件；兼容同步和异步 sink。"""

    result = callback(event)
    if inspect.isawaitable(result):
        await result


def _summarize_for_audit(value: Any, *, limit: int) -> str:
    """生成脱敏且有长度上限的审计摘要。"""

    return str(redact_secrets(_redact(value)))[:limit]


_SECRET_KEYS = {"api_key", "apikey", "authorization", "token", "secret", "password"}


def _validate_outbound_values(value: Any) -> None:
    """校验 outbound values 是否满足当前流程约束；失败时返回可定位的业务异常，不执行副作用。

    Args:
        value: 取值。
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
    """校验 public url 是否满足当前流程约束；失败时返回可定位的业务异常，不执行副作用。

    Args:
        value: 取值。
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
    """脱敏日志和审计载荷中的凭据、Cookie、认证头及大段敏感文本。

    Args:
        value: 取值。
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
