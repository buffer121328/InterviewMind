"""面试完成与报告编排用例。

把“会话完成、问答归档、报告任务入队/降级、总结流程”从 agent 实现层
移到 workflow 层，避免 agents 反向依赖 runtime agent_runs 基础设施。
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.agent_runs import TASK_TYPE_INTERVIEW_REPORT
from app.infrastructure.db.repositories.session.session_repo import SessionRepo
from app.infrastructure.runtime.agent_runs.dispatcher import enqueue_agent_run
from app.infrastructure.runtime.agent_runs.service import AgentRunService, task_queue_enabled
from app.infrastructure.runtime.background_tasks import create_background_task

logger = logging.getLogger(__name__)


async def handle_interview_complete(
    session_id: str,
    api_config: dict[str, Any] | None = None,
    trigger_analysis: bool = True,
    user_id: str = "default_user",
) -> None:
    """处理面试完成：更新状态、归档问答，并按配置触发报告生成。"""
    try:
        if not session_id:
            logger.warning("[InterviewComplete] session_id 缺失")
            return

        session_repo = SessionRepo()
        await session_repo.update_session(
            session_id=session_id,
            status="completed",
            user_id=user_id,
        )
        logger.info("[InterviewComplete] 会话 %s 状态已更新为 completed (user_id=%s)", session_id, user_id)

        # 归档真实问答；失败不阻断完成状态和后续画像分析。
        try:
            from app.infrastructure.db.repositories.interview.question_archive_repo import get_question_archive_repo

            archived = await get_question_archive_repo().archive_session(session_id, user_id)
            logger.info("[InterviewComplete] 问答归档完成: session=%s, %s", session_id, archived)
        except Exception as archive_error:  # noqa: BLE001 - 完成状态不应被归档失败阻断
            logger.warning(
                "[InterviewComplete] 问答归档失败: session=%s, error=%s",
                session_id,
                archive_error,
                exc_info=True,
            )

        if trigger_analysis:
            await queue_or_run_session_reports(session_id=session_id, api_config=api_config, user_id=user_id)

    except Exception as exc:  # noqa: BLE001 - 入口兜底，避免后台任务吞掉上下文
        logger.error("[InterviewComplete] 处理面试完成失败: %s", exc, exc_info=True)


async def queue_or_run_session_reports(
    *,
    session_id: str,
    api_config: dict[str, Any] | None = None,
    user_id: str = "default_user",
) -> None:
    """优先使用可恢复 AgentRun 生成报告；队列不可用或失败时降级本地后台任务。"""
    queued = False
    try:
        if task_queue_enabled():
            run_service = AgentRunService()
            run, created = await run_service.create_or_get(
                user_id=user_id,
                task_type=TASK_TYPE_INTERVIEW_REPORT,
                payload={"session_id": session_id, "api_config": api_config},
                idempotency_key=f"auto-report:{session_id}",
            )
            if run.status in {"failed", "cancelled"}:
                retried = await run_service.retry(run.id, user_id)
                run = retried or run
            if created or run.status in {"queued", "retrying"}:
                enqueue_agent_run(run.id)
            queued = run.status in {"queued", "retrying", "running", "succeeded"}
            logger.info("[InterviewComplete] 已创建报告任务: session=%s run=%s", session_id, run.id)
    except Exception as queue_error:  # noqa: BLE001 - 需要降级到本地后台任务
        logger.warning("[InterviewComplete] 报告任务入队失败，降级为本地后台任务: %s", queue_error)

    if not queued:
        create_background_task(
            generate_session_reports(session_id, api_config, user_id=user_id),
            name=f"interview-reports:{session_id}",
        )


async def generate_session_reports(
    session_id: str,
    api_config: dict[str, Any] | None = None,
    user_id: str = "default_user",
    *,
    raise_on_error: bool = False,
) -> None:
    """顺序生成本轮画像和短板，保证短板分析可以复用画像。"""
    from app.agents.interview.interview_analysis import trigger_background_analysis, trigger_weakness_analysis

    await trigger_background_analysis(
        session_id,
        api_config,
        user_id=user_id,
        raise_on_error=raise_on_error,
    )
    await trigger_weakness_analysis(
        session_id,
        api_config,
        user_id=user_id,
        raise_on_error=raise_on_error,
    )


async def process_interview_summary(
    session_id: str,
    messages: list[Any],
    mode: str = "mock",
    api_config: dict[str, Any] | None = None,
    trigger_analysis: bool = True,
    memory_context: str | None = None,
    user_id: str = "default_user",
) -> str:
    """执行完整总结流程：生成总结 -> 更新会话完成状态 -> 触发报告分析。"""
    from app.agents.interview.interview_analysis import generate_interview_summary

    summary = await generate_interview_summary(messages, mode, api_config, memory_context)
    await handle_interview_complete(
        session_id=session_id,
        api_config=api_config,
        trigger_analysis=trigger_analysis,
        user_id=user_id,
    )
    return summary
