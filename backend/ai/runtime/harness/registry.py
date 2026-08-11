"""生产执行适配器的轻量注册表。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any

from .contracts import ExecutionAdapter, ExecutionContext, ExecutionResult

AdapterRunner = Callable[[dict[str, Any], ExecutionContext], Awaitable[ExecutionResult]]


@dataclass(frozen=True, slots=True)
class CallableExecutionAdapter:
    """把异步 callable 包装为稳定 adapter key。"""

    key: str
    runner: AdapterRunner

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """执行注入的真实业务 callable。"""

        return await self.runner(payload, context)


class ExecutionAdapterRegistry:
    """按规范化 key 注册生产 adapter，默认拒绝覆盖。"""

    def __init__(self) -> None:
        self._items: dict[str, ExecutionAdapter] = {}
        self._lock = RLock()

    def register(self, adapter: ExecutionAdapter, *, replace: bool = False) -> None:
        """注册 adapter；空 key 和重复 key fail closed。"""

        key = adapter.key.strip().lower()
        if not key:
            raise ValueError("execution adapter key must not be empty")
        with self._lock:
            if key in self._items and not replace:
                raise ValueError(f"execution adapter already registered: {key}")
            self._items[key] = adapter

    def get(self, key: str) -> ExecutionAdapter:
        """读取显式注册 adapter，未知 key 不做名称回退。"""

        normalized = key.strip().lower()
        try:
            return self._items[normalized]
        except KeyError as exc:
            raise KeyError(f"unknown execution adapter: {normalized}") from exc

    def keys(self) -> tuple[str, ...]:
        """返回稳定排序的 adapter key。"""

        return tuple(sorted(self._items))
