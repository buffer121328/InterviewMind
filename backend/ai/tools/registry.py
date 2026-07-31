"""带权限和副作用元数据的工具注册表。"""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Literal

from ai.runtime.context import AgentContext

ToolEffect = Literal["none", "read", "write", "external"]
ToolFactory = Callable[[AgentContext], list[Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """数据对象，承载 `ToolSpec` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    name: str
    factory: ToolFactory
    effect: ToolEffect = "read"
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    requires_confirmation: bool = False


class ToolRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化 `ToolRegistry` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._specs: dict[str, ToolSpec] = {}
        self._lock = RLock()

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        """注册可供运行时发现的声明，拒绝重复或不完整定义，保持模块加载顺序不会改变最终契约。

        Args:
            spec: 经过类型边界校验的 `spec`；其格式和可选值由参数类型及调用流程约束。
            replace: 经过类型边界校验的 `replace`；其格式和可选值由参数类型及调用流程约束。
        """
        key = spec.name.strip().lower()
        if not key:
            raise ValueError("tool group name must not be empty")
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"tool group already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, context: AgentContext) -> list[Any]:
        """根据已注册的工具或配置构建可执行对象；先保留契约和权限信息，实际外部副作用由执行器统一治理。

        Args:
            name: 名称。
            context: 运行上下文。
        """
        key = name.strip().lower()
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise KeyError(f"unknown tool group: {key}") from exc
        missing = spec.required_permissions.difference(context.permissions)
        if missing:
            raise PermissionError(
                f"tool group {key} requires permissions: {', '.join(sorted(missing))}"
            )
        return spec.factory(context)

    def describe(self, name: str) -> ToolSpec:
        """返回注册工具的可审计描述，包括权限、效果和确认要求。

        Args:
            name: 名称。
        """
        return self._specs[name.strip().lower()]

    def names(self) -> tuple[str, ...]:
        """返回注册表中稳定排序的名称列表，供诊断和管理接口使用。"""
        return tuple(sorted(self._specs))


tool_registry = ToolRegistry()


def _interview_tools(context: AgentContext) -> list[Any]:
    """构造绑定当前用户和请求配置的面试工具集合，并附加工具治理契约。

    Args:
        context: 运行上下文。
    """
    from ai.tools.interview_tools import make_interview_tools

    return make_interview_tools(context.user_id, context.session_id)


def _resume_tools(context: AgentContext) -> list[Any]:
    """构造绑定当前用户简历上下文的工具集合，并保留事实和确认约束。

    Args:
        context: 运行上下文。
    """
    from ai.tools.resume_tools import make_resume_tools

    resume = str(context.api_config.get("resume_content", ""))
    jd = str(context.api_config.get("job_description", ""))
    return make_resume_tools(resume_content=resume, job_description=jd)


def _memory_tools(context: AgentContext) -> list[Any]:
    """构造绑定当前用户的长期记忆工具，并确保记忆读写遵守 namespace 隔离。

    Args:
        context: 运行上下文。
    """
    from ai.tools.memory_tools import make_memory_tools

    return make_memory_tools(user_id=context.user_id)


tool_registry.register(ToolSpec("interview", _interview_tools, effect="read"))
tool_registry.register(ToolSpec("resume", _resume_tools, effect="read"))
tool_registry.register(ToolSpec("memory", _memory_tools, effect="read"))
