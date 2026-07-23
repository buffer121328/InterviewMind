"""业务 Agent 图构造器注册表。"""

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

GraphBuilder = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class GraphSpec:
    """表示 `GraphSpec` 相关的数据或行为。"""
    name: str
    version: str
    builder: GraphBuilder


class GraphRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._specs: dict[str, GraphSpec] = {}
        self._lock = RLock()

    def register(self, spec: GraphSpec, *, replace: bool = False) -> None:
        """注册 当前对象。

        Args:
            spec: 调用方传入的 `spec` 参数。
            replace: 调用方传入的 `replace` 参数。
        """
        key = spec.name.strip().lower()
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"graph already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, **kwargs: Any) -> Any:
        """构建 当前对象。

        Args:
            name: 名称。
            **kwargs: 调用方传入的 `kwargs` 参数。
        """
        key = name.strip().lower()
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise KeyError(f"unknown graph: {key}") from exc
        return spec.builder(**kwargs)

    def names(self) -> tuple[str, ...]:
        """执行 `names` 相关逻辑。"""
        return tuple(sorted(self._specs))


graph_registry = GraphRegistry()


async def _build_interview(**kwargs: Any) -> Any:
    """构建 `interview`。

    Args:
        **kwargs: 调用方传入的 `kwargs` 参数。
    """
    from ai.agents.interview.graph import build_interview_graph

    return await build_interview_graph(**kwargs)


def _build_resume_analyzer(**kwargs: Any) -> Any:
    """构建 `resume analyzer`。

    Args:
        **kwargs: 调用方传入的 `kwargs` 参数。
    """
    from ai.agents.resume.resume_analyzer_graph import build_resume_analyzer_graph

    return build_resume_analyzer_graph(**kwargs)


def _build_resume_optimizer(**kwargs: Any) -> Any:
    """构建 `resume optimizer`。

    Args:
        **kwargs: 调用方传入的 `kwargs` 参数。
    """
    from ai.agents.resume.resume_orchestrator import build_resume_optimizer_graph

    return build_resume_optimizer_graph(**kwargs)


def _build_resume_generator(**kwargs: Any) -> Any:
    """构建 `resume generator`。

    Args:
        **kwargs: 调用方传入的 `kwargs` 参数。
    """
    from ai.agents.resume.resume_generation_graph import build_resume_generation_graph

    return build_resume_generation_graph(**kwargs)


graph_registry.register(GraphSpec("interview", "1", _build_interview))
graph_registry.register(GraphSpec("resume_analyzer", "1", _build_resume_analyzer))
graph_registry.register(GraphSpec("resume_optimizer", "1", _build_resume_optimizer))
graph_registry.register(GraphSpec("resume_generator", "1", _build_resume_generator))
