"""面试报告 AgentRun 业务任务。"""

from ai.workflows.agent_runs.contracts import ProgressCallback
from app.domain.interview_report_modes import normalize_report_mode, normalize_report_source_version
from observability import agent_observation


async def execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
    """执行面试报告相关后端逻辑。"""
    from ai.agents.interview.interview_analysis import build_qa_history
    from ai.workflows.interview.lifecycle.completion import generate_session_reports
    from app.db.repositories.interview.weakness_report_repo import (
        get_weakness_report_repo,
    )
    from app.db.repositories.session.session_repo import SessionRepo

    session_id = payload["session_id"]
    api_config = payload.get("api_config")
    report_mode = normalize_report_mode(payload.get("report_mode"))
    report_source_version = normalize_report_source_version(payload.get("report_source_version"))
    run_id = str(payload.get("_agent_run_id") or "")
    async with agent_observation(
        name="interview-report",
        agent_type="interview_report",
        user_id=user_id,
        session_id=session_id,
        run_id=run_id or None,
        input_payload={
            "session_id": session_id,
            "report_mode": report_mode.value,
            "report_source_version": report_source_version,
        },
    ) as observation:
        await progress("loading_session")
        session_repo = SessionRepo()
        session = await session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise ValueError("会话不存在或无权访问")
        if not build_qa_history(session.messages):
            raise ValueError("该面试还没有可用于生成报告的有效问答")

        await progress("generating_reports")
        report_checkpoint = None
        checkpoint_callback = None
        if run_id:
            from ai.runtime.agent_runs.service import AgentRunService

            run_service = AgentRunService()
            report_checkpoint = await run_service.load_checkpoint(
                run_id,
                user_id,
                "generating_reports",
            )

            async def checkpoint_callback(checkpoint: dict) -> None:
                """处理检查点回调相关后端逻辑。"""
                await run_service.save_checkpoint(
                    run_id,
                    "generating_reports",
                    checkpoint,
                    user_id=user_id,
                )

        await generate_session_reports(
            session_id,
            api_config,
            user_id=user_id,
            raise_on_error=True,
            report_checkpoint=report_checkpoint,
            checkpoint_callback=checkpoint_callback,
            report_mode=report_mode.value,
            report_source_version=report_source_version,
        )
        await progress("saving_report")
        profile = None
        weakness = None
        if report_mode.value == "deep":
            profile = await session_repo.get_profile(session_id, user_id=user_id)
            weakness = await get_weakness_report_repo().get_report_by_session(
                session_id,
                user_id=user_id,
            )
        result = {
            "success": True,
            "session_id": session_id,
            "report_mode": report_mode.value,
            "report_source_version": report_source_version,
            "profile": profile,
            "weakness": weakness,
        }
        observation.set_output({
            "report_mode": report_mode.value,
            "report_source_version": report_source_version,
            "has_profile": bool(profile),
            "has_weakness": bool(weakness),
        })
        return result
