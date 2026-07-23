"""岗位投递资产 AgentRun 业务任务。"""

from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.agent_tasks.types import DeferredExecutionResult, ExecutionResult, ProgressCallback


async def execute_job_assets(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """执行求职材料生成任务：分析 JD、生成简历/自荐信等资产。"""
    from ai.workflows.jobs_support.job_asset_orchestrator import generate_assets

    await progress("loading_job")
    await progress("analyzing_jd")
    await progress("generating_assets")
    agent_run_id = payload.get("_agent_run_id")
    result = await generate_assets(
        job_id=int(payload["job_id"]),
        user_id=user_id,
        resume_content=payload["resume_content"],
        api_config=payload.get("api_config"),
        include_project_rewrite=bool(payload.get("include_project_rewrite", False)),
        template_style=payload.get("template_style", "professional"),
        agent_run_id=agent_run_id,
        update_job_status=not bool(agent_run_id),
    )
    if not result.get("success"):
        raise RuntimeError(result.get("message") or "岗位资产生成失败")
    await progress("saving_assets")
    assets = result.get("assets")
    public_result = {
        "success": True,
        "message": result.get("message"),
        "assets": assets.model_dump() if hasattr(assets, "model_dump") else assets,
    }

    async def persist_result(session: AsyncSession | None = None) -> dict:
        from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo

        if agent_run_id:
            await get_job_capture_repo().update_status(
                int(payload["job_id"]),
                user_id,
                "assets_generated",
                session=session,
            )
        return public_result

    if agent_run_id:
        return DeferredExecutionResult(persist=persist_result)
    return await persist_result()
