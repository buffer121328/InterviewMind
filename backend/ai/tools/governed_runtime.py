"""Registry-backed governed execution for production Agent tools.

The runtime owns one guard per workflow run and keeps tool construction,
contract interpretation, and execution in a single boundary.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from typing import Any

from ai.runtime.context import AgentContext
from app.schemas.tools import get_tool_contract

from .executor import ToolExecutionGuard
from .registry import tool_registry


class GovernedToolRuntime:
    """Build owner-scoped registry tools and execute them through the guard."""

    def __init__(
        self,
        context: AgentContext,
        *,
        groups: Sequence[str] | None = None,
        guard: ToolExecutionGuard | None = None,
        audit_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self.context = context
        self.guard = guard or ToolExecutionGuard()
        self.audit_callback = audit_callback
        self._evaluation_fixtures = self._resolve_evaluation_fixtures(context)
        configured_allowlist = context.runtime_data.get("allowed_tool_calls")
        self._allowed_tool_calls = (
            frozenset(str(item).strip() for item in configured_allowlist if str(item).strip())
            if isinstance(configured_allowlist, (list, tuple, set, frozenset))
            else None
        )
        self._tools: dict[tuple[str, str], Any] = {}
        self._names: dict[str, list[tuple[str, Any]]] = {}
        for group in groups or tool_registry.names():
            for tool in tool_registry.build(group, context):
                name = str(getattr(tool, "name", "")).strip()
                if not name:
                    continue
                if self._allowed_tool_calls is not None and name not in self._allowed_tool_calls:
                    continue
                self._tools[(group, name)] = tool
                self._names.setdefault(name, []).append((group, tool))

    @staticmethod
    def _resolve_evaluation_fixtures(context: AgentContext) -> Mapping[str, Any]:
        """Read fixtures only from an explicitly isolated evaluation context."""

        fixtures = context.runtime_data.get("evaluation_tool_fixtures")
        if fixtures is None:
            return {}
        if (
            context.runtime_data.get("environment") != "evaluation"
            or not context.user_id.startswith("eval-user:")
        ):
            raise PermissionError("tool fixtures require an isolated evaluation context")
        if not isinstance(fixtures, Mapping):
            raise ValueError("evaluation tool fixtures must be a mapping")
        return fixtures

    def names(self, *, group: str | None = None) -> tuple[str, ...]:
        """Return deterministic names available to this runtime."""
        if group:
            return tuple(sorted(name for current, name in self._tools if current == group))
        return tuple(sorted(self._names))

    def _resolve(self, name: str, group: str | None) -> tuple[str, Any]:
        candidates = self._names.get(name.strip(), [])
        if group:
            candidates = [candidate for candidate in candidates if candidate[0] == group]
        if not candidates:
            raise KeyError(f"unknown tool: {name}")
        return candidates[0]

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        group: str | None = None,
        confirmed: bool = False,
        required_permissions: Collection[str] = (),
        call_id: str | None = None,
        parent_call_id: str | None = None,
        workflow_name: str | None = None,
        stage: str | None = None,
        simulated: bool = False,
        audit_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> Any:
        """Execute a named tool using its contract and the shared guard."""
        resolved_group, tool = self._resolve(name, group)
        contract = get_tool_contract(tool) or {}
        effect = contract.get("effect", "read")
        permissions = set(str(item) for item in contract.get("permissions") or ())
        permissions.update(str(item) for item in required_permissions)
        payload = dict(arguments or {})
        fixture = self._evaluation_fixtures.get(str(getattr(tool, "name", name)))

        async def invoke(**_tool_arguments: Any) -> Any:
            if fixture is not None:
                if effect != "read":
                    raise PermissionError("only read-only tools may use evaluation fixtures")
                return await self._invoke_fixture(fixture, payload)
            return await tool.ainvoke(payload)

        return await self.guard.execute(
            invoke,
            context=self.context,
            effect=effect,
            required_permissions=permissions,
            requires_confirmation=bool(contract.get("requires_confirmation", False)),
            confirmed=confirmed,
            tool_name=str(getattr(tool, "name", name)),
            audit_callback=audit_callback or self.audit_callback,
            call_id=call_id,
            parent_call_id=parent_call_id,
            workflow_name=workflow_name or resolved_group,
            stage=stage,
            simulated=simulated or fixture is not None,
        )

    @staticmethod
    async def _invoke_fixture(fixture: Any, arguments: Mapping[str, Any]) -> Any:
        """Return a case-owned fixture only after its bounded argument contract matches."""

        if not isinstance(fixture, Mapping):
            raise ValueError("evaluation tool fixture must be an object")
        expected_arguments = fixture.get("arguments", {})
        if not isinstance(expected_arguments, Mapping):
            raise ValueError("evaluation tool fixture arguments must be an object")
        if any(arguments.get(key) != value for key, value in expected_arguments.items()):
            raise ValueError("evaluation tool fixture argument contract mismatch")
        result = fixture.get("result")
        if callable(result):
            result = result(dict(arguments))
        if inspect.isawaitable(result):
            return await result
        return result


__all__ = ["GovernedToolRuntime"]
