"""面试完成与报告编排用例。

把“会话完成、问答归档、报告任务入队/降级、总结流程”从 agent 实现层
移到 workflow 层，避免 agents 反向依赖 runtime agent_runs 基础设施。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ai.runtime.agent_runs.outbox import dispatch_pending_outbox
from ai.workflows.agent_runs.queue.submission import enqueue_agent_run
from ai.runtime.agent_runs.service import AgentRunService, task_queue_enabled
from ai.runtime.execution.background import create_background_task
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_REPORT

logger = logging.getLogger(__name__)


async def handle_interview_complete(
    session_id: str,
    api_config: dict[str, Any] | None = None,
    trigger_analysis: bool = True,
    user_id: str = "default_user",
) -> None:
    """处理面试完成：更新状态、归档问答，并按配置触发报告生成。

    Args:
        session_id: 目标会话标识。
        api_config: 模型 API 配置，可选。
        trigger_analysis: 是否触发报告分析。
        user_id: 当前用户标识。
    """
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
            from app.db.repositories.interview.question_archive_repo import (
                get_question_archive_repo,
            )

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
    """优先使用可恢复 AgentRun 生成报告；队列不可用或失败时降级本地后台任务。

    Args:
        session_id: 目标会话标识。
        api_config: 模型 API 配置，可选。
        user_id: 当前用户标识。
    """
    queued = False
    try:
        if task_queue_enabled():
            run_service = AgentRunService()
            run, created = await run_service.create_or_get(
                user_id=user_id,
                task_type=TASK_TYPE_INTERVIEW_REPORT,
                payload={"session_id": session_id, "api_config": api_config},
                idempotency_key=f"auto-report:{session_id}",
                session_id=session_id,
            )
            if run.status in {"failed", "cancelled"}:
                retried = await run_service.retry(run.id, user_id)
                run = retried or run
            if created or run.status in {"queued", "retrying"}:
                dispatched, failed = await dispatch_pending_outbox(
                    limit=50,
                    enqueue_fn=enqueue_agent_run,
                )
                if failed:
                    logger.warning(
                        "[InterviewComplete] 报告任务 Outbox 投递失败: session=%s success=%s failed=%s",
                        session_id,
                        dispatched,
                        failed,
                    )
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
    report_checkpoint: Mapping[str, Any] | None = None,
    checkpoint_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    """触发单场面试报告分析任务（可带报告检查点与回调）。

    Args:
        session_id: 目标会话标识。
        api_config: 模型 API 配置，可选。
        user_id: 当前用户标识。
        raise_on_error: 失败时是否抛出异常。
        report_checkpoint: 报告生成检查点，可选。
        checkpoint_callback: 检查点保存回调，可选。
    """
    from ai.agents.interview.interview_analysis import trigger_session_report_analysis

    optional: dict[str, Any] = {}
    if report_checkpoint is not None:
        optional["report_checkpoint"] = report_checkpoint
    if checkpoint_callback is not None:
        optional["checkpoint_callback"] = checkpoint_callback
    await trigger_session_report_analysis(
        session_id,
        api_config,
        user_id=user_id,
        raise_on_error=raise_on_error,
        **optional,
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
    """面试结束处理：完成会话并触发分析，返回结束语。

    Args:
        session_id: 目标会话标识。
        messages: 会话消息列表。
        mode: 面试模式。
        api_config: 模型 API 配置，可选。
        trigger_analysis: 是否触发分析。
        memory_context: 记忆上下文，可选。
        user_id: 当前用户标识。
    """
    from app.domain.interview_rounds import INTERVIEW_CLOSING_MESSAGE

    _ = (messages, mode, memory_context)
    await handle_interview_complete(
        session_id=session_id,
        api_config=api_config,
        trigger_analysis=trigger_analysis,
        user_id=user_id,
    )
    return INTERVIEW_CLOSING_MESSAGE
