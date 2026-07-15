"""带权限和副作用元数据的工具注册表。"""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Literal

from app.agent_runtime.context import AgentContext

ToolEffect = Literal["none", "read", "write", "external"]
ToolFactory = Callable[[AgentContext], list[Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    factory: ToolFactory
    effect: ToolEffect = "read"
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    requires_confirmation: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._lock = RLock()

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        key = spec.name.strip().lower()
        if not key:
            raise ValueError("tool group name must not be empty")
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"tool group already registered: {key}")
            self._specs[key] = spec

    def build(self, name: str, context: AgentContext) -> list[Any]:
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
        return self._specs[name.strip().lower()]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


tool_registry = ToolRegistry()


def _interview_tools(context: AgentContext) -> list[Any]:
    from app.services.tools.interview_tools import make_interview_tools

    return make_interview_tools(context.user_id, context.session_id)


def _resume_tools(context: AgentContext) -> list[Any]:
    from app.services.tools.resume_tools import make_resume_tools

    resume = str(context.api_config.get("resume_content", ""))
    jd = str(context.api_config.get("job_description", ""))
    return make_resume_tools(resume_content=resume, job_description=jd)


def _job_tools(context: AgentContext) -> list[Any]:
    from app.services.tools.job_tools import make_jobs_tools

    return make_jobs_tools(
        user_id=context.user_id,
        api_config=dict(context.api_config),
        resume_content=str(context.api_config.get("resume_content", "")),
    )


tool_registry.register(ToolSpec("interview", _interview_tools, effect="read"))
tool_registry.register(ToolSpec("resume", _resume_tools, effect="read"))
tool_registry.register(
    ToolSpec(
        "job_application",
        _job_tools,
        effect="external",
        required_permissions=frozenset({"jobs:automate"}),
        requires_confirmation=True,
    )
)
