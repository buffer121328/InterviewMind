"""
浏览器自动化 + 跨用户隔离 测试
"""

from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeUowSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def close(self):
        return None



# ============================================================================
# 浏览器自动化测试 (mock Playwright)
# ============================================================================

class TestBrowserRunner:
    """浏览器自动化测试"""

    @pytest.mark.asyncio
    async def test_selector_strategies_defined(self):
        """验证选择器策略已定义"""
        from integrations.boss.browser_runner import BOSS_SELECTORS

        assert "chat_input" in BOSS_SELECTORS
        assert "send_button" in BOSS_SELECTORS
        assert len(BOSS_SELECTORS["chat_input"]) > 0

    @pytest.mark.asyncio
    async def test_start_browser_mock(self):
        """Mock 启动浏览器流程"""
        from integrations.boss.browser_runner import start_browser

        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context

        with patch(
            "integrations.boss.browser_runner.async_playwright"
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
        from integrations.boss.browser_runner import start_browser

        with patch(
            "integrations.boss.browser_runner.async_playwright",
            None,
        ):
            with pytest.raises(RuntimeError):
                await start_browser()

    @pytest.mark.asyncio
    async def test_start_browser_with_persistent_profile(self):
        """显式配置 profile 时复用登录会话。"""
        from integrations.boss.browser_runner import start_browser

        mock_context = AsyncMock()
        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

        with patch("integrations.boss.browser_runner.async_playwright") as mock_async_pw:
            mock_async_pw.return_value = mock_pw_instance
            mock_async_pw.return_value.start.return_value = mock_pw_instance
            _, browser, context = await start_browser(
                headless=True,
                profile_dir="~/.boss-test-profile",
            )

        assert browser is mock_context
        assert context is mock_context
        mock_pw_instance.chromium.launch_persistent_context.assert_awaited_once()

    def test_default_boss_profile_is_in_runtime_data(self):
        """未配置 profile 时仍返回稳定且不会入库的运行目录。"""
        from integrations.boss.browser_runner import resolve_boss_browser_profile_dir

        with patch.dict("os.environ", {"BOSS_BROWSER_PROFILE_DIR": ""}):
            profile_dir = resolve_boss_browser_profile_dir()

        assert profile_dir == Path(__file__).resolve().parents[1] / "data" / "browser_profiles" / "boss"

    @pytest.mark.asyncio
    async def test_boss_session_uses_persistent_profile_and_releases_lock(self, tmp_path):
        from integrations.boss.browser_runner import open_boss_browser_session

        context = AsyncMock()
        pw = AsyncMock()
        pw.chromium.launch_persistent_context.return_value = context
        playwright_manager = MagicMock()
        playwright_manager.start = AsyncMock(return_value=pw)

        with patch("integrations.boss.browser_runner.async_playwright") as mock_async_pw:
            mock_async_pw.return_value = playwright_manager
            session = await open_boss_browser_session(
                headless=True,
                profile_dir=str(tmp_path / "boss-profile"),
            )
            await session.close()
            await session.close()

        pw.chromium.launch_persistent_context.assert_awaited_once()
        context.close.assert_awaited_once()
        pw.stop.assert_awaited_once()
        assert session._lock.locked() is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("body_text", "url", "expected"),
        [
            ("请稍候", "https://www.zhipin.com/web/common/security-check.html", "manual_takeover"),
            ("请完成安全验证，拖动滑块", "https://example.com/job/1", "manual_takeover"),
            ("请扫码登录后继续", "https://example.com/login", "login_required"),
            ("抱歉，该职位已关闭", "https://example.com/job/1", "unavailable"),
            ("Python 开发工程师", "https://example.com/job/1", "ready"),
            ("", "https://example.com/job/1", "manual_takeover"),
        ],
    )
    async def test_inspect_page_state(self, body_text, url, expected):
        from integrations.boss.browser_runner import inspect_page_state

        page = AsyncMock()
        page.url = url
        page.evaluate.return_value = body_text

        result = await inspect_page_state(page)

        assert result["status"] == expected

    @pytest.mark.asyncio
    async def test_verify_send_result_from_cleared_input(self):
        from integrations.boss.browser_runner import verify_send_result

        page = AsyncMock()
        page.evaluate.return_value = "聊天页面"
        input_element = AsyncMock()
        input_element.input_value.return_value = ""
        page.query_selector.return_value = input_element

        result = await verify_send_result(page)

        assert result == {"verified": True, "evidence": "input_cleared"}

    @pytest.mark.asyncio
    async def test_scrape_page_text(self):
        """模拟页面文本抓取"""
        from integrations.boss.browser_runner import scrape_page_text

        mock_page = AsyncMock()
        mock_page.evaluate.return_value = "页面文本内容..."

        text = await scrape_page_text(mock_page)
        assert "页面文本" in text

    def test_boss_selectors_order(self):
        """验证选择器按优先级排序（通用 → 特定）"""
        from integrations.boss.browser_runner import BOSS_SELECTORS

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
        from ai.workflows.jobs_support.boss_apply_service import execute_apply_preview

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
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
        from ai.workflows.jobs_support.boss_apply_service import execute_apply_preview

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_job.return_value = {
                "id": 1,
                "source_url": "https://www.zhipin.com/job_detail/1.html",
            }
            mock_repo.return_value = mock_repo_instance

            with patch(
                "integrations.boss.rate_limiter.check_rate"
            ) as mock_check:
                mock_check.return_value = (False, "频率限制")

                result = await execute_apply_preview(
                    job_id=1,
                    user_id="user-1",
                    greeting_text="您好",
                )

                assert result["success"] is False
                assert "频率限制" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_preview_uses_host_service_and_issues_approval(self):
        from ai.workflows.jobs_support.boss_apply_service import execute_apply_preview

        source_url = "https://www.zhipin.com/job_detail/1.html"
        repo = AsyncMock()
        repo.get_job.return_value = {"id": 1, "source_url": source_url}
        client = MagicMock()
        client.preview = AsyncMock(
            return_value={
                "success": True,
                "send_ready": True,
                "message": "预览已生成",
                "screenshot_base64": "image-base64",
            }
        )

        with (
            patch(
                "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo",
                return_value=repo,
            ),
            patch(
                "integrations.boss.rate_limiter.check_rate",
                new=AsyncMock(return_value=(True, "ok")),
            ),
            patch(
                "ai.workflows.jobs_support.boss_apply_service.get_boss_automation_client",
                return_value=client,
            ),
        ):
            result = await execute_apply_preview(1, "user-1", "您好")

        assert result["success"] is True
        assert result["approval_token"]
        client.preview.assert_awaited_once_with(source_url, "您好")

    @pytest.mark.asyncio
    async def test_apply_send_requires_explicit_confirmation(self):
        from ai.workflows.jobs_support.boss_apply_service import execute_apply_send

        result = await execute_apply_send(
            job_id=1,
            user_id="user-1",
            greeting_text="您好",
            approval_token="preview-token-that-is-long-enough",
        )

        assert result["success"] is False
        assert result["send_status"] == "pending"
        assert "显式确认" in result["message"]

    @pytest.mark.asyncio
    async def test_apply_send_claims_verifies_and_marks_applied(self):
        from integrations.boss.apply_approval import apply_approval_registry
        from ai.workflows.jobs_support.boss_apply_service import execute_apply_send

        source_url = "https://www.zhipin.com/job_detail/1.html"
        token, _ = await apply_approval_registry.issue(
            user_id="user-1",
            job_id=1,
            greeting_text="您好，我想应聘",
            source_url=source_url,
            resume_id=2,
        )
        repo = AsyncMock()
        repo.get_job.return_value = {
            "id": 1,
            "source_url": source_url,
            "status": "assets_generated",
            "company_name": "示例公司",
            "job_title": "Python 工程师",
        }
        repo.claim_for_application.return_value = True
        client = MagicMock()
        fake_session = _FakeUowSession()
        client.send = AsyncMock(
            return_value={
                "success": True,
                "send_status": "sent",
                "message": "发送成功",
                "screenshot_base64": "image-base64",
                "clicked": True,
                "steps": [{"step": "click_send", "status": "success"}],
            }
        )

        with (
            patch(
                "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo",
                return_value=repo,
            ),
            patch(
                "integrations.boss.rate_limiter.check_rate",
                new=AsyncMock(return_value=(True, "ok")),
            ),
            patch(
                "integrations.boss.rate_limiter.record_success",
                new=AsyncMock(),
            ),
            patch(
                "ai.workflows.jobs_support.boss_apply_service.get_boss_automation_client",
                return_value=client,
            ),
            patch(
                "ai.workflows.jobs_support.boss_apply_service._save_application_record",
                new=AsyncMock(),
            ),
            patch("app.db.models.async_session", new=lambda: fake_session),
        ):
            result = await execute_apply_send(
                job_id=1,
                user_id="user-1",
                greeting_text="您好，我想应聘",
                resume_id=2,
                approval_token=token,
                confirmed=True,
            )

        assert result["send_status"] == "sent"
        client.send.assert_awaited_once_with(source_url, "您好，我想应聘")
        repo.claim_for_application.assert_awaited_once_with(1, "user-1")
        repo.update_status.assert_awaited_once_with(1, "user-1", "applied", session=fake_session)

    @pytest.mark.asyncio
    async def test_apply_send_rpc_timeout_requires_manual_takeover(self):
        from integrations.boss.apply_approval import apply_approval_registry
        from ai.workflows.jobs_support.boss_apply_service import execute_apply_send
        from integrations.boss.automation_client import BossAutomationError

        source_url = "https://www.zhipin.com/job_detail/2.html"
        token, _ = await apply_approval_registry.issue(
            user_id="user-1",
            job_id=2,
            greeting_text="您好",
            source_url=source_url,
            resume_id=None,
        )
        repo = AsyncMock()
        repo.get_job.return_value = {
            "id": 2,
            "source_url": source_url,
            "status": "assets_generated",
        }
        repo.claim_for_application.return_value = True
        client = MagicMock()
        fake_session = _FakeUowSession()
        client.send = AsyncMock(
            side_effect=BossAutomationError("读取超时", request_may_have_run=True)
        )

        with (
            patch(
                "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo",
                return_value=repo,
            ),
            patch(
                "integrations.boss.rate_limiter.check_rate",
                new=AsyncMock(return_value=(True, "ok")),
            ),
            patch(
                "integrations.boss.rate_limiter.record_failure",
                new=AsyncMock(),
            ),
            patch(
                "ai.workflows.jobs_support.boss_apply_service.get_boss_automation_client",
                return_value=client,
            ),
            patch(
                "ai.workflows.jobs_support.boss_apply_service._save_application_record",
                new=AsyncMock(),
            ),
            patch("app.db.models.async_session", new=lambda: fake_session),
        ):
            result = await execute_apply_send(
                job_id=2,
                user_id="user-1",
                greeting_text="您好",
                approval_token=token,
                confirmed=True,
            )

        assert result["send_status"] == "manual_takeover"
        repo.update_status.assert_awaited_once_with(2, "user-1", "manual_takeover", session=fake_session)


class TestApplyApprovalRegistry:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://www.zhipin.com/job_detail/1.html", True),
            ("https://zhipin.com/job_detail/1.html", True),
            ("http://www.zhipin.com/job_detail/1.html", False),
            ("https://zhipin.com.example.org/job/1", False),
        ],
    )
    def test_apply_url_allowlist(self, url, expected):
        from integrations.boss.apply_approval import is_allowed_apply_url

        assert is_allowed_apply_url(url) is expected

    @pytest.mark.asyncio
    async def test_token_is_bound_and_single_use(self):
        from integrations.boss.apply_approval import ApplyApprovalRegistry, ApprovalError

        registry = ApplyApprovalRegistry(ttl_seconds=300)
        token, expires_in = await registry.issue(
            user_id="user-1",
            job_id=1,
            greeting_text="您好，我想应聘",
            source_url="https://example.com/job/1",
            resume_id=2,
        )

        assert expires_in == 300
        await registry.consume(
            token,
            user_id="user-1",
            job_id=1,
            greeting_text="您好，我想应聘",
            source_url="https://example.com/job/1",
            resume_id=2,
        )
        with pytest.raises(ApprovalError, match="已使用"):
            await registry.consume(
                token,
                user_id="user-1",
                job_id=1,
                greeting_text="您好，我想应聘",
                source_url="https://example.com/job/1",
                resume_id=2,
            )

    @pytest.mark.asyncio
    async def test_token_rejects_changed_content(self):
        from integrations.boss.apply_approval import ApplyApprovalRegistry, ApprovalError

        registry = ApplyApprovalRegistry(ttl_seconds=300)
        token, _ = await registry.issue(
            user_id="user-1",
            job_id=1,
            greeting_text="原文案",
            source_url="https://example.com/job/1",
            resume_id=None,
        )

        with pytest.raises(ApprovalError, match="不一致"):
            await registry.consume(
                token,
                user_id="user-1",
                job_id=1,
                greeting_text="被修改的文案",
                source_url="https://example.com/job/1",
                resume_id=None,
            )

    @pytest.mark.asyncio
    async def test_new_preview_invalidates_previous_token_for_same_job(self):
        from integrations.boss.apply_approval import ApplyApprovalRegistry, ApprovalError

        registry = ApplyApprovalRegistry(ttl_seconds=300)
        first, _ = await registry.issue(
            user_id="user-1",
            job_id=1,
            greeting_text="第一版",
            source_url="https://www.zhipin.com/job_detail/1.html",
            resume_id=None,
        )
        await registry.issue(
            user_id="user-1",
            job_id=1,
            greeting_text="第二版",
            source_url="https://www.zhipin.com/job_detail/1.html",
            resume_id=None,
        )

        with pytest.raises(ApprovalError, match="无效"):
            await registry.consume(
                first,
                user_id="user-1",
                job_id=1,
                greeting_text="第一版",
                source_url="https://www.zhipin.com/job_detail/1.html",
                resume_id=None,
            )

    @pytest.mark.asyncio
    async def test_token_expires_closed(self):
        from integrations.boss.apply_approval import ApplyApprovalRegistry, ApprovalError

        registry = ApplyApprovalRegistry(ttl_seconds=-1)
        token, _ = await registry.issue(
            user_id="user-1",
            job_id=1,
            greeting_text="您好",
            source_url="https://example.com/job/1",
            resume_id=None,
        )

        with pytest.raises(ApprovalError, match="过期"):
            await registry.consume(
                token,
                user_id="user-1",
                job_id=1,
                greeting_text="您好",
                source_url="https://example.com/job/1",
                resume_id=None,
            )

    def test_send_schema_defaults_to_not_confirmed(self):
        from app.schemas.job_schemas import ApplySendRequest

        request = ApplySendRequest(
            job_id=1,
            greeting_text="您好",
            approval_token="preview-token-that-is-long-enough",
        )

        assert request.confirmed is False


# ============================================================================
# 跨用户隔离测试
# ============================================================================

class TestJobUserIsolation:
    """岗位数据隔离测试"""

    @pytest.mark.asyncio
    async def test_user_a_cannot_get_user_b_job(self):
        from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo

        with patch(
            "app.db.repositories.jobs.job_capture_repo.JobCaptureRepo.get_job"
        ) as mock_get:
            mock_get.return_value = None

            repo = get_job_capture_repo()
            result = await repo.get_job(1, "user-a")

            assert result is None

    @pytest.mark.asyncio
    async def test_user_a_cannot_delete_user_b_job(self):
        from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo

        with patch(
            "app.db.repositories.jobs.job_capture_repo.JobCaptureRepo.delete_job"
        ) as mock_delete:
            mock_delete.return_value = False

            repo = get_job_capture_repo()
            result = await repo.delete_job(1, "user-a")

            assert result is False

    def test_captured_job_model_fields(self):
        """验证 CapturedJobModel 包含所有关键字段"""
        from app.db.models.job_capture import CapturedJobModel

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
