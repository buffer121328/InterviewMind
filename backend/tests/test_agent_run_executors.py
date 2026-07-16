"""AgentRun 执行器幂等与恢复回归测试。"""

import pytest


@pytest.mark.asyncio
async def test_resume_optimize_executor_reuses_saved_result_after_worker_crash(monkeypatch):
    """业务结果已落库但 Worker 未标记成功时，重试应复用结果而不是二次生成。"""
    from app.services.agent_runs import executors
    from app.services.resume import resume_orchestrator

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

    monkeypatch.setattr("app.repositories.resume.resume_repo.get_resume_repo", lambda: FakeResumeRepo())
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
