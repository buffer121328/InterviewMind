"""提供简历工作区相关后端功能。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ai.runtime.execution.deadlines import TaskDeadline
from ai.workflows.agent_runs.contracts import DeferredExecutionResult, ProgressCallback
from ai.workflows.jobs.job_context import normalize_owned_job_context_snapshot
from app.config import get_settings

logger = logging.getLogger(__name__)

_WORKSPACE_CHECKPOINT_VERSION = "resume.workspace.phase4.v1"


def _public_workspace_result(result_id: int, result_data: dict[str, Any]) -> dict[str, Any]:
    """处理公开工作区结果相关后端逻辑。"""
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
        "source_job_id": workspace.get("source_job_id"),
        "job_context_snapshot": workspace.get("job_context_snapshot"),
    }


def _pipeline_jd_analysis(jd_matching: dict[str, Any]) -> dict[str, Any]:
    """处理流水线JD分析相关后端逻辑。"""
    match_score = float(jd_matching.get("overall_match_score") or 0)
    matched = list(jd_matching.get("matched_keywords") or [])
    missing = list(jd_matching.get("missing_keywords") or [])
    required = list(dict.fromkeys([*matched, *missing]))
    priority_actions = list(jd_matching.get("priority_actions") or [])
    return {
        "match_score": match_score,
        "hr_pass_rate": round(match_score * 0.85),
        "jd_keywords": required,
        "keywords_required": required,
        "keywords_preferred": [],
        "matched_keywords": matched,
        "missing_keywords": missing,
        "bonus_items": [],
        "priority_rewrite_points": [
            {"area": "综合", "action": action, "priority": index + 1}
            for index, action in enumerate(priority_actions[:5])
        ],
        "emphasis_areas": list(jd_matching.get("strengths") or [])[:5],
        "analysis_summary": f"工作区 JD 匹配分析综合得分 {match_score:.1f}。",
    }


def _compact_json(value: Any) -> str:
    """处理紧凑JSON相关后端逻辑。"""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _local_jd_matching(bundle: Any) -> dict[str, Any]:
    """处理本地JD相关后端逻辑。"""
    matched = bundle.match_map.matched_evidence
    missing = bundle.match_map.missing_requirements
    total = len(matched) + len(missing)
    score = round((len(matched) / total) * 100, 1) if total else 0.0
    matched_keywords = [item.get("requirement", "") for item in matched]
    return {
        "overall_match_score": score,
        "skill_match_score": score,
        "project_match_score": score,
        "experience_match_score": score,
        "education_match_score": score,
        "matched_keywords": matched_keywords[:12],
        "missing_keywords": missing[:12],
        "strengths": [item.get("evidence", "") for item in matched[:5]],
        "risks": missing[:5],
        "priority_actions": bundle.match_map.rewrite_targets[:5],
        "selection_hints": [],
        "degraded": True,
    }


def _local_competition_analysis(bundle: Any) -> dict[str, Any]:
    """处理本地竞赛分析相关后端逻辑。"""
    facts = bundle.fact_sheet
    evidence_count = sum(
        len(items)
        for items in (
            facts.skills,
            facts.employment_facts,
            facts.project_facts,
            facts.quantified_results,
            facts.education,
        )
    )
    score = min(100, 35 + evidence_count * 3)
    return {
        "overall_score": score,
        "dimension_scores": {},
        "strengths": [*facts.quantified_results[:2], *facts.project_facts[:3]],
        "weaknesses": bundle.match_map.missing_requirements[:5],
        "suggestions": bundle.match_map.rewrite_targets[:5],
        "interview_insights": None,
        "degraded": True,
    }


def _checkpoint_matches(checkpoint: Mapping[str, Any] | None, cache_identity: str) -> bool:
    """处理检查点相关后端逻辑。"""
    return bool(
        checkpoint
        and checkpoint.get("version") == _WORKSPACE_CHECKPOINT_VERSION
        and checkpoint.get("cache_identity") == cache_identity
    )


async def _load_checkpoint(
    service: Any,
    *,
    run_id: str,
    user_id: str,
    stage: str,
) -> dict[str, Any] | None:
    """加载检查点相关后端逻辑。"""
    if service is None:
        return None
    try:
        return await service.load_checkpoint(run_id, user_id, stage)
    except Exception as exc:
        logger.warning(
            "Resume Workspace checkpoint load degraded: stage=%s error_type=%s",
            stage,
            type(exc).__name__,
        )
        return None


async def _save_checkpoint(
    service: Any,
    *,
    run_id: str,
    user_id: str,
    stage: str,
    checkpoint: dict[str, Any],
) -> None:
    """保存检查点相关后端逻辑。"""
    if service is None:
        return
    try:
        await service.save_checkpoint(run_id, stage, checkpoint, user_id=user_id)
    except Exception as exc:
        logger.warning(
            "Resume Workspace checkpoint save degraded: stage=%s error_type=%s",
            stage,
            type(exc).__name__,
        )


async def execute_resume_workspace(
    payload: dict,
    user_id: str,
    progress: ProgressCallback,
) -> dict | DeferredExecutionResult:
    """执行简历工作区相关后端逻辑。"""
    from ai.agents.resume.jd_matcher import match_jd
    from ai.agents.resume.optimization.flow import run_pipeline
    from ai.agents.resume.resume_analyzer_graph import analyze_resume
    from ai.agents.resume.resume_context import assemble_resume_context
    from ai.agents.resume.resume_review import initialize_review
    from app.db.repositories.resume.resume_repo import get_resume_repo

    agent_run_id = str(payload.get("_agent_run_id") or "")
    resume_repo = get_resume_repo()
    job_context_snapshot = await normalize_owned_job_context_snapshot(
        payload.get("job_context_snapshot"), user_id=user_id
    )
    if agent_run_id:
        existing = await resume_repo.get_result_by_agent_run_id(agent_run_id, user_id)
        if existing:
            return _public_workspace_result(existing["id"], existing["result_data"])

    session_ids = [str(item) for item in payload.get("session_ids") or []]
    if len(session_ids) > 3:
        raise ValueError("最多只能选择 3 个面试记录")
    api_config = payload.get("api_config")
    resume_content = payload["resume_content"]
    job_description = payload["job_description"]
    if job_context_snapshot is not None:
        job_context_snapshot["job_description"] = job_description
    mode = str(payload.get("mode") or "balanced")
    deadline = TaskDeadline(float(get_settings().resume_workspace_task_timeout_seconds))
    bundle = assemble_resume_context(
        owner_id=user_id,
        resume_content=resume_content,
        job_description=job_description,
        selected_session_versions=session_ids,
        mode=mode,
    )
    event_metadata = bundle.assembled.model_event_fields()
    compact_resume = _compact_json(bundle.fact_sheet)
    compact_jd = _compact_json(bundle.requirement_map)

    checkpoint_service = None
    if agent_run_id:
        from ai.runtime.agent_runs.service import AgentRunService

        checkpoint_service = AgentRunService()
        await _save_checkpoint(
            checkpoint_service,
            run_id=agent_run_id,
            user_id=user_id,
            stage="competition_analysis",
            checkpoint={
                "version": _WORKSPACE_CHECKPOINT_VERSION,
                "cache_identity": bundle.cache_identity,
                "fact_sheet": bundle.fact_sheet.model_dump(),
                "requirement_map": bundle.requirement_map.model_dump(),
                "stage_status": {
                    "fact_sheet": "completed",
                    "requirement_map": "completed",
                },
            },
        )

    optimization_checkpoint = await _load_checkpoint(
        checkpoint_service,
        run_id=agent_run_id,
        user_id=user_id,
        stage="content_optimization",
    )
    if _checkpoint_matches(optimization_checkpoint, bundle.cache_identity):
        optimization_result = dict(optimization_checkpoint.get("optimization_result") or {})
        if optimization_result:
            workspace = optimization_result.setdefault("workspace", {})
            if job_context_snapshot is not None:
                workspace["source_job_id"] = job_context_snapshot["source_job_id"]
                workspace["job_context_snapshot"] = job_context_snapshot
            await progress("content_optimization")
            await progress("saving_result")
            return await _deferred_or_persist(
                resume_repo=resume_repo,
                optimization_result=optimization_result,
                resume_content=resume_content,
                job_description=job_description,
                session_ids=session_ids,
                include_profile=bool(payload.get("include_overall_profile", False)),
                agent_run_id=agent_run_id,
                user_id=user_id,
            )

    analysis_checkpoint = await _load_checkpoint(
        checkpoint_service,
        run_id=agent_run_id,
        user_id=user_id,
        stage="jd_matching",
    )
    analysis_warnings: list[str] = []
    if _checkpoint_matches(analysis_checkpoint, bundle.cache_identity):
        competition_analysis = dict(analysis_checkpoint.get("competition_analysis") or {})
        jd_matching = dict(analysis_checkpoint.get("jd_matching") or {})
    else:
        await progress("competition_analysis")

        async def competition_call() -> dict[str, Any]:
            """处理竞赛相关后端逻辑。"""
            return await analyze_resume(
                resume_content=compact_resume,
                job_description=compact_jd,
                session_ids=session_ids,
                user_id=user_id,
                api_config=api_config,
                deadline=deadline,
                call_metadata=event_metadata,
            )

        async def match_call() -> dict[str, Any]:
            """处理简历工作区相关后端逻辑。"""
            return await match_jd(
                mode="smart",
                resume_content=compact_resume,
                job_description=compact_jd,
                api_config=api_config,
                user_id=user_id,
                deadline=deadline,
                call_metadata=event_metadata,
            )

        competition_raw, match_raw = await asyncio.gather(
            competition_call(),
            match_call(),
            return_exceptions=True,
        )
        if isinstance(competition_raw, BaseException):
            analysis_warnings.append(
                f"竞争力分析降级: {type(competition_raw).__name__}"
            )
            competition_analysis = _local_competition_analysis(bundle)
        else:
            competition_analysis = competition_raw
        if isinstance(match_raw, BaseException):
            analysis_warnings.append(f"JD 匹配降级: {type(match_raw).__name__}")
            jd_matching = _local_jd_matching(bundle)
        else:
            jd_matching = match_raw

        await progress("jd_matching")
        await _save_checkpoint(
            checkpoint_service,
            run_id=agent_run_id,
            user_id=user_id,
            stage="jd_matching",
            checkpoint={
                "version": _WORKSPACE_CHECKPOINT_VERSION,
                "cache_identity": bundle.cache_identity,
                "match_map": bundle.match_map.model_dump(),
                "competition_analysis": competition_analysis,
                "jd_matching": jd_matching,
                "stage_status": {
                    "fact_sheet": "completed",
                    "requirement_map": "completed",
                    "match_map": "completed",
                },
            },
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
            run_id=agent_run_id or None,
            mode=mode,
            precomputed_jd_analysis=_pipeline_jd_analysis(jd_matching),
            deadline=deadline,
        )
    )
    optimization_result.setdefault("errors", []).extend(analysis_warnings)
    optimization_result["workspace"] = {
        "version": 2,
        "context_schema_version": _WORKSPACE_CHECKPOINT_VERSION,
        "cache_identity": bundle.cache_identity,
        "competition_analysis": competition_analysis,
        "jd_matching": jd_matching,
        "source_job_id": job_context_snapshot["source_job_id"] if job_context_snapshot else None,
        "job_context_snapshot": job_context_snapshot,
    }
    await _save_checkpoint(
        checkpoint_service,
        run_id=agent_run_id,
        user_id=user_id,
        stage="content_optimization",
        checkpoint={
            "version": _WORKSPACE_CHECKPOINT_VERSION,
            "cache_identity": bundle.cache_identity,
            "optimization_result": optimization_result,
            "stage_status": {
                "rewrite": "completed",
                "fact_check": "completed",
                "human_review": str(
                    (optimization_result.get("human_review") or {}).get("status") or "pending"
                ),
            },
        },
    )
    await progress("saving_result")
    return await _deferred_or_persist(
        resume_repo=resume_repo,
        optimization_result=optimization_result,
        resume_content=resume_content,
        job_description=job_description,
        session_ids=session_ids,
        include_profile=bool(payload.get("include_overall_profile", False)),
        agent_run_id=agent_run_id,
        user_id=user_id,
    )


async def _deferred_or_persist(
    *,
    resume_repo: Any,
    optimization_result: dict[str, Any],
    resume_content: str,
    job_description: str,
    session_ids: list[str],
    include_profile: bool,
    agent_run_id: str,
    user_id: str,
) -> dict | DeferredExecutionResult:
    """处理简历工作区相关后端逻辑。"""

    async def persist_result(session: AsyncSession | None = None) -> dict:
        """持久化结果相关后端逻辑。"""
        result_id = await resume_repo.save_result(
            user_id=user_id,
            result_type="optimize",
            resume_content=resume_content,
            result_data=optimization_result,
            job_description=job_description,
            session_ids=session_ids,
            include_profile=include_profile,
            agent_run_id=agent_run_id or None,
            session=session,
        )
        return _public_workspace_result(result_id, optimization_result)

    if agent_run_id:
        return DeferredExecutionResult(persist=persist_result)
    return await persist_result()
