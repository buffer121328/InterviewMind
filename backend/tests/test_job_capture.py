"""
岗位采集测试

验证：URL采集、手动粘贴采集、标准化、去重检测
"""

import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

from app.db.models.agent_run import AgentRunModel


MOCK_JD_TEXT = """
【Java高级工程师】月薪25K-40K 北京

岗位职责：
1. 负责电商平台核心模块的架构设计和开发
2. 参与微服务架构演进和技术选型
3. 优化系统性能，提升高并发场景下的稳定性

任职要求：
1. 3年以上Java开发经验
2. 精通Spring Boot、Spring Cloud微服务架构
3. 熟悉MySQL、Redis、Kafka等中间件
4. 有高并发系统设计经验优先
"""


class TestJobNormalizer:
    """岗位标准化测试"""

    def test_normalize_company_name_simple(self):
        from integrations.boss.job_normalizer import normalize_company_name
        assert normalize_company_name("北京字节跳动科技有限公司") == "字节跳动"

    def test_normalize_company_name_nickname(self):
        from integrations.boss.job_normalizer import normalize_company_name
        assert normalize_company_name("字节") == "字节跳动"

    def test_normalize_salary_range(self):
        from integrations.boss.job_normalizer import normalize_salary
        result = normalize_salary("25K-40K")
        assert result["min"] == 25
        assert result["max"] == 40

    def test_normalize_salary_single(self):
        from integrations.boss.job_normalizer import normalize_salary
        result = normalize_salary("20K以上")
        assert result["min"] == 20
        assert result["max"] is None

    def test_normalize_salary_wan(self):
        from integrations.boss.job_normalizer import normalize_salary
        result = normalize_salary("1.5-2.5万")
        assert result["min"] == 15
        assert result["max"] == 25

    def test_normalize_salary_unparseable(self):
        from integrations.boss.job_normalizer import normalize_salary
        result = normalize_salary("面议")
        assert result["text"] == "面议"
        assert result["min"] is None

    def test_extract_keywords(self):
        from integrations.boss.job_normalizer import extract_keywords
        keywords = extract_keywords(MOCK_JD_TEXT)
        assert "Java" in keywords
        assert "Spring Boot" in keywords
        assert "Spring Cloud" in keywords
        assert "MySQL" in keywords
        assert "Redis" in keywords
        assert "Kafka" in keywords

    def test_extract_keywords_empty(self):
        from integrations.boss.job_normalizer import extract_keywords
        assert extract_keywords("") == []

    def test_compute_source_hash_with_url(self):
        from integrations.boss.job_normalizer import compute_source_hash
        h1 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/123")
        h2 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/123")
        assert h1 == h2  # 相同输入得到相同哈希

    def test_compute_source_hash_different(self):
        from integrations.boss.job_normalizer import compute_source_hash
        h1 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/123")
        h2 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/456")
        assert h1 != h2  # 不同URL得到不同哈希

    def test_compute_source_hash_no_url(self):
        from integrations.boss.job_normalizer import compute_source_hash
        h1 = compute_source_hash("字节跳动", "Java", "", "boss")
        h2 = compute_source_hash("字节跳动", "Java", "", "boss")
        assert h1 == h2  # 相同company+title+platform得到相同哈希


class TestJobDeduper:
    """去重检测测试"""

    @pytest.mark.asyncio
    async def test_is_duplicate_true(self):
        from ai.workflows.jobs_support.job_deduper import is_duplicate

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.find_by_hash.return_value = {"id": 1}
            mock_repo.return_value = mock_instance

            result = await is_duplicate("abc123", "user-1")
            assert result is True

    @pytest.mark.asyncio
    async def test_is_duplicate_false(self):
        from ai.workflows.jobs_support.job_deduper import is_duplicate

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.find_by_hash.return_value = None
            mock_repo.return_value = mock_instance

            result = await is_duplicate("abc123", "user-1")
            assert result is False

    def test_similarity_exact_match(self):
        from ai.workflows.jobs_support.job_deduper import _calculate_similarity
        sim = _calculate_similarity("字节跳动", "Java开发", "字节跳动", "Java开发")
        assert sim == 1.0

    def test_similarity_different(self):
        from ai.workflows.jobs_support.job_deduper import _calculate_similarity
        sim = _calculate_similarity("字节跳动", "Java开发", "阿里巴巴", "Python开发")
        assert sim < 0.5


class TestJobCaptureService:
    """岗位采集服务测试"""

    @pytest.mark.asyncio
    async def test_capture_from_text_success(self):
        from ai.workflows.jobs_support.job_capture_service import capture_from_text

        with patch(
            "ai.llm.llm_utils.invoke_structured",
            new=AsyncMock(),
        ) as mock_llm:
            mock_llm.return_value = MagicMock()
            mock_llm.return_value.model_dump.return_value = {
                "company_name": "北京字节跳动科技有限公司",
                "job_title": "Java高级工程师",
                "job_description": MOCK_JD_TEXT,
                "salary_text": "25K-40K",
                "city": "北京",
            }

            with patch(
                "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
            ) as mock_repo:
                mock_instance = AsyncMock()
                mock_instance.find_by_hash.return_value = None
                mock_instance.save_job.return_value = 1
                mock_repo.return_value = mock_instance

                result = await capture_from_text(
                    jd_text=MOCK_JD_TEXT,
                    user_id="user-1",
                )

                assert result["success"] is True
                assert result["is_duplicate"] is False
                assert result["normalized_job"]["company_name"] == "字节跳动"

    @pytest.mark.asyncio
    async def test_capture_from_text_duplicate(self):
        from ai.workflows.jobs_support.job_capture_service import capture_from_text

        with patch(
            "ai.llm.llm_utils.invoke_structured",
            new=AsyncMock(),
        ) as mock_llm:
            mock_llm.return_value = MagicMock()
            mock_llm.return_value.model_dump.return_value = {
                "company_name": "字节跳动",
                "job_title": "Java高级工程师",
                "job_description": "",
                "salary_text": "",
                "city": "",
            }

            with patch(
                "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
            ) as mock_repo:
                mock_instance = AsyncMock()
                mock_instance.find_by_hash.return_value = {"id": 1}
                mock_repo.return_value = mock_instance

                result = await capture_from_text(
                    jd_text=MOCK_JD_TEXT,
                    user_id="user-1",
                )

                assert result["is_duplicate"] is True

    @pytest.mark.asyncio
    async def test_browser_capture_uses_host_service(self):
        from ai.workflows.jobs_support.job_capture_service import _fetch_page_text_browser

        client = MagicMock()
        client.scrape = AsyncMock(
            return_value={"success": True, "text": "BOSS直聘 Python 招聘岗位" * 20}
        )

        with patch(
            "integrations.boss.automation_client.get_boss_automation_client",
            return_value=client,
        ):
            text = await _fetch_page_text_browser(
                "https://www.zhipin.com/web/geek/job",
                headless=False,
            )

        assert "BOSS直聘" in text
        client.scrape.assert_awaited_once_with(
            "https://www.zhipin.com/web/geek/job",
            headless=False,
            manual_wait_seconds=90,
        )

    @pytest.mark.asyncio
    async def test_recommendation_capture_no_longer_uses_applescript(self):
        from ai.workflows.jobs_support.job_capture_service import capture_from_recommendations

        with (
            patch(
                "ai.workflows.jobs_support.job_capture_service._fetch_page_text_browser",
                new=AsyncMock(return_value=""),
            ) as shared_capture,
            patch(
                "ai.workflows.jobs_support.job_capture_service._open_and_read_in_chrome",
                new=AsyncMock(side_effect=AssertionError("不应调用 AppleScript")),
            ),
        ):
            result = await capture_from_recommendations(
                user_id="user-1",
                query="Python",
                resume_content="resume",
                api_config={"smart": {"model": "mock"}},
            )

        assert result["success"] is False
        shared_capture.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recommendation_capture_enqueues_recoverable_asset_task(self, monkeypatch):
        from ai.workflows.jobs_support.job_capture_service import capture_from_recommendations
        from ai.runtime.agent_runs import service as run_service_module
        from ai.runtime.agent_runs import dispatcher

        card = SimpleNamespace(model_dump=lambda: {
            "company_name": "示例公司",
            "job_title": "Python 工程师",
            "salary_text": "20-30K",
            "city": "上海",
            "title_summary": "本科 3-5年",
            "job_description": "负责 Python 服务开发",
        })
        now = datetime.now()
        run = AgentRunModel(
            id="asset-run-1", user_id="user-1", task_type="job_assets", status="queued", stage="queued",
            idempotency_key="asset-key", payload_encrypted="encrypted", result=None, error_message=None,
            attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
        )
        create_or_get = AsyncMock(return_value=(run, True))
        monkeypatch.setattr(run_service_module, "task_queue_enabled", lambda: True)
        monkeypatch.setattr(run_service_module.AgentRunService, "create_or_get", create_or_get)
        monkeypatch.setattr(dispatcher, "enqueue_agent_run", MagicMock())

        with (
            patch(
                "ai.workflows.jobs_support.job_capture_service._fetch_page_text_browser",
                new=AsyncMock(return_value="BOSS直聘 Python 招聘 综合排序"),
            ),
            patch(
                "ai.llm.llm_utils.invoke_structured",
                new=AsyncMock(return_value=SimpleNamespace(cards=[card])),
            ),
            patch(
                "ai.workflows.jobs_support.job_capture_service.capture_from_text",
                new=AsyncMock(return_value={"success": True, "job_id": 7}),
            ),
        ):
            result = await capture_from_recommendations(
                user_id="user-1",
                query="Python",
                resume_content="候选人简历",
                api_config={"smart": {"model": "mock"}},
                top_n=1,
            )

        assert result["success"] is True
        assert result["jobs"][0]["asset_run_id"] == "asset-run-1"
        assert result["jobs"][0]["asset_status"] == "queued"
        create_or_get.assert_awaited_once()
