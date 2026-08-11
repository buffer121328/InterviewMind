"""Agent Harness 的无 I/O 执行协议。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, TypeAlias

ExecutionMode: TypeAlias = Literal["queued", "inline", "stream", "session", "evaluation"]
ExecutionEnvironment: TypeAlias = Literal["production", "evaluation"]
SideEffectPolicy: TypeAlias = Literal["read_only", "local_write", "external_effect"]
ProgressCallback: TypeAlias = Callable[[str], Awaitable[None]]
PersistResultCallback: TypeAlias = Callable[[Any], Awaitable[dict[str, Any]]]
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class DeferredExecutionResult:
    """把业务结果写入延迟到 AgentRun 成功事务内。"""

    persist: PersistResultCallback = field(repr=False)


ExecutionResult: TypeAlias = JsonValue | DeferredExecutionResult


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    """传给受限事件 sink 的有界运行事件。"""

    event_type: str
    stage: str | None = None
    status: str | None = None
    payload_summary: tuple[tuple[str, str | int | float | bool | None], ...] = ()


class EventSink(Protocol):
    """异步接收 Harness 事件；实现不得反向控制业务终态。"""

    async def emit(self, event: HarnessEvent) -> None:
        """投影一个已脱敏事件。"""


class ExecutionAdapter(Protocol):
    """生产 Agent 执行适配器。"""

    key: str

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """在受限上下文中执行真实业务入口。"""


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """只携带运行标识、隔离策略与受限回调的执行上下文。"""

    run_id: str | None
    task_type: str
    agent_name: str
    agent_version: str
    user_id: str
    session_id: str | None
    owner_scope: str
    execution_mode: ExecutionMode
    environment: ExecutionEnvironment
    memory_namespace: str | None = None
    artifact_namespace: str | None = None
    external_tools_enabled: bool = False
    side_effect_policy: SideEffectPolicy = "read_only"
    deadline_at: datetime | None = None
    model_config_ref: str | None = None
    correlation_metadata: tuple[tuple[str, str], ...] = ()
    progress: ProgressCallback | None = field(default=None, repr=False)
    event_sink: EventSink | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """验证评测隔离和模式组合，拒绝隐式扩大副作用。"""

        if not self.task_type or not self.agent_name or not self.agent_version:
            raise ValueError("execution context requires task and agent identity")
        if self.environment == "evaluation":
            if self.execution_mode != "evaluation":
                raise ValueError("evaluation environment requires evaluation execution mode")
            if self.external_tools_enabled:
                raise ValueError("external tools must be disabled in evaluation")
            namespaces = (self.memory_namespace, self.artifact_namespace)
            if any(not value or not value.startswith("eval:") for value in namespaces):
                raise ValueError("evaluation resources require isolated eval namespaces")
        elif self.execution_mode == "evaluation":
            raise ValueError("evaluation execution mode requires evaluation environment")

    async def mark_progress(self, stage: str) -> None:
        """把阶段变化交给入口 lifecycle owner。"""

        if self.progress is not None:
            await self.progress(stage)

    async def emit(self, event: HarnessEvent) -> None:
        """投影可选事件；sink 的降级策略由其实现负责。"""

        if self.event_sink is not None:
            await self.event_sink.emit(event)
