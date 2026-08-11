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


@dataclass(frozen=True, slots=True)
class LegacyTaskExecutionAdapter:
    """把 queued/inline 旧 executor 包装为 Harness adapter。"""

    key: str
    executor: TaskRunner

    async def run(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """委托旧业务 executor；AgentRun 终态仍由 driver 持有。"""

        if context.environment != "production":
            raise ValueError(f"adapter is not enabled for evaluation: {self.key}")
        return await self.executor(payload, context.user_id, context.mark_progress)


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

    from ai.workflows.agent_tasks.interview_start import execute_interview_start

    return await execute_interview_start(payload, user_id, progress)


async def _run_interview_start_evaluation(
    payload: dict[str, Any],
    context: ExecutionContext,
) -> ExecutionResult:
    """使用隔离身份调用真实 planner，明确禁止正式会话持久化。"""

    from ai.agents.interview.interview_planner import generate_interview_plan

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
