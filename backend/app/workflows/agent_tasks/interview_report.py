"""面试报告 AgentRun 业务任务。"""

import logging

from app.workflows.agent_tasks.types import ProgressCallback

logger = logging.getLogger(__name__)


async def execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
    """执行面试报告生成任务：加载会话、触发画像与短板分析、聚合综合画像。"""
    from app.infrastructure.db.repositories.interview.weakness_report_repo import get_weakness_report_repo
    from app.infrastructure.db.repositories.session.session_repo import SessionRepo
    from app.agents.interview.interview_analysis import (
        build_qa_history,
        trigger_background_analysis,
        trigger_weakness_analysis,
    )

    session_id = payload["session_id"]
    api_config = payload.get("api_config")
    await progress("loading_session")
    session = await SessionRepo().get_session(session_id, user_id=user_id)
    if not session:
        raise ValueError("会话不存在或无权访问")
    if not build_qa_history(session.messages):
        raise ValueError("该面试还没有可用于生成报告的有效问答")
    await progress("generating_profile")
    await trigger_background_analysis(session_id, api_config, user_id=user_id, raise_on_error=True)
    await progress("generating_weakness")
    await trigger_weakness_analysis(session_id, api_config, user_id=user_id, raise_on_error=True)
    await progress("saving_report")
    overall_profile = None
    overall_warning = None
    try:
        from app.workflows.analysis.ability_service import get_ability_service

        overall = await get_ability_service().generate_overall_profile(user_id=user_id, api_config=api_config)
        overall_profile = overall["profile"].model_dump()
        overall_warning = overall.get("warning")
    except Exception as exc:
        # 综合画像是跨场聚合，不应阻断本轮画像与短板报告落库。
        logger.warning("综合画像刷新失败: session=%s error=%s", session_id, exc)
        overall_warning = "本轮报告已生成，但综合画像刷新失败，可稍后重试"
    profile = await SessionRepo().get_profile(session_id)
    weakness = await get_weakness_report_repo().get_report_by_session(session_id, user_id=user_id)
    return {
        "success": True,
        "session_id": session_id,
        "profile": profile,
        "weakness": weakness,
        "overall_profile": overall_profile,
        "warning": overall_warning,
    }
