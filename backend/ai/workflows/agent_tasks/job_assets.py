"""岗位投递资产 AgentRun 兼容任务。

该执行器仅用于恢复或重试本变更上线前已经持久化的 ``job_assets`` 运行。
新岗位入库不再创建此任务；确认没有 queued/running 存量运行后应在独立清理
变更中删除注册、执行器和旧编排器。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.agent_tasks.types import DeferredExecutionResult, ExecutionResult, ProgressCallback
from observability import agent_observation


async def execute_job_assets(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """执行岗位资产任务，并把运行中或失败状态同步到 owner 范围内的岗位库。"""
    from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo

    job_id = int(payload["job_id"])
    agent_run_id = payload.get("_agent_run_id")
    repo = get_job_capture_repo()
    if agent_run_id:
        await repo.update_asset_tracking(
            job_id,
            user_id,
            asset_run_id=str(agent_run_id),
            asset_status="running",
        )
    try:
        async with agent_observation(
            name="job-assets",
            agent_type="job_assets",
            user_id=user_id,
            session_id=None,
            run_id=agent_run_id,
            input_payload={
                "job_id": job_id,
                "include_project_rewrite": bool(payload.get("include_project_rewrite", False)),
                "template_style": str(payload.get("template_style", "professional"))[:40],
            },
        ) as observation:
            result = await _execute_job_assets(payload, user_id, progress)
            observation.set_output({
                "deferred_persistence": isinstance(result, DeferredExecutionResult),
            })
            return result
    except Exception:
        if agent_run_id:
            await repo.update_asset_tracking(
                job_id,
                user_id,
                asset_run_id=str(agent_run_id),
                asset_status="failed",
            )
        raise


async def _execute_job_assets(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """执行岗位资产相关后端逻辑。"""
    from ai.workflows.jobs.job_asset_orchestrator import generate_assets

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
        """在事务会话中完成岗位资产任务的状态落库；AgentRun 场景延迟提交，避免业务任务绕过统一生命周期。"""
        from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo

        if agent_run_id:
            repo = get_job_capture_repo()
            await repo.update_status(
                int(payload["job_id"]),
                user_id,
                "assets_generated",
                session=session,
            )
            asset_payload = public_result.get("assets") or {}
            jd_analysis = asset_payload.get("jd_analysis") if isinstance(asset_payload, dict) else {}
            match_score = jd_analysis.get("overall_match_score") if isinstance(jd_analysis, dict) else None
            await repo.update_asset_tracking(
                int(payload["job_id"]),
                user_id,
                asset_run_id=str(agent_run_id),
                asset_status="succeeded",
                match_score=match_score,
                asset_payload=asset_payload if isinstance(asset_payload, dict) else {},
                session=session,
            )
        return public_result

    if agent_run_id:
        return DeferredExecutionResult(persist=persist_result)
    return await persist_result()
