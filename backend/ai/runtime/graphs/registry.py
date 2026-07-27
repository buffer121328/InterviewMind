"""业务 Agent 图构造器注册表。"""

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

GraphBuilder = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class GraphSpec:
    """可发现工作流图的注册声明，描述图名称、版本和构建入口；注册表只管理契约，不在声明阶段执行任务副作用。"""
    name: str
    version: str
    builder: GraphBuilder


class GraphRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化 `GraphRegistry` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._specs: dict[str, GraphSpec] = {}
        self._lock = RLock()

    def register(self, spec: GraphSpec, *, replace: bool = False) -> None:
        """注册可供运行时发现的声明，拒绝重复或不完整定义，保持模块加载顺序不会改变最终契约。

        Args:
            spec: 经过类型边界校验的 `spec`；其格式和可选值由参数类型及调用流程约束。
            replace: 经过类型边界校验的 `replace`；其格式和可选值由参数类型及调用流程约束。
        """
        key = spec.name.strip().lower()
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"graph already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, **kwargs: Any) -> Any:
        """根据已注册的工具或配置构建可执行对象；先保留契约和权限信息，实际外部副作用由执行器统一治理。

        Args:
            name: 名称。
            **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
        """
        key = name.strip().lower()
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise KeyError(f"unknown graph: {key}") from exc
        return spec.builder(**kwargs)

    def names(self) -> tuple[str, ...]:
        """返回注册表中稳定排序的名称列表，供诊断和管理接口使用。"""
        return tuple(sorted(self._specs))


graph_registry = GraphRegistry()


async def _build_interview(**kwargs: Any) -> Any:
    """构建 `interview`。

    Args:
        **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
    """
    from ai.agents.interview.graph import build_interview_graph

    return await build_interview_graph(**kwargs)


def _build_resume_analyzer(**kwargs: Any) -> Any:
    """构建 `resume analyzer`。

    Args:
        **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
    """
    from ai.agents.resume.resume_analyzer_graph import build_resume_analyzer_graph

    return build_resume_analyzer_graph(**kwargs)


def _build_resume_optimizer(**kwargs: Any) -> Any:
    """构建 `resume optimizer`。

    Args:
        **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
    """
    from ai.agents.resume.resume_orchestrator import build_resume_optimizer_graph

    return build_resume_optimizer_graph(**kwargs)


def _build_resume_generator(**kwargs: Any) -> Any:
    """构建 `resume generator`。

    Args:
        **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
    """
    from ai.agents.resume.resume_generation_graph import build_resume_generation_graph

    return build_resume_generation_graph(**kwargs)


graph_registry.register(GraphSpec("interview", "1", _build_interview))
graph_registry.register(GraphSpec("resume_analyzer", "1", _build_resume_analyzer))
graph_registry.register(GraphSpec("resume_optimizer", "1", _build_resume_optimizer))
graph_registry.register(GraphSpec("resume_generator", "1", _build_resume_generator))
