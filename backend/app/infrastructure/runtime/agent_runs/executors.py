"""通用任务执行器注册表。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.runtime.agent_runs.interview_start import execute_interview_start
from app.infrastructure.runtime.agent_runs.service import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_RESUME_OPTIMIZE,
)

ProgressCallback = Callable[[str], Awaitable[None]]
PersistResultCallback = Callable[[AsyncSession], Awaitable[dict]]


@dataclass(frozen=True)
class DeferredExecutionResult:
    """业务结果需要和 AgentRun 完成态在同一事务内落库。"""

    persist: PersistResultCallback


ExecutionResult = dict | DeferredExecutionResult
TaskExecutor = Callable[[dict, str, ProgressCallback], Awaitable[ExecutionResult]]
logger = logging.getLogger(__name__)


async def execute_resume_optimize(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
    from app.infrastructure.db.repositories.resume.resume_repo import get_resume_repo
    from app.agents.resume.result_mapper import pipeline_to_optimize_result
    from app.agents.resume.resume_orchestrator import run_pipeline
    from app.agents.resume.resume_review import initialize_review

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


async def execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> dict:
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


async def execute_job_assets(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from app.infrastructure.browser.job_asset_orchestrator import generate_assets

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
        from app.infrastructure.db.repositories.jobs.job_capture_repo import get_job_capture_repo

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


EXECUTORS: dict[str, TaskExecutor] = {
    TASK_TYPE_INTERVIEW_START: lambda payload, user_id, progress: execute_interview_start(payload, user_id, progress),
    TASK_TYPE_RESUME_OPTIMIZE: execute_resume_optimize,
    TASK_TYPE_INTERVIEW_REPORT: execute_interview_report,
    TASK_TYPE_JOB_ASSETS: execute_job_assets,
}


async def execute_registered_task(task_type: str, payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    try:
        executor = EXECUTORS[task_type]
    except KeyError as exc:
        raise ValueError(f"unknown task type: {task_type}") from exc
    return await executor(payload, user_id, progress)
