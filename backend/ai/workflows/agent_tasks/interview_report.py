"""面试报告 AgentRun 业务任务。"""

import asyncio
import logging

from ai.workflows.agent_tasks.types import ProgressCallback
from observability import agent_observation

logger = logging.getLogger(__name__)


async def _generate_overall_profile(
    *,
    user_id: str,
    api_config: dict | None,
) -> tuple[dict | None, str | None]:
    """Refresh the cross-session profile without letting this optional aggregate fail the report."""
    try:
        from ai.workflows.analysis.ability_service import get_ability_service

        overall = await get_ability_service().generate_overall_profile(
            user_id=user_id,
            api_config=api_config,
        )
        return overall["profile"].model_dump(), overall.get("warning")
    except Exception as exc:
        logger.warning("综合画像刷新失败: error=%s", type(exc).__name__)
        return None, "本轮报告已生成，但综合画像刷新失败，可稍后重试"


async def _generate_weakness_and_overall(
    *,
    session_id: str,
    user_id: str,
    api_config: dict | None,
) -> tuple[dict | None, str | None]:
    """Generate the weakness map and aggregate profile concurrently after the session profile exists."""
    from ai.agents.interview.interview_analysis import trigger_weakness_analysis

    weakness_task = asyncio.create_task(
        trigger_weakness_analysis(
            session_id,
            api_config,
            user_id=user_id,
            raise_on_error=True,
        ),
        name=f"interview-weakness:{session_id}",
    )
    overall_task = asyncio.create_task(
        _generate_overall_profile(user_id=user_id, api_config=api_config),
        name=f"interview-overall-profile:{session_id}",
    )
    try:
        _, overall = await asyncio.gather(weakness_task, overall_task)
        return overall
    finally:
        for task in (weakness_task, overall_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(weakness_task, overall_task, return_exceptions=True)


async def execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
    """Generate a traced report while overlapping independent post-profile model calls."""
    from app.db.repositories.interview.weakness_report_repo import get_weakness_report_repo
    from app.db.repositories.session.session_repo import SessionRepo
    from ai.agents.interview.interview_analysis import (
        build_qa_history,
        trigger_background_analysis,
    )

    session_id = payload["session_id"]
    api_config = payload.get("api_config")
    async with agent_observation(
        name="interview-report",
        agent_type="interview_report",
        user_id=user_id,
        session_id=session_id,
        run_id=payload.get("_agent_run_id"),
        input_payload={"session_id": session_id},
    ) as observation:
        await progress("loading_session")
        session_repo = SessionRepo()
        session = await session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise ValueError("会话不存在或无权访问")
        if not build_qa_history(session.messages):
            raise ValueError("该面试还没有可用于生成报告的有效问答")

        await progress("generating_profile")
        await trigger_background_analysis(
            session_id,
            api_config,
            user_id=user_id,
            raise_on_error=True,
        )
        await progress("generating_weakness")
        overall_profile, overall_warning = await _generate_weakness_and_overall(
            session_id=session_id,
            user_id=user_id,
            api_config=api_config,
        )
        await progress("saving_report")
        profile = await session_repo.get_profile(session_id)
        weakness = await get_weakness_report_repo().get_report_by_session(
            session_id,
            user_id=user_id,
        )
        result = {
            "success": True,
            "session_id": session_id,
            "profile": profile,
            "weakness": weakness,
            "overall_profile": overall_profile,
            "warning": overall_warning,
        }
        observation.set_output({
            "has_profile": bool(profile),
            "has_weakness": bool(weakness),
            "has_overall_profile": bool(overall_profile),
            "has_warning": bool(overall_warning),
        })
        return result
