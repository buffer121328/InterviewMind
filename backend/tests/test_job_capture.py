"""
岗位采集测试

验证：URL采集、手动粘贴采集、标准化、去重检测
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


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
        from app.services.jobs.job_normalizer import normalize_company_name
        assert normalize_company_name("北京字节跳动科技有限公司") == "字节跳动"

    def test_normalize_company_name_nickname(self):
        from app.services.jobs.job_normalizer import normalize_company_name
        assert normalize_company_name("字节") == "字节跳动"

    def test_normalize_salary_range(self):
        from app.services.jobs.job_normalizer import normalize_salary
        result = normalize_salary("25K-40K")
        assert result["min"] == 25
        assert result["max"] == 40

    def test_normalize_salary_single(self):
        from app.services.jobs.job_normalizer import normalize_salary
        result = normalize_salary("20K以上")
        assert result["min"] == 20
        assert result["max"] is None

    def test_normalize_salary_wan(self):
        from app.services.jobs.job_normalizer import normalize_salary
        result = normalize_salary("1.5-2.5万")
        assert result["min"] == 15
        assert result["max"] == 25

    def test_normalize_salary_unparseable(self):
        from app.services.jobs.job_normalizer import normalize_salary
        result = normalize_salary("面议")
        assert result["text"] == "面议"
        assert result["min"] is None

    def test_extract_keywords(self):
        from app.services.jobs.job_normalizer import extract_keywords
        keywords = extract_keywords(MOCK_JD_TEXT)
        assert "Java" in keywords
        assert "Spring Boot" in keywords
        assert "Spring Cloud" in keywords
        assert "MySQL" in keywords
        assert "Redis" in keywords
        assert "Kafka" in keywords

    def test_extract_keywords_empty(self):
        from app.services.jobs.job_normalizer import extract_keywords
        assert extract_keywords("") == []

    def test_compute_source_hash_with_url(self):
        from app.services.jobs.job_normalizer import compute_source_hash
        h1 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/123")
        h2 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/123")
        assert h1 == h2  # 相同输入得到相同哈希

    def test_compute_source_hash_different(self):
        from app.services.jobs.job_normalizer import compute_source_hash
        h1 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/123")
        h2 = compute_source_hash("字节跳动", "Java", "https://boss.com/job/456")
        assert h1 != h2  # 不同URL得到不同哈希

    def test_compute_source_hash_no_url(self):
        from app.services.jobs.job_normalizer import compute_source_hash
        h1 = compute_source_hash("字节跳动", "Java", "", "boss")
        h2 = compute_source_hash("字节跳动", "Java", "", "boss")
        assert h1 == h2  # 相同company+title+platform得到相同哈希


class TestJobDeduper:
    """去重检测测试"""

    @pytest.mark.asyncio
    async def test_is_duplicate_true(self):
        from app.services.jobs.job_deduper import is_duplicate

        with patch(
            "app.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.find_by_hash.return_value = {"id": 1}
            mock_repo.return_value = mock_instance

            result = await is_duplicate("abc123", "user-1")
            assert result is True

    @pytest.mark.asyncio
    async def test_is_duplicate_false(self):
        from app.services.jobs.job_deduper import is_duplicate

        with patch(
            "app.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.find_by_hash.return_value = None
            mock_repo.return_value = mock_instance

            result = await is_duplicate("abc123", "user-1")
            assert result is False

    def test_similarity_exact_match(self):
        from app.services.jobs.job_deduper import _calculate_similarity
        sim = _calculate_similarity("字节跳动", "Java开发", "字节跳动", "Java开发")
        assert sim == 1.0

    def test_similarity_different(self):
        from app.services.jobs.job_deduper import _calculate_similarity
        sim = _calculate_similarity("字节跳动", "Java开发", "阿里巴巴", "Python开发")
        assert sim < 0.5


class TestJobCaptureService:
    """岗位采集服务测试"""

    @pytest.mark.asyncio
    async def test_capture_from_text_success(self):
        from app.services.jobs.job_capture_service import capture_from_text

        with patch(
            "app.services.jobs.job_capture_service.invoke_structured"
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
                "app.repositories.jobs.job_capture_repo.get_job_capture_repo"
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
        from app.services.jobs.job_capture_service import capture_from_text

        with patch(
            "app.services.jobs.job_capture_service.invoke_structured"
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
                "app.repositories.jobs.job_capture_repo.get_job_capture_repo"
            ) as mock_repo:
                mock_instance = AsyncMock()
                mock_instance.find_by_hash.return_value = {"id": 1}
                mock_repo.return_value = mock_instance

                result = await capture_from_text(
                    jd_text=MOCK_JD_TEXT,
                    user_id="user-1",
                )

                assert result["is_duplicate"] is True
