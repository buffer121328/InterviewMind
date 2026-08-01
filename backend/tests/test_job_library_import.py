"""
岗位一键入库测试

验证：待入库卡片保存进岗位库、去重、资产任务调度、部分失败明细与输入边界。
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.db.models.agent_run import AgentRunModel

VALID_BOSS_SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent"


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


class TestImportSavesAndSchedules:
    """一键入库：保存岗位并调度可恢复资产任务。"""

    @pytest.mark.asyncio
    async def test_import_saves_jobs_and_enqueues_recoverable_asset_tasks(self, monkeypatch):
        """每个成功入库的岗位都应创建 job_assets 可恢复任务并记录资产跟踪。"""
        from ai.runtime.agent_runs import outbox
        from ai.runtime.agent_runs import service as run_service_module
        from ai.workflows.jobs.job_capture_service import import_cards_to_library

        now = datetime.now()
        run = AgentRunModel(
            id="asset-run-1",
            user_id="user-1",
            task_type="job_assets",
            status="queued",
            stage="queued",
            idempotency_key="asset-key",
            payload_encrypted="encrypted",
            result=None,
            error_message=None,
            attempts=0,
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=None,
        )
        create_or_get = AsyncMock(return_value=(run, True))
        monkeypatch.setattr(run_service_module, "task_queue_enabled", lambda: True)
        monkeypatch.setattr(
            run_service_module.AgentRunService,
            "create_or_get",
            create_or_get,
        )
        dispatch_pending = AsyncMock(return_value=(1, 0))
        monkeypatch.setattr(outbox, "dispatch_pending_outbox", dispatch_pending)

        fake_job_repo = MagicMock()
        fake_job_repo.update_asset_tracking = AsyncMock(return_value=True)
        with (
            patch(
                "ai.workflows.jobs.job_capture_service._normalize_and_save",
                new=AsyncMock(return_value={"success": True, "job_id": 7}),
            ),
            patch(
                "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo",
                return_value=fake_job_repo,
            ),
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[make_imported_card()],
                resume_content="候选人简历",
                api_config={"smart": {"model": "mock"}, "fast": {"model": "mock"}},
            )

        assert result["success"] is True
        assert result["total"] == 1
        assert result["duplicates"] == 0
        assert result["jobs"][0]["job_id"] == 7
        assert result["jobs"][0]["asset_run_id"] == "asset-run-1"
        assert result["jobs"][0]["asset_status"] == "queued"
        assert result["jobs"][0]["match_score"] == 86.5
        create_or_get.assert_awaited_once()
        dispatch_pending.assert_awaited_once_with(limit=50)
        fake_job_repo.update_asset_tracking.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_reuses_existing_job_and_counts_duplicate(self):
        """按来源哈希去重：重复卡片复用岗位库记录，不再重复入库。"""
        from ai.workflows.jobs.job_capture_service import import_cards_to_library

        with patch(
            "ai.workflows.jobs.job_capture_service._normalize_and_save",
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
                resume_content="候选人简历",
                api_config={"smart": {"model": "mock"}},
            )

        assert result["success"] is True
        assert result["total"] == 1
        assert result["duplicates"] == 1
        assert result["jobs"][0]["job_id"] == 3


class TestImportFailures:
    """一键入库失败与部分失败语义。"""

    @pytest.mark.asyncio
    async def test_import_partial_failure_keeps_failed_details(self):
        """部分卡片保存失败时返回失败明细，且失败卡片不进入 jobs。"""
        from ai.workflows.jobs.job_capture_service import import_cards_to_library

        def fake_save(card, _user_id, _platform, source_url="", source_text=""):
            if card["job_title"].endswith("2"):
                return {"success": False, "message": "岗位信息不完整"}
            return {"success": True, "job_id": 7}

        with patch(
            "ai.workflows.jobs.job_capture_service._normalize_and_save",
            new=AsyncMock(side_effect=fake_save),
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[make_imported_card(1), make_imported_card(2)],
                resume_content="候选人简历",
                api_config={"smart": {"model": "mock"}},
            )

        assert result["total"] == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["job_title"] == "Agent 工程师 2"
        assert result["failed"][0]["source_url"] == make_imported_card(2)["source_url"]
        assert result["failed"][0]["reason"] == "岗位信息不完整"

    @pytest.mark.asyncio
    async def test_import_rejects_invalid_cards_without_saving(self):
        """外部域名或无效卡片在入库边界被拒绝，不触发任何保存。"""
        from ai.workflows.jobs.job_capture_service import import_cards_to_library

        normalize_job = AsyncMock()
        with patch(
            "ai.workflows.jobs.job_capture_service._normalize_and_save",
            new=normalize_job,
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[{
                    **make_imported_card(),
                    "source_url": "https://example.com/job_detail/card1.html",
                }],
                resume_content="候选人简历",
                api_config={"smart": {"model": "mock"}},
            )

        assert result["success"] is False
        assert result["total"] == 0
        normalize_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_import_filters_internship_cards(self):
        """实习标记卡片不得入库。"""
        from ai.workflows.jobs.job_capture_service import import_cards_to_library

        normalize_job = AsyncMock()
        with patch(
            "ai.workflows.jobs.job_capture_service._normalize_and_save",
            new=normalize_job,
        ):
            result = await import_cards_to_library(
                user_id="user-1",
                cards=[{**make_imported_card(), "job_title": "Agent 实习生"}],
                resume_content="Python Agent",
                api_config={"smart": {"model": "mock"}},
            )

        assert result["success"] is False
        assert result["total"] == 0
        normalize_job.assert_not_awaited()


class TestImportBoundaries:
    """入库请求的 schema 与用例边界。"""

    def test_import_request_requires_one_to_twenty_official_cards(self):
        """请求只接受 1-20 张 BOSS 官方岗位链接卡片，越界直接拒绝。"""
        from app.schemas.job_schemas import JobLibraryImportRequest

        base = {
            "resume_content": "candidate resume",
            "cards": [make_imported_card()],
        }
        request = JobLibraryImportRequest(**base)
        assert len(request.cards) == 1
        assert request.cards[0].preliminary_match_score == 86.5
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

    @pytest.mark.asyncio
    async def test_import_use_case_requires_api_config(self):
        """缺少模型通道配置时用例直接拒绝，不触达服务层。"""
        from app.schemas.job_schemas import JobLibraryImportRequest
        from ai.workflows.jobs import JobBadRequest, jobs_use_cases

        request = JobLibraryImportRequest(
            resume_content="candidate resume",
            cards=[make_imported_card()],
        )
        assert request.api_config is None
        with pytest.raises(JobBadRequest):
            await jobs_use_cases.import_cards_to_library(
                request=request,
                user_id="user-1",
            )

    @pytest.mark.asyncio
    async def test_import_use_case_passes_cards_to_service(self):
        """用例把 schema 卡片原样交给服务层，并透传简历与城市。"""
        from app.schemas.job_schemas import JobLibraryImportRequest
        from ai.workflows.jobs import jobs_use_cases

        request = JobLibraryImportRequest(
            resume_content="candidate resume",
            city="101280600",
            cards=[make_imported_card()],
            api_config={"smart": {"model": "mock"}, "fast": {"model": "mock"}},
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
            "ai.workflows.jobs.job_capture_service.import_cards_to_library",
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
            resume_content="candidate resume",
            api_config=request.api_config,
            city="101280600",
        )
