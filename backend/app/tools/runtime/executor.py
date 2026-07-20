"""统一的工具执行边界。"""

import asyncio
import ipaddress
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Collection
from urllib.parse import urlparse

from app.infrastructure.runtime.context import AgentContext

from .registry import ToolEffect


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    timeout_seconds: float = 30.0
    max_calls: int = 20
    max_retries: int = 0
    retry_effects: frozenset[ToolEffect] = frozenset({"none", "read"})
    redact_results: bool = True




@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
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
        super().__init__(message)
        self.tool_name = tool_name


class ToolExecutionGuard:
    """一次运行内共享的工具安全边界。"""

    def __init__(self, policy: ToolExecutionPolicy | None = None) -> None:
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
        audit_callback: Callable[[dict[str, Any]], None] | None = None,
        **kwargs: Any,
    ) -> Any:
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
        input_summary = str((args, kwargs))[:200]
        if audit_callback is not None:
            audit_callback(
                asdict(
                    ToolAuditRecord(
                        tool_name=tool_name or getattr(call, "__name__", "tool"),
                        effect=effect,
                        status="started",
                        input_summary=input_summary,
                    )
                )
            )
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    call(*args, **kwargs), timeout=self.policy.timeout_seconds
                )
                output = _redact(result) if self.policy.redact_results else result
                if audit_callback is not None:
                    audit_callback(
                        asdict(
                            ToolAuditRecord(
                                tool_name=tool_name or getattr(call, "__name__", "tool"),
                                effect=effect,
                                status="completed",
                                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                                input_summary=input_summary,
                                output_summary=str(output)[:300],
                            )
                        )
                    )
                return output
            except Exception as exc:
                if attempt == attempts - 1:
                    if audit_callback is not None:
                        audit_callback(
                            asdict(
                                ToolAuditRecord(
                                    tool_name=tool_name or getattr(call, "__name__", "tool"),
                                    effect=effect,
                                    status="failed",
                                    duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                                    input_summary=input_summary,
                                    error_type=type(exc).__name__,
                                    error_message=str(exc)[:200],
                                )
                            )
                        )
                    raise


_SECRET_KEYS = {"api_key", "apikey", "authorization", "token", "secret", "password"}


def _validate_outbound_values(value: Any) -> None:
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


async def execute_tool(
    call: Callable[..., Awaitable[Any]],
    /,
    *args: Any,
    policy: ToolExecutionPolicy | None = None,
    **kwargs: Any,
) -> Any:
    """兼容旧调用；新 Agent 应复用同一个 ToolExecutionGuard。"""
    current = policy or ToolExecutionPolicy()
    return await asyncio.wait_for(call(*args, **kwargs), timeout=current.timeout_seconds)
