"""
岗位采集测试

验证：BOSS 当前页 DOM 导入、标准化、去重检测
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.db.models.agent_run import AgentRunModel
from pydantic import ValidationError

VALID_BOSS_SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent"


def make_imported_card(index: int = 1) -> dict[str, str]:
    """Build one bounded official BOSS card for DOM-import tests."""
    return {
        "company_name": f"示例科技 {index}",
        "company_size_text": "100-499人",
        "job_title": f"Agent 工程师 {index}",
        "salary_text": "20-30K",
        "city": "深圳",
        "title_summary": "3-5年 本科",
        "job_description": "负责 Agent 产品及 Python 服务端开发工作",
        "source_url": f"https://www.zhipin.com/job_detail/card_{index}-real.html",
    }


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


@pytest.fixture(autouse=True)
def _backend_capture_log_dir(monkeypatch, tmp_path):
    """Keep backend-only capture logs isolated per test."""
    from app.config import get_settings

    monkeypatch.setenv("ARTIFACT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
        from ai.workflows.jobs.job_deduper import is_duplicate

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
        from ai.workflows.jobs.job_deduper import is_duplicate

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.find_by_hash.return_value = None
            mock_repo.return_value = mock_instance

            result = await is_duplicate("abc123", "user-1")
            assert result is False

    def test_similarity_exact_match(self):
        from ai.workflows.jobs.job_deduper import _calculate_similarity
        sim = _calculate_similarity("字节跳动", "Java开发", "字节跳动", "Java开发")
        assert sim == 1.0

    def test_similarity_different(self):
        from ai.workflows.jobs.job_deduper import _calculate_similarity
        sim = _calculate_similarity("字节跳动", "Java开发", "阿里巴巴", "Python开发")
        assert sim < 0.5


class TestJobCaptureService:
    """岗位采集服务测试"""

    @pytest.mark.asyncio
    async def test_dom_import_never_calls_browser_search(self):
        """Recommendation import must use only supplied cards and never open a browser."""
        from ai.workflows.jobs import job_capture_service

        progress_stages: list[str] = []

        async def progress(stage: str) -> None:
            """Record public AgentRun progress for the import assertion."""
            progress_stages.append(stage)

        normalize_job = AsyncMock(return_value={"success": True, "job_id": 7})
        score_cards = AsyncMock(side_effect=lambda **kwargs: kwargs["cards"])
        with (
            patch(
                "ai.workflows.jobs.job_capture_service._normalize_and_save",
                new=normalize_job,
            ),
            patch(
                "ai.workflows.jobs.job_capture_service._score_job_cards_by_match",
                new=score_cards,
            ),
            patch(
                "ai.runtime.agent_runs.service.task_queue_enabled",
                return_value=False,
            ),
            patch(
                "ai.workflows.jobs.job_asset_orchestrator.generate_assets",
                new=AsyncMock(return_value={"success": False}),
            ),
        ):
            result = await job_capture_service.capture_from_imported_cards(
                user_id="user-1",
                query="Agent",
                resume_content="候选人简历",
                imported_cards=[{
                    **make_imported_card(),
                    "company_size_text": "已上市 人工智能 100-499人",
                }],
                source_page_url=VALID_BOSS_SEARCH_URL,
                api_config={"smart": {"model": "mock"}},
                top_n=1,
                progress=progress,
            )

        assert not hasattr(job_capture_service, "_fetch_boss_search_page_browser")
        assert result["success"] is True
        assert result["jobs"][0]["source_url"].endswith("card_1-real.html")
        assert progress_stages == [
            "validating_import",
            "extracting_jobs",
            "ranking_jobs",
            "awaiting_import",
        ]
        normalize_job.assert_not_awaited()
        assert result["jobs"][0]["job_id"] is None
        assert result["jobs"][0]["pending_import"] is True

    @pytest.mark.asyncio
    async def test_dom_import_rejects_external_and_navigation_cards(self):
        """External links and navigation-like rows must not reach persistence."""
        from ai.workflows.jobs import job_capture_service

        external = {
            **make_imported_card(),
            "source_url": "https://example.com/job_detail/card1.html",
        }
        navigation = {
            **make_imported_card(2),
            "company_name": "",
            "job_title": "职位搜索",
            "salary_text": "",
            "job_description": "职位搜索 BOSS直聘APP 投资者关系",
        }
        normalize_job = AsyncMock()
        with patch(
            "ai.workflows.jobs.job_capture_service._normalize_and_save",
            new=normalize_job,
        ):
            result = await job_capture_service.capture_from_imported_cards(
                user_id="user-1",
                query="Agent",
                resume_content="候选人简历",
                imported_cards=[external, navigation],
                source_page_url=VALID_BOSS_SEARCH_URL,
                api_config={"smart": {"model": "mock"}},
            )

        assert result["success"] is False
        assert result["total"] == 0
        normalize_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dom_import_reads_at_most_twenty_candidates(self):
        """Service-side bounds must hold even when a caller bypasses request validation."""
        from ai.workflows.jobs import job_capture_service

        normalize_job = AsyncMock(return_value={"success": True, "job_id": 7})
        score_cards = AsyncMock(side_effect=lambda **kwargs: kwargs["cards"])
        with (
            patch(
                "ai.workflows.jobs.job_capture_service._normalize_and_save",
                new=normalize_job,
            ),
            patch(
                "ai.workflows.jobs.job_capture_service._score_job_cards_by_match",
                new=score_cards,
            ),
            patch(
                "ai.runtime.agent_runs.service.task_queue_enabled",
                return_value=False,
            ),
            patch(
                "ai.workflows.jobs.job_asset_orchestrator.generate_assets",
                new=AsyncMock(return_value={"success": False}),
            ),
        ):
            result = await job_capture_service.capture_from_imported_cards(
                user_id="user-1",
                query="Agent",
                resume_content="候选人简历",
                imported_cards=[make_imported_card(index) for index in range(1, 22)],
                source_page_url=VALID_BOSS_SEARCH_URL,
                api_config={"smart": {"model": "mock"}},
                top_n=20,
            )

        assert result["total"] == 20
        normalize_job.assert_not_awaited()
        assert all("card_21-real.html" not in item["source_url"] for item in result["jobs"])

    @pytest.mark.asyncio
    async def test_dom_import_ranks_before_applying_top_n(self):
        """The imported cards must keep the existing resume-match ranking boundary."""
        from ai.workflows.jobs import job_capture_service

        cards = [make_imported_card(index) for index in range(1, 4)]
        ranked = [cards[2], cards[0], cards[1]]
        score_cards = AsyncMock(return_value=ranked)
        normalize_job = AsyncMock(return_value={"success": True, "job_id": 7})
        with (
            patch(
                "ai.workflows.jobs.job_capture_service._score_job_cards_by_match",
                new=score_cards,
            ),
            patch(
                "ai.workflows.jobs.job_capture_service._normalize_and_save",
                new=normalize_job,
            ),
            patch(
                "ai.runtime.agent_runs.service.task_queue_enabled",
                return_value=False,
            ),
            patch(
                "ai.workflows.jobs.job_asset_orchestrator.generate_assets",
                new=AsyncMock(return_value={"success": False}),
            ),
        ):
            result = await job_capture_service.capture_from_imported_cards(
                user_id="user-1",
                query="Agent",
                resume_content="候选人简历",
                imported_cards=cards,
                source_page_url=VALID_BOSS_SEARCH_URL,
                api_config={"smart": {"model": "mock"}},
                top_n=2,
            )

        score_cards.assert_awaited_once()
        assert [job["job_title"] for job in result["jobs"]] == [
            "Agent 工程师 3",
            "Agent 工程师 1",
        ]

    @pytest.mark.asyncio
    async def test_persistence_rejects_empty_or_navigation_job(self):
        """The shared persistence boundary rejects malformed jobs from any collector."""
        from ai.workflows.jobs.job_capture_persistence import (
            normalize_and_save_job,
        )

        result = await normalize_and_save_job(
            {
                "company_name": "",
                "job_title": "职位搜索",
                "job_description": "",
                "salary_text": "",
                "city": "",
            },
            user_id="user-1",
            platform="boss",
            source_text="职位搜索 BOSS直聘APP 投资者关系",
        )

        assert result == {
            "success": False,
            "message": "岗位信息不完整：未识别到有效岗位标题或 JD，已拒绝入库",
            "is_duplicate": False,
        }

    @pytest.mark.asyncio
    async def test_dom_import_writes_backend_txt_without_returning_logs(self, tmp_path):
        """Import audit text stays server-side and public results contain no raw logs."""
        from ai.workflows.jobs import job_capture_service

        result = await job_capture_service.capture_from_imported_cards(
            user_id="user-1",
            query="Agent",
            resume_content="resume",
            imported_cards=[{
                **make_imported_card(),
                "source_url": "https://example.com/job_detail/card1.html",
            }],
            source_page_url=VALID_BOSS_SEARCH_URL,
            api_config={"smart": {"model": "mock"}},
            run_id="capture-run-1",
        )

        log_path = tmp_path / "job-capture-logs" / "job-capture-capture-run-1.txt"
        assert log_path.exists()
        log_text = log_path.read_text(encoding="utf-8")
        assert "校验当前 BOSS 页面导入" in log_text
        assert "已拒绝 1 张" in log_text
        assert "logs" not in result


def test_dom_import_request_requires_official_bounded_cards():
    """The API schema accepts 1-20 official cards and rejects the browser-era contract."""
    from app.schemas.job_schemas import CaptureRecommendationsRequest

    base = {
        "query": "Agent",
        "resume_content": "candidate resume",
        "source_page_url": VALID_BOSS_SEARCH_URL,
        "cards": [make_imported_card()],
    }
    request = CaptureRecommendationsRequest(**base)

    assert request.top_n == 3
    assert len(request.cards) == 1
    assert request.cards[0].source_url.endswith("card_1-real.html")
    assert CaptureRecommendationsRequest(**base, top_n=20).top_n == 20
    with pytest.raises(ValidationError):
        CaptureRecommendationsRequest(**{**base, "cards": []})
    with pytest.raises(ValidationError):
        CaptureRecommendationsRequest(
            **{**base, "cards": [make_imported_card(index) for index in range(1, 22)]}
        )
    with pytest.raises(ValidationError):
        CaptureRecommendationsRequest(
            **{**base, "source_page_url": "https://example.com/web/geek/jobs"}
        )
    with pytest.raises(ValidationError):
        CaptureRecommendationsRequest(
            **{
                **base,
                "cards": [{
                    **make_imported_card(),
                    "source_url": "https://example.com/job_detail/card1.html",
                }],
            }
        )
    with pytest.raises(ValidationError):
        CaptureRecommendationsRequest(**base, browser_channel="chrome")


def test_existing_tab_capture_request_requires_query_and_numeric_city_code():
    """The browser-control API trims a real query and rejects arbitrary city text."""
    from app.schemas.job_schemas import BossTabCaptureRequest

    request = BossTabCaptureRequest(query="  AI Agent  ", city="101280600")

    assert request.query == "AI Agent"
    assert request.city == "101280600"
    with pytest.raises(ValidationError):
        BossTabCaptureRequest(query="   ")
    with pytest.raises(ValidationError):
        BossTabCaptureRequest(query="AI Agent", city="深圳")


@pytest.mark.asyncio
async def test_resume_keyword_fallback_ranks_relevant_job_when_model_scoring_fails(monkeypatch):
    """Fast 模型不可用时仍按基础简历与岗位的透明关键词重合度排序。"""
    from ai.llm import llms
    from ai.workflows.jobs.job_capture_service import _score_job_cards_by_match

    cards = [
        {
            **make_imported_card(1),
            "job_title": "Python Agent 后端工程师",
            "job_description": "负责 Python Django FastAPI Agent Redis 与 Docker 服务开发",
        },
        {
            **make_imported_card(2),
            "job_title": "Java 客户端工程师",
            "job_description": "负责 Java Spring Android 客户端开发",
        },
    ]
    monkeypatch.setattr(
        llms,
        "invoke_text",
        AsyncMock(side_effect=RuntimeError("model unavailable")),
    )
    monkeypatch.setattr(
        "ai.prompts.jobs.build_job_card_scoring_prompt",
        lambda **_kwargs: "bounded scoring prompt",
    )

    ranked = await _score_job_cards_by_match(
        cards,
        resume_content="熟悉 Python、Django、FastAPI、Agent、Redis、Docker",
        query="Agent 后端工程师",
        api_config={"fast": {"model": "mock"}},
    )

    assert ranked[0]["job_title"] == "Python Agent 后端工程师"
    assert ranked[0]["preliminary_match_score"] > ranked[1]["preliminary_match_score"]


@pytest.mark.asyncio
async def test_dom_import_filters_internships_before_persistence():
    """标题或职位介绍包含实习标记的卡片不得进入岗位库。"""
    from ai.workflows.jobs.job_capture_service import capture_from_imported_cards

    normalize_job = AsyncMock(return_value={"success": True, "job_id": 7})
    with patch(
        "ai.workflows.jobs.job_capture_service._normalize_and_save",
        new=normalize_job,
    ):
        result = await capture_from_imported_cards(
            user_id="user-1",
            query="Agent",
            resume_content="Python Agent",
            imported_cards=[{**make_imported_card(), "job_title": "Agent 实习生"}],
            source_page_url=VALID_BOSS_SEARCH_URL,
            api_config={"smart": {"model": "mock"}},
        )

    assert result["success"] is False
    assert result["total"] == 0
    normalize_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_normalize_persistence_preserves_salary_company_size_and_match_score():
    """DOM 已校验强字段应直接持久化，不得再被二次 LLM 抽取覆盖。"""
    from ai.workflows.jobs.job_capture_persistence import normalize_and_save_job

    fake_repo = MagicMock()
    fake_repo.find_by_hash = AsyncMock(return_value=None)
    fake_repo.save_job = AsyncMock(return_value=91)
    with patch(
        "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo",
        return_value=fake_repo,
    ):
        result = await normalize_and_save_job(
            {
                **make_imported_card(),
                "preliminary_match_score": 86.5,
            },
            user_id="user-1",
            platform="boss",
            source_url=make_imported_card()["source_url"],
            source_text=make_imported_card()["job_description"],
        )

    assert result["success"] is True
    saved = fake_repo.save_job.await_args.kwargs["job_data"]
    assert saved["salary_text"] == "20-30K"
    assert saved["company_size_text"] == "100-499人"
    assert saved["match_score"] == 86.5
