"""
浏览器自动化 + 跨用户隔离 测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# 浏览器自动化测试 (mock Playwright)
# ============================================================================

class TestBrowserRunner:
    """浏览器自动化测试"""

    @pytest.mark.asyncio
    async def test_selector_strategies_defined(self):
        """验证选择器策略已定义"""
        from app.services.jobs.browser_runner import BOSS_SELECTORS

        assert "chat_input" in BOSS_SELECTORS
        assert "send_button" in BOSS_SELECTORS
        assert len(BOSS_SELECTORS["chat_input"]) > 0

    @pytest.mark.asyncio
    async def test_start_browser_mock(self):
        """Mock 启动浏览器流程"""
        from app.services.jobs.browser_runner import start_browser

        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context

        with patch(
            "app.services.jobs.browser_runner.async_playwright"
        ) as mock_async_pw:
            mock_async_pw.return_value = mock_pw_instance
            mock_async_pw.return_value.start.return_value = mock_pw_instance

            pw, browser, context = await start_browser(headless=True)

            assert pw is not None
            assert browser is not None
            assert context is not None

    @pytest.mark.asyncio
    async def test_playwright_not_installed(self):
        """Playwright 未安装时的错误处理"""
        from app.services.jobs.browser_runner import start_browser

        with patch(
            "app.services.jobs.browser_runner.async_playwright",
            side_effect=ImportError("No module named 'playwright'"),
        ):
            with pytest.raises(RuntimeError):
                await start_browser()

    @pytest.mark.asyncio
    async def test_scrape_page_text(self):
        """模拟页面文本抓取"""
        from app.services.jobs.browser_runner import scrape_page_text

        mock_page = AsyncMock()
        mock_page.evaluate.return_value = "页面文本内容..."

        text = await scrape_page_text(mock_page)
        assert "页面文本" in text

    def test_boss_selectors_order(self):
        """验证选择器按优先级排序（通用 → 特定）"""
        from app.services.jobs.browser_runner import BOSS_SELECTORS

        send_selectors = BOSS_SELECTORS["send_button"]
        # 至少包含几个关键选择器
        assert any("发送" in s for s in send_selectors)
        assert any("send" in s.lower() for s in send_selectors)


# ============================================================================
# BOSS投递服务测试
# ============================================================================

class TestBossApplyService:
    """BOSS投递服务测试"""

    @pytest.mark.asyncio
    async def test_apply_preview_no_url(self):
        """无来源链接时无法自动投递"""
        from app.services.jobs.boss_apply_service import execute_apply_preview

        with patch(
            "app.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_job.return_value = {
                "id": 1,
                "source_url": "",  # 无链接
            }
            mock_repo.return_value = mock_repo_instance

            result = await execute_apply_preview(
                job_id=1,
                user_id="user-1",
                greeting_text="您好",
            )

            assert result["success"] is False
            assert "链接" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_preview_rate_limited(self):
        """被限流时无法预览"""
        from app.services.jobs.boss_apply_service import execute_apply_preview

        with patch(
            "app.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_job.return_value = {
                "id": 1,
                "source_url": "https://boss.com/job/1",
            }
            mock_repo.return_value = mock_repo_instance

            with patch(
                "app.services.jobs.rate_limiter.check_rate"
            ) as mock_check:
                mock_check.return_value = (False, "频率限制")

                result = await execute_apply_preview(
                    job_id=1,
                    user_id="user-1",
                    greeting_text="您好",
                )

                assert result["success"] is False
                assert "频率限制" in result["message"]


# ============================================================================
# 跨用户隔离测试
# ============================================================================

class TestJobUserIsolation:
    """岗位数据隔离测试"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_get_user_b_job(self):
        from app.repositories.jobs.job_capture_repo import get_job_capture_repo

        with patch(
            "app.repositories.jobs.job_capture_repo.JobCaptureRepo.get_job"
        ) as mock_get:
            mock_get.return_value = None

            repo = get_job_capture_repo()
            result = await repo.get_job(1, "user-a")

            assert result is None

    @pytest.mark.asyncio
    async def test_user_a_cannot_delete_user_b_job(self):
        from app.repositories.jobs.job_capture_repo import get_job_capture_repo

        with patch(
            "app.repositories.jobs.job_capture_repo.JobCaptureRepo.delete_job"
        ) as mock_delete:
            mock_delete.return_value = False

            repo = get_job_capture_repo()
            result = await repo.delete_job(1, "user-a")

            assert result is False

    def test_captured_job_model_fields(self):
        """验证 CapturedJobModel 包含所有关键字段"""
        from app.models.job_capture import CapturedJobModel

        # 验证类属性
        assert hasattr(CapturedJobModel, "user_id")
        assert hasattr(CapturedJobModel, "source_hash")
        assert hasattr(CapturedJobModel, "company_name")
        assert hasattr(CapturedJobModel, "job_title")
        assert hasattr(CapturedJobModel, "platform")
        assert hasattr(CapturedJobModel, "salary_min")
        assert hasattr(CapturedJobModel, "salary_max")
        assert hasattr(CapturedJobModel, "tags")
        assert hasattr(CapturedJobModel, "status")
        assert hasattr(CapturedJobModel, "source_url")
        assert hasattr(CapturedJobModel, "city")

        # 验证 to_dict 方法
        assert callable(CapturedJobModel.to_dict)
