"""组合 AgentDefinition 与生产 adapter 的只读 Catalog。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.agent_definitions import AgentDefinition

from .contracts import ExecutionAdapter, ExecutionMode
from .registry import ExecutionAdapterRegistry


class CatalogValidationError(ValueError):
    """Catalog 定义、adapter、Prompt 或 Graph 不一致。"""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """已解析且可执行的定义与 adapter 组合。"""

    definition: AgentDefinition
    adapter: ExecutionAdapter


class AgentCatalog:
    """提供 task type 到权威定义和生产 adapter 的 fail-closed 解析。"""

    def __init__(
        self,
        *,
        definitions: tuple[AgentDefinition, ...],
        adapters: ExecutionAdapterRegistry,
        prompt_refs: frozenset[tuple[str, str]],
        graph_names: frozenset[str],
    ) -> None:
        items: dict[str, AgentDefinition] = {}
        for definition in definitions:
            if definition.task_type in items:
                raise CatalogValidationError(
                    f"duplicate task definition: {definition.task_type}"
                )
            items[definition.task_type] = definition
        self._definitions = items
        self._adapters = adapters
        self._prompt_refs = prompt_refs
        self._graph_names = graph_names

    def validate(self) -> None:
        """只读验证全部定义，不构建 Graph 或实例化业务依赖。"""

        errors: list[str] = []
        declared_adapter_keys: set[str] = set()
        allowed_modes = {"queued", "inline", "stream", "session"}
        allowed_gate_policies = {"global", "worker_limit", "none"}
        allowed_side_effect_policies = {"read_only", "local_write", "external_effect"}
        for definition in self._definitions.values():
            task_type = definition.task_type
            if definition.deprecated:
                continue
            if not definition.execution_modes:
                errors.append(f"{task_type}: execution modes are required")
            unknown_modes = set(definition.execution_modes) - allowed_modes
            if unknown_modes:
                errors.append(f"{task_type}: unknown execution modes {sorted(unknown_modes)}")
            if definition.run_gate_policy not in allowed_gate_policies:
                errors.append(f"{task_type}: unknown run gate policy {definition.run_gate_policy!r}")
            if definition.side_effect_policy not in allowed_side_effect_policies:
                errors.append(
                    f"{task_type}: unknown side effect policy {definition.side_effect_policy!r}"
                )
            if definition.run_gate_policy == "worker_limit" and "queued" not in definition.execution_modes:
                errors.append(f"{task_type}: worker_limit policy requires queued execution mode")
            if definition.evaluation_enabled and definition.side_effect_policy == "external_effect":
                errors.append(f"{task_type}: external_effect policy is not allowed for evaluation")
            if definition.migration_state == "harness":
                if not definition.adapter_key:
                    errors.append(f"{task_type}: adapter key is required")
                else:
                    declared_adapter_keys.add(definition.adapter_key)
                    try:
                        self._adapters.get(definition.adapter_key)
                    except KeyError:
                        errors.append(
                            f"{task_type}: adapter {definition.adapter_key!r} is not registered"
                        )
            elif definition.adapter_key is not None:
                errors.append(f"{task_type}: legacy task must not expose an adapter")

            prompt_pair = (definition.prompt_name, definition.prompt_version)
            if (prompt_pair[0] is None) != (prompt_pair[1] is None):
                errors.append(f"{task_type}: prompt name/version must be declared together")
            elif prompt_pair[0] is not None and prompt_pair not in self._prompt_refs:
                errors.append(
                    f"{task_type}: prompt {prompt_pair[0]}@{prompt_pair[1]} is not registered"
                )

            if (
                definition.graph_reference_mode == "required"
                and definition.graph_name not in self._graph_names
            ):
                errors.append(
                    f"{task_type}: graph {definition.graph_name!r} is not registered"
                )

        orphaned = set(self._adapters.keys()) - declared_adapter_keys
        errors.extend(f"orphan adapter: {key}" for key in sorted(orphaned))
        if errors:
            raise CatalogValidationError("; ".join(errors))

    def definition(self, task_type: str) -> AgentDefinition:
        """读取定义；未知 task type 不回退。"""

        try:
            return self._definitions[task_type]
        except KeyError as exc:
            raise ValueError(f"unknown agent task: {task_type}") from exc

    def resolve(
        self,
        task_type: str,
        *,
        execution_mode: ExecutionMode,
        environment: Literal["production", "evaluation"] = "production",
    ) -> CatalogEntry:
        """按定义策略解析 adapter，拒绝 deprecated、legacy 和模式漂移。"""

        definition = self.definition(task_type)
        if definition.deprecated:
            raise ValueError(f"deprecated agent task cannot execute: {task_type}")
        if definition.migration_state != "harness" or not definition.adapter_key:
            raise ValueError(f"legacy agent task is not managed by Harness: {task_type}")
        if environment == "evaluation":
            if execution_mode != "evaluation" or not definition.evaluation_enabled:
                raise ValueError(f"agent task is not enabled for evaluation: {task_type}")
        elif execution_mode not in definition.execution_modes:
            raise ValueError(
                f"execution mode {execution_mode!r} is not allowed for {task_type}"
            )
        return CatalogEntry(
            definition=definition,
            adapter=self._adapters.get(definition.adapter_key),
        )
