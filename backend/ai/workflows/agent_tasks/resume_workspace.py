"""Recoverable executor for the unified Resume Workspace workflow."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.agent_tasks.types import DeferredExecutionResult, ProgressCallback


def _public_workspace_result(result_id: int, result_data: dict[str, Any]) -> dict[str, Any]:
    """Map the persisted parent result to the public workspace response.

    ``result_data`` uses the established ``optimize`` shape at its top level so
    existing generation and high-risk review endpoints retain their approval
    gate. Workspace-only analysis is nested under ``workspace``.
    """
    from ai.agents.resume.result_mapper import pipeline_to_optimize_result
    from ai.agents.resume.resume_review import public_review_state

    workspace = result_data.get("workspace") or {}
    return {
        "success": True,
        "result_id": result_id,
        "competition_analysis": workspace.get("competition_analysis") or {},
        "jd_matching": workspace.get("jd_matching") or {},
        "content_optimization": pipeline_to_optimize_result(result_data).model_dump(),
        "review": public_review_state(result_data),
        "warnings": result_data.get("errors") or [],
    }


async def execute_resume_workspace(
    payload: dict,
    user_id: str,
    progress: ProgressCallback,
) -> dict | DeferredExecutionResult:
    """Run and atomically persist competition, JD and optimization workspace results.

    All model work is delegated to existing agents that use the model gateway.
    The final optimization is initialized through the existing human-review gate;
    no generated high-risk content is marked approved by this workflow.
    """
    from app.db.repositories.resume.resume_repo import get_resume_repo
    from ai.agents.resume.jd_matcher import analyze_jd_match
    from ai.agents.resume.resume_analyzer_graph import analyze_resume
    from ai.agents.resume.resume_orchestrator import run_pipeline
    from ai.agents.resume.resume_review import initialize_review

    agent_run_id = payload.get("_agent_run_id")
    resume_repo = get_resume_repo()
    if agent_run_id:
        existing = await resume_repo.get_result_by_agent_run_id(agent_run_id, user_id)
        if existing:
            return _public_workspace_result(existing["id"], existing["result_data"])

    session_ids = payload.get("session_ids") or []
    if len(session_ids) > 3:
        raise ValueError("最多只能选择 3 个面试记录")
    api_config = payload.get("api_config")
    resume_content = payload["resume_content"]
    job_description = payload["job_description"]

    await progress("competition_analysis")
    competition_analysis = await analyze_resume(
        resume_content=resume_content,
        job_description=job_description,
        session_ids=session_ids,
        user_id=user_id,
        api_config=api_config,
    )
    await progress("jd_matching")
    jd_matching = await analyze_jd_match(
        resume_content=resume_content,
        job_description=job_description,
        api_config=api_config,
    )
    await progress("content_optimization")
    optimization_result = initialize_review(
        await run_pipeline(
            resume_content=resume_content,
            job_description=job_description,
            session_ids=session_ids,
            include_profile=bool(payload.get("include_overall_profile", False)),
            user_id=user_id,
            api_config=api_config,
            run_id=agent_run_id,
            mode=str(payload.get("mode") or "balanced"),
        )
    )
    # Keep top-level optimize fields for existing generation/review readers; this
    # adds one compatible parent result instead of introducing an unhandled type.
    optimization_result["workspace"] = {
        "version": 1,
        "competition_analysis": competition_analysis,
        "jd_matching": jd_matching,
    }
    await progress("saving_result")

    async def persist_result(session: AsyncSession | None = None) -> dict:
        """Save the parent result in the AgentRun transaction for crash-safe retries."""
        result_id = await resume_repo.save_result(
            user_id=user_id,
            result_type="optimize",
            resume_content=resume_content,
            result_data=optimization_result,
            job_description=job_description,
            session_ids=session_ids,
            include_profile=bool(payload.get("include_overall_profile", False)),
            agent_run_id=agent_run_id,
            session=session,
        )
        return _public_workspace_result(result_id, optimization_result)

    if agent_run_id:
        return DeferredExecutionResult(persist=persist_result)
    return await persist_result()
