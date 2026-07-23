"""简历优化 AgentRun 业务任务。"""

from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.agent_tasks.types import DeferredExecutionResult, ProgressCallback


async def execute_resume_optimize(payload: dict, user_id: str, progress: ProgressCallback) -> dict | DeferredExecutionResult:
    """执行简历优化任务：运行优化 pipeline 并持久化结果。"""
    from app.db.repositories.resume.resume_repo import get_resume_repo
    from ai.agents.resume.result_mapper import pipeline_to_optimize_result
    from ai.agents.resume.resume_orchestrator import run_pipeline
    from ai.agents.resume.resume_review import initialize_review

    await progress("preparing")
    agent_run_id = payload.get("_agent_run_id")
    resume_repo = get_resume_repo()
    if agent_run_id:
        existing = await resume_repo.get_result_by_agent_run_id(agent_run_id, user_id)
        if existing:
            public_result = pipeline_to_optimize_result(existing["result_data"])
            return {
                "success": True,
                "result_id": existing["id"],
                "result": public_result.model_dump(),
                "warnings": existing["result_data"].get("errors") or [],
            }
    session_ids = payload.get("session_ids") or []
    if len(session_ids) > 3:
        raise ValueError("最多只能选择 3 个面试记录")
    await progress("optimizing")
    result = await run_pipeline(
        resume_content=payload["resume_content"],
        job_description=payload["job_description"],
        session_ids=session_ids,
        include_profile=bool(payload.get("include_overall_profile", False)),
        user_id=user_id,
        api_config=payload.get("api_config"),
        run_id=agent_run_id,
        mode=str(payload.get("mode") or "balanced"),
    )
    result = initialize_review(result)
    await progress("saving_result")

    async def persist_result(session: AsyncSession | None = None) -> dict:
        result_id = await resume_repo.save_result(
            user_id=user_id,
            result_type="optimize",
            resume_content=payload["resume_content"],
            result_data=result,
            job_description=payload.get("job_description"),
            session_ids=session_ids,
            include_profile=bool(payload.get("include_overall_profile", False)),
            agent_run_id=agent_run_id,
            session=session,
        )
        public_result = pipeline_to_optimize_result(result)
        return {
            "success": True,
            "result_id": result_id,
            "result": public_result.model_dump(),
            "warnings": result.get("errors") or [],
        }

    if agent_run_id:
        return DeferredExecutionResult(persist=persist_result)
    return await persist_result()
