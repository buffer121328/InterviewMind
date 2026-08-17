import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _request():
    from app.schemas.jobs.job_schemas import JobJdAnalysisRequest

    config = {
        "smart": {"base_url": "https://models.example.test/v1", "model": "smart-model"},
        "fast": {"base_url": "https://models.example.test/v1", "model": "fast-model"},
    }
    return JobJdAnalysisRequest(resume_content="具备 Python、FastAPI 与分布式系统项目经验", api_config=config)


def _install_match_dependencies(monkeypatch, match_jd):
    """Supplies the dynamic optional dependencies without importing real LLM or guardrails packages."""
    guardrails = ModuleType("ai.runtime.safety.guardrails")
    guardrails.screen_untrusted_text = lambda *_args, **_kwargs: SimpleNamespace(allowed=True)
    matcher = ModuleType("ai.agents.resume.jd_matcher")
    matcher.match_jd = match_jd
    monkeypatch.setitem(sys.modules, "ai.runtime.safety.guardrails", guardrails)
    monkeypatch.setitem(sys.modules, "ai.agents.resume.jd_matcher", matcher)


def _job(*, asset_payload=None, match_score=61.0):
    return {
        "id": 7,
        "user_id": "user-1",
        "job_title": "后端工程师",
        "job_description": "岗位职责：\n1. 负责 Python 服务开发\n2. 参与分布式系统设计",
        "match_score": match_score,
        "asset_payload": asset_payload or {},
        "status": "pending",
    }


@pytest.mark.asyncio
async def test_explicit_job_jd_analysis_persists_only_analysis_summary(monkeypatch):
    from ai.workflows.jobs import use_cases as module

    repo = SimpleNamespace(
        get_job=AsyncMock(side_effect=[_job(), {**_job(), "match_score": 88.0, "asset_payload": {
            "preliminary_match_score": 61.0,
            "jd_analysis": {"overall_match_score": 88.0, "matched_keywords": ["Python"]},
        }}]),
        update_asset_tracking=AsyncMock(return_value=True),
    )
    match_jd = AsyncMock(return_value={
        "overall_match_score": 88.0,
        "skill_match_score": 90.0,
        "project_match_score": 86.0,
        "experience_match_score": 85.0,
        "education_match_score": 70.0,
        "matched_keywords": ["Python"],
        "missing_keywords": ["Kubernetes"],
        "strengths": ["有后端交付经验"],
        "risks": [],
        "priority_actions": ["补充容器编排项目"],
        "ignored_private_field": "must not persist",
    })
    monkeypatch.setattr(module, "get_job_capture_repo", lambda: repo)
    _install_match_dependencies(monkeypatch, match_jd)

    result = await module.JobsUseCases().analyze_job_jd(job_id=7, request=_request(), user_id="user-1")

    assert result.success is True
    match_jd.assert_awaited_once()
    repo.update_asset_tracking.assert_awaited_once_with(
        7,
        "user-1",
        match_score=88.0,
        asset_payload={
            "preliminary_match_score": 61.0,
            "jd_analysis": {
                "overall_match_score": 88.0,
                "skill_match_score": 90.0,
                "project_match_score": 86.0,
                "experience_match_score": 85.0,
                "education_match_score": 70.0,
                "matched_keywords": ["Python"],
                "missing_keywords": ["Kubernetes"],
                "strengths": ["有后端交付经验"],
                "risks": [],
                "priority_actions": ["补充容器编排项目"],
            },
        },
    )
    assert result.job["status"] == "pending"


@pytest.mark.asyncio
async def test_job_jd_analysis_rejects_missing_configuration_without_reading_job(monkeypatch):
    from ai.workflows.jobs import use_cases as module
    from ai.workflows.jobs.use_cases import JobBadRequest
    from app.schemas.jobs.job_schemas import JobJdAnalysisRequest

    repo = SimpleNamespace(get_job=AsyncMock())
    monkeypatch.setattr(module, "get_job_capture_repo", lambda: repo)

    with pytest.raises(JobBadRequest, match="配置可用模型"):
        await module.JobsUseCases().analyze_job_jd(
            job_id=7,
            request=JobJdAnalysisRequest(resume_content="简历内容", api_config=None),
            user_id="user-1",
        )

    repo.get_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_job_jd_analysis_enforces_owner_before_model_call(monkeypatch):
    from ai.workflows.jobs import use_cases as module
    from ai.workflows.jobs.use_cases import JobNotFound

    repo = SimpleNamespace(get_job=AsyncMock(return_value=None), update_asset_tracking=AsyncMock())
    monkeypatch.setattr(module, "get_job_capture_repo", lambda: repo)

    with pytest.raises(JobNotFound):
        await module.JobsUseCases().analyze_job_jd(job_id=7, request=_request(), user_id="other-user")

    repo.update_asset_tracking.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_reanalysis_keeps_existing_result_untouched(monkeypatch):
    from ai.workflows.jobs import use_cases as module
    from ai.workflows.jobs.use_cases import JobBadRequest

    existing = _job(asset_payload={"jd_analysis": {"overall_match_score": 72.0, "matched_keywords": ["FastAPI"]}}, match_score=72.0)
    repo = SimpleNamespace(get_job=AsyncMock(return_value=existing), update_asset_tracking=AsyncMock())
    monkeypatch.setattr(module, "get_job_capture_repo", lambda: repo)
    _install_match_dependencies(monkeypatch, AsyncMock(side_effect=RuntimeError("provider unavailable")))

    with pytest.raises(JobBadRequest, match="暂时失败"):
        await module.JobsUseCases().analyze_job_jd(job_id=7, request=_request(), user_id="user-1")

    repo.update_asset_tracking.assert_not_awaited()
    assert existing["asset_payload"]["jd_analysis"]["overall_match_score"] == 72.0


@pytest.mark.asyncio
async def test_job_jd_analysis_route_delegates_to_owner_scoped_use_case(monkeypatch):
    from app.api.jobs import analyze_job_jd

    use_cases = SimpleNamespace(analyze_job_jd=AsyncMock(return_value={"success": True, "job": {"id": 7}}))
    monkeypatch.setattr("app.api.jobs.jobs_use_cases", use_cases)

    result = await analyze_job_jd(7, _request(), "user-1")

    assert result["success"] is True
    use_cases.analyze_job_jd.assert_awaited_once_with(job_id=7, request=_request(), user_id="user-1")
