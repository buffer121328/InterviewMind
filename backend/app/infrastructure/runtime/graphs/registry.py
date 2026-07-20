"""业务 Agent 图构造器注册表。"""

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

GraphBuilder = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class GraphSpec:
    name: str
    version: str
    builder: GraphBuilder


class GraphRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, GraphSpec] = {}
        self._lock = RLock()

    def register(self, spec: GraphSpec, *, replace: bool = False) -> None:
        key = spec.name.strip().lower()
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"graph already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, **kwargs: Any) -> Any:
        key = name.strip().lower()
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise KeyError(f"unknown graph: {key}") from exc
        return spec.builder(**kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


graph_registry = GraphRegistry()


async def _build_interview(**kwargs: Any) -> Any:
    from app.agents.interview.graph import build_interview_graph

    return await build_interview_graph(**kwargs)


def _build_resume_analyzer(**kwargs: Any) -> Any:
    from app.agents.resume_analyzer.graph import build_resume_analyzer_graph

    return build_resume_analyzer_graph(**kwargs)


def _build_resume_optimizer(**kwargs: Any) -> Any:
    from app.agents.resume_optimizer.graph import build_resume_optimizer_graph

    return build_resume_optimizer_graph(**kwargs)


def _build_resume_generator(**kwargs: Any) -> Any:
    from app.agents.resume_generator.graph import build_resume_generation_graph

    return build_resume_generation_graph(**kwargs)


graph_registry.register(GraphSpec("interview", "1", _build_interview))
graph_registry.register(GraphSpec("resume_analyzer", "1", _build_resume_analyzer))
graph_registry.register(GraphSpec("resume_optimizer", "1", _build_resume_optimizer))
graph_registry.register(GraphSpec("resume_generator", "1", _build_resume_generator))
