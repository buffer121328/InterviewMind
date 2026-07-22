"""带权限和副作用元数据的工具注册表。"""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Literal

from app.infrastructure.runtime.context import AgentContext

ToolEffect = Literal["none", "read", "write", "external"]
ToolFactory = Callable[[AgentContext], list[Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """表示 `ToolSpec` 相关的数据或行为。"""
    name: str
    factory: ToolFactory
    effect: ToolEffect = "read"
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    requires_confirmation: bool = False


class ToolRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._specs: dict[str, ToolSpec] = {}
        self._lock = RLock()

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        """注册 当前对象。

        Args:
            spec: 调用方传入的 `spec` 参数。
            replace: 调用方传入的 `replace` 参数。
        """
        key = spec.name.strip().lower()
        if not key:
            raise ValueError("tool group name must not be empty")
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"tool group already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, context: AgentContext) -> list[Any]:
        """构建 当前对象。

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
        """执行 `describe` 相关逻辑。

        Args:
            name: 名称。
        """
        return self._specs[name.strip().lower()]

    def names(self) -> tuple[str, ...]:
        """执行 `names` 相关逻辑。"""
        return tuple(sorted(self._specs))


tool_registry = ToolRegistry()


def _interview_tools(context: AgentContext) -> list[Any]:
    """执行 `_interview_tools` 相关逻辑。

    Args:
        context: 运行上下文。
    """
    from app.tools.interview_tools import make_interview_tools

    return make_interview_tools(context.user_id, context.session_id)


def _resume_tools(context: AgentContext) -> list[Any]:
    """执行 `_resume_tools` 相关逻辑。

    Args:
        context: 运行上下文。
    """
    from app.tools.resume_tools import make_resume_tools

    resume = str(context.api_config.get("resume_content", ""))
    jd = str(context.api_config.get("job_description", ""))
    return make_resume_tools(resume_content=resume, job_description=jd)


def _job_tools(context: AgentContext) -> list[Any]:
    """执行 `_job_tools` 相关逻辑。

    Args:
        context: 运行上下文。
    """
    from app.tools.job_tools import make_jobs_tools

    return make_jobs_tools(
        user_id=context.user_id,
        api_config=dict(context.api_config),
        resume_content=str(context.api_config.get("resume_content", "")),
    )


def _memory_tools(context: AgentContext) -> list[Any]:
    """执行 `_memory_tools` 相关逻辑。

    Args:
        context: 运行上下文。
    """
    from app.tools.memory_tools import make_memory_tools

    return make_memory_tools(user_id=context.user_id)


tool_registry.register(ToolSpec("interview", _interview_tools, effect="read"))
tool_registry.register(ToolSpec("resume", _resume_tools, effect="read"))
tool_registry.register(ToolSpec("memory", _memory_tools, effect="read"))
tool_registry.register(
    ToolSpec(
        "job_application",
        _job_tools,
        effect="external",
        required_permissions=frozenset({"jobs:automate"}),
        requires_confirmation=True,
    )
)
