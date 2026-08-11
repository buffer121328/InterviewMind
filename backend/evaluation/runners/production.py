"""默认 Eval Harness 生产 Agent 适配器，所有重型依赖均延迟导入。"""

from __future__ import annotations

from typing import Any

from evaluation.extractors.runtime import EvaluationTraceCollector
from evaluation.runners.base import (
    AgentAdapterRegistry,
    CallableAgentAdapter,
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


def build_production_agent_registry() -> AgentAdapterRegistry:
    """注册首批真实生产入口：面试规划/追问与简历分析/优化。"""

    from app.domain.agent_definitions import get_agent_definition
    from app.domain.agent_runs import TASK_TYPE_INTERVIEW_START

    interview_start = get_agent_definition(TASK_TYPE_INTERVIEW_START)
    registry = AgentAdapterRegistry()
    registry.register(
        CallableAgentAdapter(
            name="interview_planner",
            version=interview_start.version,
            entrypoint=_run_interview_planner,
            prompt_name=interview_start.prompt_name,
            prompt_version=interview_start.prompt_version,
        )
    )
    registry.register(
        CallableAgentAdapter(
            name="interview_turn",
            version="production",
            entrypoint=_run_interview_turn,
        )
    )
    registry.register(
        CallableAgentAdapter(
            name="interview_scoring",
            version="production",
            entrypoint=_run_interview_turn,
        )
    )
    registry.register(
        CallableAgentAdapter(
            name="resume_optimizer",
            version="production",
            entrypoint=_run_resume_optimizer,
        )
    )
    registry.register(
        CallableAgentAdapter(
            name="resume_analyzer",
            version="production",
            entrypoint=_run_resume_analyzer,
        )
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
