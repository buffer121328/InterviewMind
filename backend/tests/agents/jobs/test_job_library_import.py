"""岗位一键入库的确定性持久化与输入边界测试。"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError


def make_imported_card(index: int = 1) -> dict[str, object]:
    """Build one bounded official BOSS card accepted by the import boundary."""
    return {
        "company_name": f"示例科技 {index}",
        "company_size_text": "100-499人",
        "job_title": f"Agent 工程师 {index}",
        "salary_text": "20-30K",
        "city": "深圳",
        "title_summary": "3-5年 本科",
        "job_description": "负责 Agent 产品及 Python 服务端开发工作",
        "source_url": f"https://www.zhipin.com/job_detail/card_{index}-real.html",
        "preliminary_match_score": 86.5,
    }


@pytest.fixture(autouse=True)
def _backend_capture_log_dir(monkeypatch, tmp_path):
    """Keep backend-only capture logs isolated per test."""
    monkeypatch.setenv("ARTIFACT_STORAGE_DIR", str(tmp_path))


class TestDeterministicImport:
    """一键入库只保存岗位，不进入模型或 Agent 任务边界。"""

    @pytest.mark.asyncio
    async def test_import_saves_job_without_scheduling_model_work(self, monkeypatch):
        """成功入库不得创建 AgentRun、Outbox 调度或同步资产生成。"""
        from ai.runtime.agent_runs import outbox
        from ai.runtime.agent_runs import service as run_service_module
        from ai.workflows.jobs import job_asset_orchestrator
        from ai.workflows.jobs.capture.imports import import_cards_to_library

        create_or_get = AsyncMock()
        dispatch_pending = AsyncMock()
        generate_assets = AsyncMock()
        monkeypatch.setattr(run_service_module.AgentRunService, "create_or_get", create_or_get)
        monkeypatch.setattr(outbox, "dispatch_pending_outbox", dispatch_pending)
        monkeypatch.setattr(job_asset_orchestrator, "generate_assets", generate_assets)
        monkeypatch.setattr(run_service_module, "task_queue_enabled", lambda: True)

        with patch(
            "ai.workflows.jobs.capture.imports.normalize_and_save_job",
            new=AsyncMock(return_value={"success": True, "job_id": 7}),
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[make_imported_card()],
            )

        assert result["success"] is True
        assert result["total"] == 1
        assert result["duplicates"] == 0
        assert result["jobs"][0] == {
            "job_id": 7,
            "source_url": make_imported_card()["source_url"],
            "company_name": "示例科技 1",
            "company_size_text": "100-499人",
            "job_title": "Agent 工程师 1",
            "job_description": "负责 Agent 产品及 Python 服务端开发工作",
            "salary_text": "20-30K",
            "city": "深圳",
            "match_score": 86.5,
            "custom_resume_id": None,
            "risk_flags": [],
            "asset_run_id": None,
            "asset_status": None,
        }
        create_or_get.assert_not_awaited()
        dispatch_pending.assert_not_awaited()
        generate_assets.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_import_twenty_jobs_without_derived_tasks(self, monkeypatch):
        """批量入库上限场景保存 20 个岗位且不放大为 20 个资产任务。"""
        from ai.runtime.agent_runs import service as run_service_module
        from ai.workflows.jobs import job_asset_orchestrator
        from ai.workflows.jobs.capture.imports import import_cards_to_library

        create_or_get = AsyncMock()
        generate_assets = AsyncMock()
        monkeypatch.setattr(run_service_module.AgentRunService, "create_or_get", create_or_get)
        monkeypatch.setattr(job_asset_orchestrator, "generate_assets", generate_assets)

        normalize = AsyncMock(
            side_effect=[{"success": True, "job_id": index} for index in range(1, 21)]
        )
        with patch(
            "ai.workflows.jobs.capture.imports.normalize_and_save_job",
            new=normalize,
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[make_imported_card(index) for index in range(1, 21)],
            )

        assert result["success"] is True
        assert result["total"] == 20
        assert len(result["jobs"]) == 20
        assert normalize.await_count == 20
        create_or_get.assert_not_awaited()
        generate_assets.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_import_reuses_existing_job_and_counts_duplicate(self):
        """按来源哈希去重时复用岗位库记录且不派生任务。"""
        from ai.workflows.jobs.capture.imports import import_cards_to_library

        with patch(
            "ai.workflows.jobs.capture.imports.normalize_and_save_job",
            new=AsyncMock(return_value={
                "success": True,
                "job_id": 3,
                "is_duplicate": True,
                "message": "该岗位已采集过，已复用岗位库记录",
            }),
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[make_imported_card()],
            )

        assert result["success"] is True
        assert result["total"] == 1
        assert result["duplicates"] == 1
        assert result["jobs"][0]["job_id"] == 3
        assert result["jobs"][0]["asset_run_id"] is None

    @pytest.mark.asyncio
    async def test_import_returns_partial_failure_details(self):
        """单张卡片保存失败时返回失败明细，且失败卡片不进入 jobs。"""
        from ai.workflows.jobs.capture.imports import import_cards_to_library

        async def fake_save(card, _user_id, _platform, source_url="", source_text=""):
            if str(card["job_title"]).endswith("2"):
                return {"success": False, "message": "岗位信息不完整"}
            return {"success": True, "job_id": 7}

        with patch(
            "ai.workflows.jobs.capture.imports.normalize_and_save_job",
            new=AsyncMock(side_effect=fake_save),
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[make_imported_card(1), make_imported_card(2)],
            )

        assert result["total"] == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["job_title"] == "Agent 工程师 2"
        assert result["failed"][0]["source_url"] == make_imported_card(2)["source_url"]
        assert result["failed"][0]["reason"] == "岗位信息不完整"

    @pytest.mark.asyncio
    async def test_import_rejects_invalid_cards_without_saving(self):
        """外部域名或无效卡片在入库边界被拒绝，不触发任何保存。"""
        from ai.workflows.jobs.capture.imports import import_cards_to_library

        normalize_job = AsyncMock()
        with patch(
            "ai.workflows.jobs.capture.imports.normalize_and_save_job",
            new=normalize_job,
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[{
                    **make_imported_card(),
                    "source_url": "https://example.com/job_detail/card1.html",
                }],
            )

        assert result["success"] is False
        assert result["total"] == 0
        normalize_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_import_filters_internship_cards(self):
        """实习标记卡片不得入库。"""
        from ai.workflows.jobs.capture.imports import import_cards_to_library

        normalize_job = AsyncMock()
        with patch(
            "ai.workflows.jobs.capture.imports.normalize_and_save_job",
            new=normalize_job,
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[{**make_imported_card(), "job_title": "Agent 实习生"}],
            )

        assert result["success"] is False
        assert result["total"] == 0
        normalize_job.assert_not_awaited()


class TestImportBoundaries:
    """入库请求的 schema 与用例边界。"""

    def test_import_request_requires_one_to_twenty_official_cards(self):
        """请求只接受 1-20 张官方岗位卡片且不要求模型相关字段。"""
        from app.schemas.job_schemas import JobLibraryImportRequest

        base = {"cards": [make_imported_card()]}
        request = JobLibraryImportRequest(**base)
        assert len(request.cards) == 1
        assert request.cards[0].preliminary_match_score == 86.5
        assert not hasattr(request, "resume_content")
        assert not hasattr(request, "api_config")
        with pytest.raises(ValidationError):
            JobLibraryImportRequest(**{**base, "cards": []})
        with pytest.raises(ValidationError):
            JobLibraryImportRequest(
                **{**base, "cards": [make_imported_card(i) for i in range(1, 22)]}
            )
        with pytest.raises(ValidationError):
            JobLibraryImportRequest(
                **{
                    **base,
                    "cards": [{
                        **make_imported_card(),
                        "source_url": "https://example.com/job_detail/card1.html",
                    }],
                }
            )
        with pytest.raises(ValidationError):
            JobLibraryImportRequest(
                **{
                    **base,
                    "cards": [{**make_imported_card(), "preliminary_match_score": 101}],
                }
            )
        with pytest.raises(ValidationError):
            JobLibraryImportRequest(
                **{**base, "resume_content": "legacy", "api_config": {"smart": {}}}
            )

    @pytest.mark.asyncio
    async def test_import_use_case_passes_only_cards_and_city_to_service(self):
        """用例只把确定性入库字段交给服务层。"""
        from app.schemas.job_schemas import JobLibraryImportRequest
        from ai.workflows.jobs import jobs_use_cases

        request = JobLibraryImportRequest(
            city="101280600",
            cards=[make_imported_card()],
        )
        service_mock = AsyncMock(return_value={
            "success": True,
            "total": 1,
            "duplicates": 0,
            "jobs": [],
            "failed": [],
            "message": "ok",
        })
        with patch(
            "ai.workflows.jobs.capture.imports.import_cards_to_library",
            new=service_mock,
        ):
            result = await jobs_use_cases.import_cards_to_library(
                request=request,
                user_id="user-1",
            )

        assert result["success"] is True
        service_mock.assert_awaited_once_with(
            user_id="user-1",
            cards=[card.model_dump() for card in request.cards],
            city="101280600",
        )

class TestHistoricalAssetCompatibility:
    """历史岗位资产保持可读，但退休的文案字段不会重新暴露。"""

    @pytest.mark.asyncio
    async def test_job_detail_hides_historical_greetings_but_preserves_resume_assets(self, monkeypatch):
        """历史 JSON 可保留，但岗位详情只返回仍支持的资产字段。"""
        from ai.workflows.jobs import use_cases as jobs

        fake_repo = type("FakeRepo", (), {})()
        fake_repo.get_job = AsyncMock(return_value={
            "id": 9,
            "company_name": "历史公司",
            "job_title": "历史岗位",
            "asset_payload": {
                "custom_resume_id": 88,
                "custom_resume_preview": "用户历史简历内容",
                "greetings": [{"tone": "professional", "message_text": "历史文案"}],
            },
        })
        monkeypatch.setattr(jobs, "get_job_capture_repo", lambda: fake_repo)

        response = await jobs.JobsUseCases().get_job(job_id=9, user_id="user-1")

        payload = response.job["asset_payload"]
        assert payload["custom_resume_id"] == 88
        assert payload["custom_resume_preview"] == "用户历史简历内容"
        assert "greetings" not in payload
