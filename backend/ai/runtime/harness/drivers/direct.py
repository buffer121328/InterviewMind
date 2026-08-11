"""请求内与评测执行 driver。"""

from __future__ import annotations

from typing import Any

from ..catalog import AgentCatalog
from ..contracts import (
    DeferredExecutionResult,
    EventSink,
    ExecutionContext,
    ExecutionResult,
    ProgressCallback,
)


class InlineDriver:
    """在当前请求内调用 Catalog adapter，不拥有持久 AgentRun 终态。"""

    def __init__(self, catalog: AgentCatalog) -> None:
        self._catalog = catalog

    async def run(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        session_id: str | None = None,
        run_id: str | None = None,
        progress: ProgressCallback | None = None,
        event_sink: EventSink | None = None,
    ) -> ExecutionResult:
        """用 production/inline policy 执行一个 adapter。"""

        entry = self._catalog.resolve(task_type, execution_mode="inline")
        context = ExecutionContext(
            run_id=run_id,
            task_type=task_type,
            agent_name=entry.definition.name,
            agent_version=entry.definition.version,
            user_id=user_id,
            session_id=session_id,
            owner_scope=f"user:{user_id}",
            execution_mode="inline",
            environment="production",
            external_tools_enabled=entry.definition.side_effect_policy == "external_effect",
            side_effect_policy=entry.definition.side_effect_policy,
            progress=progress,
            event_sink=event_sink,
        )
        result = await entry.adapter.run(dict(payload), context)
        if isinstance(result, (dict, DeferredExecutionResult)):
            return result
        raise TypeError("production inline adapter must return an object result")


class EvaluationDriver:
    """使用隔离身份与 namespace 调用允许评测的生产 adapter。"""

    def __init__(self, catalog: AgentCatalog) -> None:
        self._catalog = catalog

    async def run(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        run_id: str,
        user_id: str,
        session_id: str,
        memory_namespace: str,
        artifact_namespace: str,
        progress: ProgressCallback | None = None,
        event_sink: EventSink | None = None,
    ) -> ExecutionResult:
        """构造 fail-closed evaluation context 并执行同一 adapter。"""

        entry = self._catalog.resolve(
            task_type,
            execution_mode="evaluation",
            environment="evaluation",
        )
        context = ExecutionContext(
            run_id=run_id,
            task_type=task_type,
            agent_name=entry.definition.name,
            agent_version=entry.definition.version,
            user_id=user_id,
            session_id=session_id,
            owner_scope=f"eval:{run_id}",
            execution_mode="evaluation",
            environment="evaluation",
            memory_namespace=memory_namespace,
            artifact_namespace=artifact_namespace,
            external_tools_enabled=False,
            side_effect_policy=entry.definition.side_effect_policy,
            progress=progress,
            event_sink=event_sink,
        )
        result = await entry.adapter.run(dict(payload), context)
        if isinstance(result, DeferredExecutionResult):
            raise TypeError("evaluation adapter cannot return deferred persistence")
        return result
