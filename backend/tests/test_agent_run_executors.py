"""AgentRun 执行器幂等与恢复回归测试。"""

import pytest


@pytest.mark.asyncio
async def test_resume_optimize_executor_reuses_saved_result_after_worker_crash(monkeypatch):
    """业务结果已落库但 Worker 未标记成功时，重试应复用结果而不是二次生成。"""
    from ai.workflows import agent_tasks as executors
    from ai.agents.resume import resume_orchestrator

    progress_stages: list[str] = []
    save_calls: list[dict] = []

    class FakeResumeRepo:
        async def get_result_by_agent_run_id(self, agent_run_id, user_id):
            assert agent_run_id == "run-1"
            assert user_id == "user-1"
            return {
                "id": 42,
                "result_data": {
                    "jd_analysis": {"match_score": 88, "hr_pass_rate": 80, "keywords_required": ["Python"]},
                    "change_items": [
                        {
                            "change_type": "polish",
                            "section_name": "项目经历",
                            "original_text": "old",
                            "optimized_text": "new",
                            "confidence": 0.9,
                            "reason": "突出 Python 经验",
                        }
                    ],
                    "errors": ["non-blocking warning"],
                },
            }

        async def save_result(self, **kwargs):
            save_calls.append(kwargs)
            return 99

    async def fail_if_pipeline_runs(**_kwargs):
        raise AssertionError("已有 agent_run_id 结果时不应重新运行优化 pipeline")

    async def progress(stage: str) -> None:
        progress_stages.append(stage)

    monkeypatch.setattr("app.db.repositories.resume.resume_repo.get_resume_repo", lambda: FakeResumeRepo())
    monkeypatch.setattr(resume_orchestrator, "run_pipeline", fail_if_pipeline_runs)

    result = await executors.execute_resume_optimize(
        {
            "_agent_run_id": "run-1",
            "resume_content": "resume",
            "job_description": "jd",
            "session_ids": [],
        },
        "user-1",
        progress,
    )

    assert progress_stages == ["preparing"]
    assert save_calls == []
    assert result["success"] is True
    assert result["result_id"] == 42
    assert result["warnings"] == ["non-blocking warning"]
    assert result["result"]["match_score"] == 88
    assert result["result"]["change_items"][0]["optimized_text"] == "new"


@pytest.mark.asyncio
async def test_resume_optimize_executor_defers_save_for_agent_run_transaction(monkeypatch):
    """有 agent_run_id 时，业务结果保存交给 AgentRun 完成事务统一提交。"""
    from ai.workflows import agent_tasks as executors
    from ai.agents.resume import resume_orchestrator

    progress_stages: list[str] = []
    save_calls: list[dict] = []
    tx_session = object()

    class FakeResumeRepo:
        async def get_result_by_agent_run_id(self, agent_run_id, user_id):
            assert agent_run_id == "run-2"
            assert user_id == "user-1"
            return None

        async def save_result(self, **kwargs):
            save_calls.append(kwargs)
            return 101

    pipeline_kwargs = {}

    async def fake_pipeline(**kwargs):
        pipeline_kwargs.update(kwargs)
        return {
            "jd_analysis": {"match_score": 91, "hr_pass_rate": 80, "keywords_required": ["Python"]},
            "change_items": [
                {
                    "change_type": "polish",
                    "section_name": "项目经历",
                    "original_text": "old",
                    "optimized_text": "new",
                    "confidence": 0.9,
                    "reason": "突出 Python 经验",
                }
            ],
            "errors": [],
        }

    async def progress(stage: str) -> None:
        progress_stages.append(stage)

    monkeypatch.setattr("app.db.repositories.resume.resume_repo.get_resume_repo", lambda: FakeResumeRepo())
    monkeypatch.setattr(resume_orchestrator, "run_pipeline", fake_pipeline)

    result = await executors.execute_resume_optimize(
        {
            "_agent_run_id": "run-2",
            "resume_content": "resume",
            "job_description": "jd",
            "session_ids": ["s1"],
            "include_overall_profile": True,
            "mode": "quality",
        },
        "user-1",
        progress,
    )

    assert isinstance(result, executors.DeferredExecutionResult)
    assert progress_stages == ["preparing", "optimizing", "saving_result"]
    assert save_calls == []

    public_result = await result.persist(tx_session)

    assert public_result["success"] is True
    assert public_result["result_id"] == 101
    assert public_result["result"]["match_score"] == 91
    assert len(save_calls) == 1
    assert save_calls[0]["agent_run_id"] == "run-2"
    assert save_calls[0]["session"] is tx_session
    assert save_calls[0]["session_ids"] == ["s1"]
    assert save_calls[0]["include_profile"] is True
    assert pipeline_kwargs["mode"] == "quality"


@pytest.mark.asyncio
async def test_job_assets_executor_defers_job_status_for_agent_run_transaction(monkeypatch):
    """岗位资产 AgentRun 的岗位状态更新应和完成态共用事务。"""
    from types import SimpleNamespace

    from ai.workflows import agent_tasks as executors

    progress_stages: list[str] = []
    generate_calls: list[dict] = []
    update_calls: list[dict] = []
    tx_session = object()

    async def fake_generate_assets(**kwargs):
        generate_calls.append(kwargs)
        return {
            "success": True,
            "message": "ok",
            "assets": SimpleNamespace(model_dump=lambda: {"job_id": kwargs["job_id"]}),
        }

    class FakeJobRepo:
        async def update_status(self, job_id, user_id, status, session=None):
            update_calls.append({
                "job_id": job_id,
                "user_id": user_id,
                "status": status,
                "session": session,
            })
            return True

    async def progress(stage: str) -> None:
        progress_stages.append(stage)

    monkeypatch.setattr("ai.workflows.jobs_support.job_asset_orchestrator.generate_assets", fake_generate_assets)
    monkeypatch.setattr("app.db.repositories.jobs.job_capture_repo.get_job_capture_repo", lambda: FakeJobRepo())

    result = await executors.execute_job_assets(
        {
            "_agent_run_id": "run-assets-1",
            "job_id": 12,
            "resume_content": "resume",
            "api_config": {"provider": "test"},
        },
        "user-1",
        progress,
    )

    assert isinstance(result, executors.DeferredExecutionResult)
    assert progress_stages == ["loading_job", "analyzing_jd", "generating_assets", "saving_assets"]
    assert generate_calls[0]["update_job_status"] is False
    assert update_calls == []

    public_result = await result.persist(tx_session)

    assert public_result == {"success": True, "message": "ok", "assets": {"job_id": 12}}
    assert update_calls == [
        {"job_id": 12, "user_id": "user-1", "status": "assets_generated", "session": tx_session}
    ]
