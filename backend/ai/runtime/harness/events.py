"""Harness 事件的 best-effort fan-out。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import cast

from .contracts import EventSink, HarnessEvent

EventReceiver = Callable[[HarnessEvent], Awaitable[None]]


class BestEffortEventSink:
    """隔离单个可选 sink 失败，并继续投影给其他消费者。"""

    def __init__(self, sinks: Iterable[EventSink | EventReceiver] = ()) -> None:
        """保存 sink 列表并记录降级错误类型。

        Args:
            sinks: 待投影的 sink（实现 emit 方法）或接收函数集合。
        """

        self._sinks = tuple(sinks)
        self._error_types: list[str] = []

    @property       # 作用是把一个方法 伪装成属性 来调用
    def error_types(self) -> tuple[str, ...]:
        """返回不含异常正文的 sink 降级类型。"""

        return tuple(self._error_types)

    async def emit(self, event: HarnessEvent) -> None:
        """向所有 sink 投影事件，单个失败不向业务调用方冒泡。

        Args:
            event: 需要投影的受限运行事件。
        """

        for sink in self._sinks:
            try:
                emitter = getattr(sink, "emit", None)   # 取下游 sink 的 emit 方法（没有就 None）
                if callable(emitter):                   # 如果它有 emit 方法
                    await emitter(event)                #   调它的 emit 发事件
                else:                                   # 否则
                    await cast(EventReceiver, sink)(event)  # 兼容函数式 receiver
            except Exception as exc:  # noqa: BLE001 - telemetry must remain best effort
                self._error_types.append(type(exc).__name__)
