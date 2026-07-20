"""与业务实现解耦的 Agent 定义和版本注册表。"""

from dataclasses import dataclass
from threading import RLock
from typing import Literal

CheckpointPolicy = Literal["none", "memory", "durable"]
CancellationPolicy = Literal["none", "cooperative"]


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    name: str
    version: str
    task_type: str
    title: str
    steps: tuple[tuple[str, str], ...]
    checkpoint_policy: CheckpointPolicy = "none"
    cancellation_policy: CancellationPolicy = "cooperative"
    graph_name: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None


class AgentDefinitionRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentDefinition] = {}
        self._lock = RLock()

    def register(self, definition: AgentDefinition, *, replace: bool = False) -> None:
        with self._lock:
            if definition.task_type in self._items and not replace:
                raise ValueError(f"agent task already registered: {definition.task_type}")
            self._items[definition.task_type] = definition

    def get(self, task_type: str) -> AgentDefinition:
        try:
            return self._items[task_type]
        except KeyError as exc:
            raise KeyError(f"unknown agent task: {task_type}") from exc

    def definitions(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._items[key] for key in sorted(self._items))


agent_definition_registry = AgentDefinitionRegistry()
