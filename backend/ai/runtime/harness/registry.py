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
        """把 payload 和 context 转交给包装的真实业务 callable 执行。

        Args:
            payload: 任务入参。
            context: 执行上下文（身份与隔离约束）。
        """

        return await self.runner(payload, context)


class ExecutionAdapterRegistry:
    """按规范化 key 注册生产 adapter，默认拒绝覆盖。"""

    def __init__(self) -> None:
        self._items: dict[str, ExecutionAdapter] = {}
        self._lock = RLock()

    def register(self, adapter: ExecutionAdapter, *, replace: bool = False) -> None:
        """按规范化 key 注册 adapter；空 key 或重复 key 拒绝（fail-closed）。

        Args:
            adapter: 待注册的执行适配器，需含 key 和 run。
            replace: 为 True 时允许覆盖已存在的同名 adapter。
        """

        key = adapter.key.strip().lower()
        if not key:
            raise ValueError("execution adapter key must not be empty")
        with self._lock:
            if key in self._items and not replace:
                raise ValueError(f"execution adapter already registered: {key}")
            self._items[key] = adapter

    def get(self, key: str) -> ExecutionAdapter:
        """按 key 读取 adapter；未知 key 抛 KeyError，不做名称回退。

        Args:
            key: adapter 的注册名。
        """

        normalized = key.strip().lower()
        try:
            return self._items[normalized]
        except KeyError as exc:
            raise KeyError(f"unknown execution adapter: {normalized}") from exc

    def keys(self) -> tuple[str, ...]:
        """返回稳定排序的 adapter key。"""

        return tuple(sorted(self._items))
