"""面试报告 AgentRun 业务任务。"""

from ai.workflows.agent_tasks.types import ProgressCallback
from observability import agent_observation


async def execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
    """Generate a recoverable report and checkpoint completed evidence chunks encrypted at rest."""
    from ai.agents.interview.interview_analysis import build_qa_history
    from ai.workflows.interview.completion import generate_session_reports
    from app.db.repositories.interview.weakness_report_repo import (
        get_weakness_report_repo,
    )
    from app.db.repositories.session.session_repo import SessionRepo

    session_id = payload["session_id"]
    api_config = payload.get("api_config")
    run_id = str(payload.get("_agent_run_id") or "")
    async with agent_observation(
        name="interview-report",
        agent_type="interview_report",
        user_id=user_id,
        session_id=session_id,
        run_id=run_id or None,
        input_payload={"session_id": session_id},
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
                """Persist only encrypted evidence progress for the current owner-scoped run."""
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
        )
        await progress("saving_report")
        profile = await session_repo.get_profile(session_id, user_id=user_id)
        weakness = await get_weakness_report_repo().get_report_by_session(
            session_id,
            user_id=user_id,
        )
        result = {
            "success": True,
            "session_id": session_id,
            "profile": profile,
            "weakness": weakness,
        }
        observation.set_output({
            "has_profile": bool(profile),
            "has_weakness": bool(weakness),
        })
        return result
