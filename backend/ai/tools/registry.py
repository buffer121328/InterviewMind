"""按能力组集中构建业务工具；副作用治理由工具级契约负责。"""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable

from ai.runtime.context import AgentContext

ToolFactory = Callable[[AgentContext], list[Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """声明一个工具能力组的名称、构建函数和构建前置权限。"""
    name: str
    factory: ToolFactory
    required_permissions: frozenset[str] = field(default_factory=frozenset)


class ToolRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化线程安全的进程内能力组注册表，不构建或执行工具。"""
        self._specs: dict[str, ToolSpec] = {}
        self._lock = RLock()

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        """注册能力组声明，并拒绝空名称或未显式替换的重复项。

        Args:
            spec: 经过类型边界校验的 `spec`；其格式和可选值由参数类型及调用流程约束。
            replace: 是否显式替换同名能力组。
        """
        key = spec.name.strip().lower()
        if not key:
            raise ValueError("tool group name must not be empty")
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"tool group already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, context: AgentContext) -> list[Any]:
        """校验能力组前置权限后，构建带工具级契约的可执行对象。

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
        """返回工具组的构建声明；副作用与确认要求由组内 ToolContract 声明。

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
    model_config = {
        key: value
        for key, value in context.api_config.items()
        if key not in {"resume_content", "job_description", "verification_source"}
    }
    return make_resume_tools(
        resume_content=resume,
        job_description=jd,
        api_config=model_config or None,
        user_id=context.user_id,
    )


def _verification_tools(context: AgentContext) -> list[Any]:
    """构造绑定可信来源的声明核验工具，不允许模型替换证据源。"""

    from ai.tools.verification_tools import make_verification_tools

    source = context.api_config.get("verification_source")
    if isinstance(source, (list, tuple)):
        source_text = "\n".join(str(item) for item in source)
    else:
        source_text = str(source or context.api_config.get("resume_content", ""))
    return make_verification_tools(source_text)


def _job_tools(context: AgentContext) -> list[Any]:
    """构造绑定 owner 的岗位准备与现有标签页打开工具。"""

    from ai.tools.job_tools import make_job_tools

    return make_job_tools(context.user_id)


def _memory_tools(context: AgentContext) -> list[Any]:
    """构造绑定当前用户的长期记忆工具，并确保记忆读写遵守 namespace 隔离。

    Args:
        context: 运行上下文。
    """
    from ai.tools.memory_tools import make_memory_tools

    return make_memory_tools(user_id=context.user_id)


tool_registry.register(ToolSpec("interview", _interview_tools))
tool_registry.register(ToolSpec("resume", _resume_tools))
tool_registry.register(ToolSpec("verification", _verification_tools))
tool_registry.register(ToolSpec("jobs", _job_tools))
tool_registry.register(ToolSpec("memory", _memory_tools))
