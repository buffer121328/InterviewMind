"""Agent Harness Catalog 与轻量导入契约测试。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ai.runtime.harness.catalog import AgentCatalog, CatalogValidationError
from ai.runtime.harness.registry import (
    CallableExecutionAdapter,
    ExecutionAdapterRegistry,
)
from app.domain.agent_definitions import AgentDefinition, get_agent_definitions


async def _success(payload, context):
    return {"payload": payload, "task_type": context.task_type}


def _definition(**overrides) -> AgentDefinition:
    values = {
        "name": "demo_agent",
        "version": "1",
        "task_type": "demo_task",
        "title": "Demo",
        "steps": (("queued", "等待"), ("running", "执行")),
        "execution_modes": ("queued", "inline"),
        "adapter_key": "demo_adapter",
        "migration_state": "harness",
        "evaluation_enabled": False,
        "side_effect_policy": "local_write",
        "graph_name": "demo_graph",
        "graph_reference_mode": "required",
        "prompt_name": "demo.prompt",
        "prompt_version": "1",
        "run_gate_policy": "global",
    }
    values.update(overrides)
    return AgentDefinition(**values)


def _registry() -> ExecutionAdapterRegistry:
    registry = ExecutionAdapterRegistry()
    registry.register(CallableExecutionAdapter(key="demo_adapter", runner=_success))
    return registry


def test_adapter_registry_rejects_duplicate_keys() -> None:
    registry = _registry()

    with pytest.raises(ValueError, match="already registered"):
        registry.register(CallableExecutionAdapter(key="demo_adapter", runner=_success))


def test_catalog_fails_closed_for_missing_adapter_and_required_graph() -> None:
    with pytest.raises(CatalogValidationError, match="demo_task.*adapter"):
        AgentCatalog(
            definitions=(_definition(),),
            adapters=ExecutionAdapterRegistry(),
            prompt_refs=frozenset({("demo.prompt", "1")}),
            graph_names=frozenset({"demo_graph"}),
        ).validate()

    with pytest.raises(CatalogValidationError, match="demo_task.*graph"):
        AgentCatalog(
            definitions=(_definition(),),
            adapters=_registry(),
            prompt_refs=frozenset({("demo.prompt", "1")}),
            graph_names=frozenset(),
        ).validate()


def test_catalog_allows_missing_diagnostic_graph_but_rejects_prompt_drift() -> None:
    catalog = AgentCatalog(
        definitions=(_definition(graph_reference_mode="diagnostic"),),
        adapters=_registry(),
        prompt_refs=frozenset({("demo.prompt", "1")}),
        graph_names=frozenset(),
    )
    catalog.validate()

    with pytest.raises(CatalogValidationError, match="demo_task.*prompt"):
        AgentCatalog(
            definitions=(_definition(graph_reference_mode="diagnostic"),),
            adapters=_registry(),
            prompt_refs=frozenset(),
            graph_names=frozenset(),
        ).validate()


def test_catalog_reports_legacy_and_deprecated_tasks_without_dispatching() -> None:
    definitions = (
        _definition(
            task_type="legacy_stream",
            execution_modes=("stream",),
            adapter_key=None,
            migration_state="legacy",
            graph_reference_mode="diagnostic",
        ),
        _definition(
            task_type="retired_task",
            execution_modes=(),
            adapter_key=None,
            migration_state="legacy",
            deprecated=True,
            graph_name=None,
            graph_reference_mode="diagnostic",
            prompt_name=None,
            prompt_version=None,
            run_gate_policy="none",
        ),
    )
    catalog = AgentCatalog(
        definitions=definitions,
        adapters=ExecutionAdapterRegistry(),
        prompt_refs=frozenset({("demo.prompt", "1")}),
        graph_names=frozenset(),
    )
    catalog.validate()

    with pytest.raises(ValueError, match="legacy"):
        catalog.resolve("legacy_stream", execution_mode="stream")
    with pytest.raises(ValueError, match="deprecated"):
        catalog.resolve("retired_task", execution_mode="queued")


def test_production_definitions_expose_explicit_migration_and_execution_policy() -> None:
    definitions = {item.task_type: item for item in get_agent_definitions()}

    assert definitions["interview_start"].execution_modes == ("queued", "inline")
    assert definitions["interview_start"].adapter_key == "interview_start"
    assert definitions["interview_start"].evaluation_enabled is True
    assert definitions["interview_start"].graph_reference_mode == "required"
    assert definitions["job_assets"].run_gate_policy == "worker_limit"
    assert definitions["interview_turn"].migration_state == "harness"
    assert definitions["interview_turn"].adapter_key == "interview_turn"
    assert definitions["interview_turn"].run_gate_policy == "global"
    assert definitions["voice_interview_turn"].migration_state == "harness"
    assert definitions["voice_interview_turn"].adapter_key == "voice_interview_turn"
    assert definitions["resume_generation"].execution_modes == ("session",)
    assert definitions["resume_generation"].migration_state == "harness"
    assert definitions["resume_generation"].adapter_key == "resume_generation"
    assert definitions["interview_experience_collect"].deprecated is True


def test_agent_tasks_package_exposes_no_parallel_executor_registry() -> None:
    import ai.workflows.agent_tasks as package
    import ai.workflows.agent_tasks.registry as production_registry
    from ai.workflows.agent_tasks import adapters

    assert not hasattr(package, "EXECUTORS")
    assert not hasattr(package, "_EXECUTOR_MODULES")
    assert not hasattr(production_registry, "EXECUTORS")
    assert not hasattr(adapters, "LegacyTaskExecutionAdapter")


def test_production_catalog_rejects_deprecated_history_task() -> None:
    from ai.workflows.agent_tasks.registry import (
        get_production_adapter_registry,
        get_production_catalog,
    )

    assert "interview_experience_collect" not in set(get_production_adapter_registry().keys())
    with pytest.raises(ValueError, match="deprecated"):
        get_production_catalog().resolve(
            "interview_experience_collect",
            execution_mode="queued",
        )


def test_harness_core_import_does_not_load_heavy_runtime_dependencies() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    script = """
import json
import sys
import ai.runtime.harness.catalog
import ai.runtime.harness.contracts
import ai.runtime.harness.registry
import ai.runtime.harness.drivers.session
import ai.runtime.harness.drivers.stream
blocked = sorted(
    name for name in sys.modules
    if name == 'dramatiq'
    or name.startswith('langgraph')
    or name.startswith('langfuse')
    or name.startswith('playwright')
)
print(json.dumps(blocked))
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and constant script
        [sys.executable, "-c", script],
        cwd=backend_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def test_frontend_task_type_constant_matches_backend_definitions() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "web"
        / "lib"
        / "api"
        / "agentRunTypes.ts"
    ).read_text()
    block = re.search(
        r"AGENT_RUN_TASK_TYPES\s*=\s*\[(.*?)\]\s*as const",
        source,
        re.DOTALL,
    )

    assert block is not None
    frontend_types = set(re.findall(r"'([^']+)'", block.group(1)))
    backend_types = {definition.task_type for definition in get_agent_definitions()}
    assert frontend_types == backend_types
