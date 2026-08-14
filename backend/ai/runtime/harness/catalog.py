"""组合 AgentDefinition 与生产 adapter 的只读 Catalog（查找表）。"""

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
    """提供 task type到权威定义和生产 adapter 的 fail-closed 解析。"""

    def __init__(
        self,
        *,
        definitions: tuple[AgentDefinition, ...],
        adapters: ExecutionAdapterRegistry,
        prompt_refs: frozenset[tuple[str, str]],
        graph_names: frozenset[str],
    ) -> None:
        """构建以 task_type 为键的定义查找表，并持有 adapter/prompt/graph 引用。

        Args:
            definitions: 全部任务定义，重复 task_type 直接报错。
            adapters: 已注册的 adapter 注册表，供 resolve() 取执行器。
            prompt_refs: 已注册的 (prompt_name, prompt_version) 集合。
            graph_names: 已注册的 graph 名称集合。
        """
        # 把定义按 task_type 建成查找表；重复定义属于配置错误，启动即失败。
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
        """启动期只读校验全部定义（模式/门禁/副作用、adapter/prompt/graph、孤儿 adapter），有问题聚合抛出。

        只读、不构建 Graph、不实例化业务依赖，保证配置错误启动即暴露（fail-closed）。
        """

        errors: list[str] = []
        declared_adapter_keys: set[str] = set()
        allowed_modes = {"queued", "inline", "stream", "session"}
        allowed_gate_policies = {"global", "worker_limit", "none"}
        allowed_side_effect_policies = {"read_only", "local_write", "external_effect"}
        for definition in self._definitions.values():
            task_type = definition.task_type
            # 1) 执行模式：必须声明，且只能在合法集合内。
            if not definition.execution_modes:
                errors.append(f"{task_type}: execution modes are required")
            unknown_modes = set(definition.execution_modes) - allowed_modes
            if unknown_modes:
                errors.append(f"{task_type}: unknown execution modes {sorted(unknown_modes)}")
            # 2) 门禁与副作用策略：必须是合法取值。
            if definition.run_gate_policy not in allowed_gate_policies:
                errors.append(f"{task_type}: unknown run gate policy {definition.run_gate_policy!r}")
            if definition.side_effect_policy not in allowed_side_effect_policies:
                errors.append(
                    f"{task_type}: unknown side effect policy {definition.side_effect_policy!r}"
                )
            # 3) 组合约束：worker_limit 门禁要求 queued 模式；评测任务禁外部副作用。
            if definition.run_gate_policy == "worker_limit" and "queued" not in definition.execution_modes:
                errors.append(f"{task_type}: worker_limit policy requires queued execution mode")
            if definition.evaluation_enabled and definition.side_effect_policy == "external_effect":
                errors.append(f"{task_type}: external_effect policy is not allowed for evaluation")
            # 4) adapter：必须声明 adapter_key，且该 key 必须在注册表中存在。
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

            # 5) prompt：name 和 version 必须成对声明，且已注册。
            prompt_pair = (definition.prompt_name, definition.prompt_version)
            if (prompt_pair[0] is None) != (prompt_pair[1] is None):
                errors.append(f"{task_type}: prompt name/version must be declared together")
            elif prompt_pair[0] is not None and prompt_pair not in self._prompt_refs:
                errors.append(
                    f"{task_type}: prompt {prompt_pair[0]}@{prompt_pair[1]} is not registered"
                )

            # 6) graph：声明为 required 时，graph_name 必须已注册。
            if (
                definition.graph_reference_mode == "required"
                and definition.graph_name not in self._graph_names
            ):
                errors.append(
                    f"{task_type}: graph {definition.graph_name!r} is not registered"
                )

        # 7) 孤儿 adapter：注册了但没有任何定义引用，视为配置不一致。
        orphaned = set(self._adapters.keys()) - declared_adapter_keys
        errors.extend(f"orphan adapter: {key}" for key in sorted(orphaned))
        if errors:
            raise CatalogValidationError("; ".join(errors))

    def definition(self, task_type: str) -> AgentDefinition:
        """按 task_type 读取任务定义；未知任务直接报错，不做名称回退。"""

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
        """把 task_type 解析为可执行的定义 + adapter 组合，并校验模式/环境合法性（fail-closed）。

        Args:
            task_type: 任务类型名。
            execution_mode: 请求的执行模式。
            environment: 运行环境，默认生产。
        """

        definition = self.definition(task_type)
        if not definition.adapter_key:
            raise ValueError(f"agent task has no Harness adapter: {task_type}")
        if environment == "evaluation":
            # 评测环境：必须用 evaluation 模式，且该任务已开启评测支持。
            if execution_mode != "evaluation" or not definition.evaluation_enabled:
                raise ValueError(f"agent task is not enabled for evaluation: {task_type}")
        elif execution_mode not in definition.execution_modes:
            # 生产环境：execution_mode 必须在任务声明的允许列表中，拒绝模式漂移。
            raise ValueError(
                f"execution mode {execution_mode!r} is not allowed for {task_type}"
            )
        return CatalogEntry(
            definition=definition,
            adapter=self._adapters.get(definition.adapter_key),
        )
