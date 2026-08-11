"""默认 Eval Harness 生产 Agent 适配器，所有重型依赖均延迟导入。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from evaluation.extractors.runtime import EvaluationTraceCollector
from evaluation.runners.base import (
    AgentAdapterRegistry,
    EvaluationExecutionContext,
)


async def _run_interview_planner(
    payload: dict[str, Any],
    context: EvaluationExecutionContext,
    trace: EvaluationTraceCollector,
) -> Any:
    """通过 EvaluationDriver 调用 `interview_start` production adapter。"""

    from ai.runtime.harness.contracts import DeferredExecutionResult
    from ai.workflows.agent_tasks.registry import get_evaluation_driver
    from app.domain.agent_runs import TASK_TYPE_INTERVIEW_START

    trace.start_step("planning")
    try:
        result = await get_evaluation_driver().run(
            task_type=TASK_TYPE_INTERVIEW_START,
            payload=payload,
            run_id=context.run_id,
            user_id=context.evaluation_user_id,
            session_id=context.evaluation_session_id,
            memory_namespace=context.evaluation_memory_namespace,
            artifact_namespace=context.evaluation_artifact_namespace,
        )
        if isinstance(result, DeferredExecutionResult):
            raise TypeError("evaluation adapter cannot return deferred persistence")
        trace.finish_step(
            "planning",
            summary={"question_count": len(result), "saved_to_db": False},
        )
        return result
    except Exception:
        trace.finish_step("planning", status="failed")
        raise


async def _run_interview_turn(
    payload: dict[str, Any],
    context: EvaluationExecutionContext,
    trace: EvaluationTraceCollector,
) -> Any:
    """调用真实 InterviewRuntime responder，使用评测身份且不执行会话持久化。"""

    from ai.agents.interview.interview_graph import node_responder

    state = dict(payload)
    state.update(
        {
            "user_id": context.evaluation_user_id,
            "session_id": context.evaluation_session_id,
            "run_id": context.run_id,
        }
    )
    trace.start_step("interview_turn")
    try:
        result = await node_responder(state)
        safe_result = _normalize_runtime_value(result)
        trace.finish_step("interview_turn")
        return safe_result
    except Exception:
        trace.finish_step("interview_turn", status="failed")
        raise


async def _run_resume_optimizer(
    payload: dict[str, Any],
    context: EvaluationExecutionContext,
    trace: EvaluationTraceCollector,
) -> Any:
    """调用真实六阶段简历优化流水线，不保存到正式简历结果表。"""

    from ai.agents.resume.resume_orchestrator import run_pipeline

    trace.start_step("resume_optimize")
    try:
        result = await run_pipeline(
            resume_content=str(payload.get("resume_content") or payload.get("resume") or ""),
            job_description=str(payload.get("job_description") or ""),
            user_id=context.evaluation_user_id,
            api_config=dict(payload.get("api_config") or {}),
            session_ids=[],
            include_profile=False,
            run_id=context.run_id,
            mode=str(payload.get("mode") or "balanced"),
            precomputed_jd_analysis=payload.get("precomputed_jd_analysis"),
        )
        trace.finish_step(
            "resume_optimize",
            summary={
                "change_count": len(result.get("change_items") or []),
                "confirmation_count": len(result.get("confirmation_items") or []),
            },
        )
        return _normalize_runtime_value(result)
    except Exception:
        trace.finish_step("resume_optimize", status="failed")
        raise


async def _run_resume_analyzer(
    payload: dict[str, Any],
    context: EvaluationExecutionContext,
    trace: EvaluationTraceCollector,
) -> Any:
    """调用真实简历分析图，禁止读取正式面试会话和用户画像。"""

    from ai.agents.resume.resume_analyzer_graph import analyze_resume

    trace.start_step("resume_analyze")
    try:
        result = await analyze_resume(
            resume_content=str(payload.get("resume_content") or payload.get("resume") or ""),
            job_description=str(payload.get("job_description") or ""),
            session_ids=[],
            user_id=context.evaluation_user_id,
            api_config=dict(payload.get("api_config") or {}),
            call_metadata={
                "environment": "evaluation",
                "evaluation_run_id": context.run_id,
            },
        )
        trace.finish_step("resume_analyze")
        return _normalize_runtime_value(result)
    except Exception:
        trace.finish_step("resume_analyze", status="failed")
        raise


class EvaluationConfigurationError(ValueError):
    """评测目录或 case adapter 配置不一致。"""


CaseAdapterRunner = Callable[
    [dict[str, Any], EvaluationExecutionContext, EvaluationTraceCollector, Any],
    Awaitable[Any],
]


@dataclass(frozen=True, slots=True)
class EvaluationCaseAdapterSpec:
    """把稳定 capability 名称映射到一个明确 production task。"""

    task_type: str
    runner: CaseAdapterRunner
    required_trace_categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogEvaluationEntry:
    """Catalog、production adapter 与 case adapter 的只读关联。"""

    capability_name: str
    task_type: str
    definition: Any
    production_adapter_key: str
    production_adapter: Any
    case_adapter: EvaluationCaseAdapterSpec


class CatalogEvaluationView:
    """从 Harness Catalog 派生 fail-closed 的 evaluation view。"""

    def __init__(self, *, catalog: Any = None, case_adapters: dict[str, EvaluationCaseAdapterSpec] | None = None) -> None:
        if catalog is None:
            from ai.workflows.agent_tasks.registry import get_production_catalog

            catalog = get_production_catalog()
        self._catalog = catalog
        self._case_adapters = dict(case_adapters or {
            "interview_planner": EvaluationCaseAdapterSpec(
                task_type="interview_start",
                runner=_run_interview_planner_case,
                required_trace_categories=("runtime", "model"),
            ),
        })

    def resolve(self, capability_name: str) -> CatalogEvaluationEntry:
        """解析 capability；缺 case adapter、policy 或 Prompt 时拒绝执行。"""

        try:
            case_adapter = self._case_adapters[capability_name]
        except KeyError as exc:
            raise EvaluationConfigurationError(
                f"evaluation case adapter is not registered: {capability_name}"
            ) from exc
        try:
            catalog_entry = self._catalog.resolve(
                case_adapter.task_type,
                execution_mode="evaluation",
                environment="evaluation",
            )
        except (KeyError, ValueError) as exc:
            raise EvaluationConfigurationError(
                f"evaluation task is not eligible: {case_adapter.task_type}"
            ) from exc
        definition = catalog_entry.definition
        adapter_key = definition.adapter_key
        if not adapter_key or adapter_key != getattr(catalog_entry.adapter, "key", None):
            raise EvaluationConfigurationError(
                f"evaluation adapter identity mismatch: {case_adapter.task_type}"
            )
        if (definition.prompt_name is None) != (definition.prompt_version is None):
            raise EvaluationConfigurationError(
                f"evaluation prompt identity is incomplete: {case_adapter.task_type}"
            )
        return CatalogEvaluationEntry(
            capability_name=capability_name,
            task_type=case_adapter.task_type,
            definition=definition,
            production_adapter_key=adapter_key,
            production_adapter=catalog_entry.adapter,
            case_adapter=case_adapter,
        )

    def capabilities(self) -> tuple[str, ...]:
        """返回显式 case adapter capability，不暴露案例正文。"""

        return tuple(sorted(self._case_adapters))


class CatalogEvaluationAdapter:
    """AgentEvalRunner 使用的 Catalog-derived adapter facade。"""

    def __init__(self, *, capability_name: str, view: CatalogEvaluationView) -> None:
        self.name = capability_name
        self._view = view

    def _entry(self) -> CatalogEvaluationEntry:
        return self._view.resolve(self.name)

    @property
    def version(self) -> str:
        try:
            return str(self._entry().definition.version)
        except EvaluationConfigurationError:
            return "unresolved"

    @property
    def prompt_name(self) -> str | None:
        return self._entry().definition.prompt_name

    @property
    def prompt_version(self) -> str | None:
        return self._entry().definition.prompt_version

    @property
    def task_type(self) -> str:
        return self._entry().task_type

    @property
    def production_adapter_key(self) -> str:
        return self._entry().production_adapter_key

    @property
    def catalog_identity(self) -> str:
        entry = self._entry()
        prompt = (
            f"{entry.definition.prompt_name}@{entry.definition.prompt_version}"
            if entry.definition.prompt_name
            else "none"
        )
        return (
            f"{entry.task_type}:{entry.definition.name}@{entry.definition.version}:"
            f"{entry.production_adapter_key}:{prompt}"
        )

    @property
    def required_trace_categories(self) -> tuple[str, ...]:
        return self._entry().case_adapter.required_trace_categories

    async def run(
        self,
        payload: dict[str, Any],
        context: EvaluationExecutionContext,
        trace: EvaluationTraceCollector,
    ) -> Any:
        entry = self._entry()
        return await entry.case_adapter.runner(
            payload,
            context,
            trace,
            entry.production_adapter,
        )


async def _run_interview_planner_case(
    payload: dict[str, Any],
    context: EvaluationExecutionContext,
    trace: EvaluationTraceCollector,
    production_adapter: Any,
) -> Any:
    """通过同一 production adapter key 执行 planner case。"""

    if getattr(production_adapter, "key", None) != "interview_start":
        raise EvaluationConfigurationError("interview planner production adapter drifted")
    return await _run_interview_planner(payload, context, trace)


def build_production_agent_registry() -> AgentAdapterRegistry:
    """构造 Catalog-derived evaluation compatibility view。"""

    view = CatalogEvaluationView()
    registry = AgentAdapterRegistry()
    for capability_name in (
        "interview_planner",
        "interview_scoring",
        "interview_turn",
        "resume_analyzer",
        "resume_optimizer",
    ):
        # 兼容旧 dataset capability 名称，但所有实际执行都重新解析 Catalog；
        # 未注册 case adapter 的 capability 只会 fail closed，不回退旧函数。
        registry.register(
            CatalogEvaluationAdapter(capability_name=capability_name, view=view)
        )
    return registry


def _normalize_runtime_value(value: Any) -> Any:
    """把 Pydantic、LangChain Message 和容器转换为 JSON 可序列化结构。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _normalize_runtime_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_runtime_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _normalize_runtime_value(model_dump(mode="json"))
    content = getattr(value, "content", None)
    if content is not None:
        return {
            "role": getattr(value, "type", None) or getattr(value, "role", None),
            "content": _normalize_runtime_value(content),
        }
    return str(value)
