"""Harness 事件的 best-effort fan-out。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from .contracts import EventSink, HarnessEvent

EventReceiver = Callable[[HarnessEvent], Awaitable[None]]


class BestEffortEventSink:
    """隔离单个可选 sink 失败，并继续投影给其他消费者。"""

    def __init__(self, sinks: Iterable[EventSink | EventReceiver] = ()) -> None:
        self._sinks = tuple(sinks)
        self._error_types: list[str] = []

    @property
    def error_types(self) -> tuple[str, ...]:
        """返回不含异常正文的 sink 降级类型。"""

        return tuple(self._error_types)

    async def emit(self, event: HarnessEvent) -> None:
        """向所有 sink 投影事件，单个失败不向业务调用方冒泡。"""

        for sink in self._sinks:
            try:
                emitter = getattr(sink, "emit", None)
                if callable(emitter):
                    await emitter(event)
                else:
                    await sink(event)  # type: ignore[operator]
            except Exception as exc:  # noqa: BLE001 - telemetry must remain best effort
                self._error_types.append(type(exc).__name__)
