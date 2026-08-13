"""通用 Agent 图构造器注册表。"""

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

GraphBuilder = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class GraphSpec:
    """可发现工作流图的注册声明。"""

    name: str
    version: str
    builder: GraphBuilder


class GraphRegistry:
    """维护不依赖具体业务 Agent 的图注册表。"""

    def __init__(self) -> None:
        self._specs: dict[str, GraphSpec] = {}
        self._lock = RLock()

    def register(self, spec: GraphSpec, *, replace: bool = False) -> None:
        """注册图构造声明，拒绝重复名称。"""

        key = spec.name.strip().lower()
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"graph already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, **kwargs: Any) -> Any:
        """根据名称构建已注册的图。"""

        key = name.strip().lower()
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise KeyError(f"unknown graph: {key}") from exc
        return spec.builder(**kwargs)

    def names(self) -> tuple[str, ...]:
        """返回稳定排序的注册名称。"""

        return tuple(sorted(self._specs))


graph_registry = GraphRegistry()
