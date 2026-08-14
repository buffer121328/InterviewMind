"""现有生产任务到 Agent Harness 的延迟执行适配器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ai.runtime.harness.contracts import (
    DeferredExecutionResult,
    ExecutionAdapter,
    ExecutionContext,
    ExecutionResult,
    ProgressCallback,
)

TaskRunner = Callable[
    [dict[str, Any], str, ProgressCallback],
    Awaitable[ExecutionResult],
]
EvaluationRunner = Callable[
    [dict[str, Any], ExecutionContext],
    Awaitable[ExecutionResult],
]


class ProductionTaskExecutionAdapter:
    """把一个显式生产任务入口包装为 Harness adapter。"""

    __slots__ = ("executor", "key")

    def __init__(self, *, key: str, executor: TaskRunner) -> None:
        self.key = key
        self.executor = executor

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """延迟委托业务 executor；AgentRun 终态仍由 driver 持有。"""

        if context.environment != "production":
            raise ValueError(f"adapter is not enabled for evaluation: {self.key}")
        return await self.executor(payload, context.user_id, context.mark_progress)


class ResumeOptimizeExecutionAdapter(ProductionTaskExecutionAdapter):
    """简历优化任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(key="resume_optimize", executor=executor or _run_resume_optimize)


class ResumeWorkspaceExecutionAdapter(ProductionTaskExecutionAdapter):
    """简历工作台任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(key="resume_workspace", executor=executor or _run_resume_workspace)


class InterviewReportExecutionAdapter(ProductionTaskExecutionAdapter):
    """面试报告任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(key="interview_report", executor=executor or _run_interview_report)


class AbilityProfileExecutionAdapter(ProductionTaskExecutionAdapter):
    """能力画像任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(key="ability_profile", executor=executor or _run_ability_profile)


class JobRecommendationCaptureExecutionAdapter(ProductionTaskExecutionAdapter):
    """岗位推荐导入任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(
            key="job_recommendation_capture",
            executor=executor or _run_job_recommendation_capture,
        )


class JobAssetsExecutionAdapter(ProductionTaskExecutionAdapter):
    """岗位资产任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(key="job_assets", executor=executor or _run_job_assets)


class InterviewEvaluationDraftExecutionAdapter(ProductionTaskExecutionAdapter):
    """历史面试评测草稿任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(
            key="interview_evaluation_draft",
            executor=executor or _run_interview_evaluation_draft,
        )


class EvaluationSuiteExecutionAdapter(ProductionTaskExecutionAdapter):
    """评测套件编排任务的显式 production adapter。"""

    def __init__(self, *, executor: TaskRunner | None = None) -> None:
        super().__init__(key="evaluation_suite", executor=executor or _run_evaluation_suite)


async def _run_resume_optimize(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.resume.optimize import execute_resume_optimize

    return await execute_resume_optimize(payload, user_id, progress)


async def _run_resume_workspace(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.resume.workspace import execute_resume_workspace

    return await execute_resume_workspace(payload, user_id, progress)


async def _run_interview_report(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.interview.report import execute_interview_report

    return await execute_interview_report(payload, user_id, progress)


async def _run_ability_profile(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.analysis.ability_profile import execute_ability_profile

    return await execute_ability_profile(payload, user_id, progress)


async def _run_job_recommendation_capture(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.jobs.recommendation_capture import (
        execute_job_recommendation_capture,
    )

    return await execute_job_recommendation_capture(payload, user_id, progress)


async def _run_job_assets(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.jobs.assets import execute_job_assets

    return await execute_job_assets(payload, user_id, progress)


async def _run_interview_evaluation_draft(
    payload: dict[str, Any], user_id: str, progress: ProgressCallback
) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.evaluation.interview_history_draft import (
        execute_interview_evaluation_draft,
    )

    return await execute_interview_evaluation_draft(payload, user_id, progress)


async def _run_evaluation_suite(payload: dict[str, Any], user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from ai.workflows.agent_runs.tasks.evaluation.evaluation_suite import execute_evaluation_suite

    return await execute_evaluation_suite(payload, user_id, progress)


class InterviewTurnExecutionAdapter:
    """`interview_turn` 的 stream/evaluation 同源执行适配器。"""

    key = "interview_turn"

    def __init__(self, *, evaluation_runner: EvaluationRunner | None = None) -> None:
        self._evaluation_runner = evaluation_runner or _run_interview_turn_evaluation

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """评测时使用隔离身份；生产请求仍必须由 StreamDriver 持有。"""

        if context.environment == "evaluation":
            return await self._evaluation_runner(payload, context)
        raise RuntimeError("stream task must be dispatched through StreamDriver")


class InterviewStartExecutionAdapter:
    """`interview_start` 的 production/evaluation 同源执行适配器。"""

    key = "interview_start"

    def __init__(
        self,
        *,
        production_runner: TaskRunner | None = None,
        evaluation_runner: EvaluationRunner | None = None,
    ) -> None:
        self._production_runner = production_runner or _run_interview_start_production
        self._evaluation_runner = evaluation_runner or _run_interview_start_evaluation

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """按 execution context 选择保存策略，不复制 Agent/Prompt 版本事实。"""

        if context.environment == "evaluation":
            return await self._evaluation_runner(payload, context)
        return await self._production_runner(
            payload,
            context.user_id,
            context.mark_progress,
        )


@dataclass(frozen=True, slots=True)
class ObservedExecutionAdapter:
    """为任意 production adapter 添加统一、可降级的根 observation。"""

    adapter: ExecutionAdapter

    @property
    def key(self) -> str:
        """透传稳定 adapter key。"""

        return self.adapter.key

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """延迟导入观测依赖并仅记录有界 task metadata。"""

        from observability import agent_observation

        async with agent_observation(
            name=f"agent-run-{context.task_type}",
            agent_type=context.task_type,
            user_id=context.user_id,
            session_id=context.session_id,
            run_id=context.run_id,
            input_payload={"task_type": context.task_type},
        ) as observation:
            result = await self.adapter.run(payload, context)
            observation.set_output(
                {"deferred_persistence": isinstance(result, DeferredExecutionResult)}
            )
            return result


async def _run_interview_start_production(
    payload: dict[str, Any],
    user_id: str,
    progress: ProgressCallback,
) -> ExecutionResult:
    """延迟导入并执行现有 session/Graph 生产入口。"""

    from ai.workflows.agent_runs.tasks.interview.start import execute_interview_start

    return await execute_interview_start(payload, user_id, progress)


async def _run_interview_start_evaluation(
    payload: dict[str, Any],
    context: ExecutionContext,
) -> ExecutionResult:
    """使用隔离身份调用真实 planner，明确禁止正式会话持久化。"""

    from ai.agents.interview.planning.planner import generate_interview_plan

    return await generate_interview_plan(
        resume=str(payload.get("resume") or payload.get("resume_content") or ""),
        job_description=str(payload.get("job_description") or ""),
        company_info=str(payload.get("company_info") or ""),
        max_questions=int(payload.get("max_questions") or 5),
        api_config=dict(payload.get("api_config") or {}),
        round_type=str(payload.get("round_type") or "tech_initial"),
        round_index=int(payload.get("round_index") or 1),
        previous_profile=payload.get("previous_profile"),
        previous_questions=list(payload.get("previous_questions") or []),
        output_format=str(payload.get("output_format") or "full"),
        session_id=context.session_id,
        save_to_db=False,
        generate_hints=bool(payload.get("generate_hints", False)),
        weakness_report=payload.get("weakness_report"),
        retrieval_context=payload.get("retrieval_context"),
        memory_context=str(payload.get("memory_context") or ""),
        previous_summary=payload.get("previous_summary"),
        owner_id=context.user_id,
        cache_scope=context.session_id or context.run_id or "",
    )


async def _run_interview_turn_evaluation(
    payload: dict[str, Any],
    context: ExecutionContext,
) -> ExecutionResult:
    """在 evaluation identity 下调用真实 InterviewRuntime，不写源 session。"""

    from ai.agents.interview.interview_graph import node_responder

    state = dict(payload)
    state.update(
        {
            "user_id": context.user_id,
            "session_id": context.session_id,
            "run_id": context.run_id,
            # 历史案例必须显式关闭正式 memory 注入；工具读取也只会命中 eval identity。
            "memory_context": "",
            "memory_items": [],
        }
    )
    result = await node_responder(state)
    return _normalize_runtime_value(result)


def _normalize_runtime_value(value: Any) -> Any:
    """把消息、Pydantic 和容器收敛为 AgentRun 可序列化结果。"""

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
