"""Langfuse Tool observation 生命周期适配器。

工具执行器只负责生成不可变的 ``ToolObservationEvent``，本模块把同一事实
投影为一个可下钻的 Langfuse ``tool`` observation。所有 SDK 失败都被吞掉并
记录本地 warning，避免远端观测改变工具业务终态。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from observability.runtime_events import ToolObservationEvent

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ActiveToolSpan:
    """保存跨 await 边界的 Langfuse context manager 与 observation 句柄。"""

    context_manager: Any
    span: Any


_active_tool_spans: ContextVar[dict[str, _ActiveToolSpan] | None] = ContextVar(
    "active_tool_spans", default=None
)


def _get_active_spans() -> dict[str, _ActiveToolSpan]:
    """返回当前任务的 Tool span 注册表，避免跨请求共享句柄。"""

    spans = _active_tool_spans.get()
    if spans is None:
        spans = {}
        _active_tool_spans.set(spans)
    return spans


def _langfuse_client() -> Any | None:
    """延迟读取 Langfuse client，避免本模块与 observability 根模块循环导入。"""

    try:
        from observability import get_langfuse_client, is_agent_observation_active

        if not is_agent_observation_active():
            return None
        return get_langfuse_client()
    except Exception as exc:  # pragma: no cover - 仅防御模块初始化异常。
        logger.warning("Langfuse Tool span 上下文读取失败: %s", type(exc).__name__)
        return None


def _start_context_manager(client: Any, event: ToolObservationEvent) -> _ActiveToolSpan | None:
    """创建不携带业务正文的 Langfuse Tool observation。"""

    metadata = event.to_langfuse_payload()
    context_manager = client.start_as_current_observation(
        name=event.tool_name,
        as_type="tool",
        metadata=metadata,
        end_on_exit=False,
    )
    span = context_manager.__enter__()
    return _ActiveToolSpan(context_manager=context_manager, span=span)


def start_tool_span(event: ToolObservationEvent) -> None:
    """在当前 Agent root span 下开始一个 Tool span；失败时安全 no-op。"""

    client = _langfuse_client()
    if client is None:
        return
    spans = _get_active_spans()
    if event.call_id in spans:
        return
    try:
        active = _start_context_manager(client, event)
        if active is not None:
            spans[event.call_id] = active
    except Exception as exc:  # noqa: BLE001 - Langfuse best-effort 边界。
        logger.warning("Langfuse Tool span 创建失败: %s", type(exc).__name__)


def finish_tool_span(event: ToolObservationEvent) -> None:
    """用工具终态更新并结束对应 Tool span。"""

    spans = _active_tool_spans.get() or {}
    active = spans.pop(event.call_id, None)
    if active is None:
        # 直接记录 completed/failed 的调用也应能在 Langfuse 中下钻。
        start_tool_span(event)
        active = (_active_tool_spans.get() or {}).pop(event.call_id, None)
    if active is None:
        return

    payload = event.to_langfuse_payload()
    level = "ERROR" if event.status == "failed" else "DEFAULT"
    try:
        update = getattr(active.span, "update", None)
        if callable(update):
            update(
                output=payload,
                metadata=payload,
                level=level,
                status_message=event.error_category or event.status,
            )
        end = getattr(active.span, "end", None)
        if callable(end):
            end()
    except Exception as exc:  # noqa: BLE001 - Langfuse best-effort 边界。
        logger.warning("Langfuse Tool span 更新失败: %s", type(exc).__name__)
    finally:
        try:
            active.context_manager.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - 清理失败同样不能阻断业务。
            logger.warning("Langfuse Tool span 清理失败: %s", type(exc).__name__)


def observe_tool_event(event: ToolObservationEvent) -> None:
    """按 Tool 事件状态推进 span 生命周期。"""

    if event.status == "started":
        start_tool_span(event)
        return
    if event.status in {"completed", "failed", "blocked", "skipped"}:
        finish_tool_span(event)


def reset_tool_spans() -> None:
    """测试或请求结束时关闭遗留 span，防止句柄泄漏到后续 ContextVar。"""

    spans = _active_tool_spans.get() or {}
    for call_id, active in list(spans.items()):
        try:
            end = getattr(active.span, "end", None)
            if callable(end):
                end()
            active.context_manager.__exit__(None, None, None)
        except Exception as exc:  # pragma: no cover - 仅防御 SDK 清理异常。
            logger.warning("遗留 Tool span 清理失败 (%s): %s", call_id, type(exc).__name__)
    _active_tool_spans.set(None)
