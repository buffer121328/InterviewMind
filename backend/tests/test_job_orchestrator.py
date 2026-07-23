"""
资产生成编排器 + 限流 + 审计日志 测试
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# 资产生成编排器测试
# ============================================================================

class TestAssetOrchestrator:
    """资产生成编排测试"""

    @pytest.mark.asyncio
    async def test_generate_assets_full_flow(self):
        """完整资产生成流程：JD分析 → 简历 → 文案"""
        from ai.workflows.jobs_support.job_asset_orchestrator import generate_assets

        # Mock 岗位仓库
        mock_job = {
            "id": 1,
            "company_name": "字节跳动",
            "job_title": "Java高级工程师",
            "job_description": "Java Spring Cloud 高并发",
            "tags": ["Java", "Spring"],
            "platform": "boss",
            "source_url": "https://boss.com/job/1",
        }

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_job.return_value = mock_job
            mock_repo_instance.update_status.return_value = True
            mock_repo.return_value = mock_repo_instance

            # Mock JD分析
            with patch("ai.agents.resume.jd_matcher.analyze_jd_match") as mock_jd:
                mock_jd.return_value = {
                    "overall_match_score": 75,
                    "matched_keywords": ["Java", "Spring"],
                    "missing_keywords": ["Kafka"],
                    "strengths": ["Java经验"],
                    "priority_actions": ["补充Kafka经验"],
                }

                # Mock 简历生成
                with patch(
                    "ai.agents.resume.resume_generation_sessions.init_generation_session"
                ) as mock_gen:
                    mock_gen.return_value = {
                        "needs_input": False,
                        "result": {
                            "resume_id": 1,
                            "content": "# Java高级工程师简历\n...",
                        },
                    }

                    # Mock 文案生成
                    with patch(
                        "ai.agents.jobs.greeting_generator.generate_greetings"
                    ) as mock_greet:
                        mock_greet.return_value = [
                            {"tone": "professional", "message_text": "您好...", "highlights_used": [], "risk_notes": ""},
                            {"tone": "technical", "message_text": "技术栈...", "highlights_used": [], "risk_notes": ""},
                            {"tone": "result_oriented", "message_text": "成果...", "highlights_used": [], "risk_notes": ""},
                        ]

                        result = await generate_assets(
                            job_id=1,
                            user_id="user-1",
                            resume_content="3年Java开发经验",
                        )

        assert result["success"] is True
        assert result["assets"].jd_analysis is not None
        assert result["assets"].custom_resume_id == 1
        assert len(result["assets"].greetings) == 3

    @pytest.mark.asyncio
    async def test_generate_assets_job_not_found(self):
        from ai.workflows.jobs_support.job_asset_orchestrator import generate_assets

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_job.return_value = None
            mock_repo.return_value = mock_repo_instance

            result = await generate_assets(
                job_id=999,
                user_id="user-1",
                resume_content="test",
            )

        assert result["success"] is False
        assert "不存在" in result["message"]

    @pytest.mark.asyncio
    async def test_low_match_risk_flag(self):
        """匹配度过低时生成风险标记"""
        from ai.workflows.jobs_support.job_asset_orchestrator import generate_assets

        mock_job = {
            "id": 1, "company_name": "字节", "job_title": "Java",
            "job_description": "Java", "tags": ["Java"], "platform": "boss",
        }

        with patch(
            "app.db.repositories.jobs.job_capture_repo.get_job_capture_repo"
        ) as mock_repo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_job.return_value = mock_job
            mock_repo_instance.update_status.return_value = True
            mock_repo.return_value = mock_repo_instance

            with patch("ai.agents.resume.jd_matcher.analyze_jd_match") as mock_jd:
                mock_jd.return_value = {"overall_match_score": 15}

                with patch(
                    "ai.agents.resume.resume_generation_sessions.init_generation_session"
                ) as mock_gen:
                    mock_gen.return_value = {"needs_input": False, "result": {}}

                    with patch(
                        "ai.agents.jobs.greeting_generator.generate_greetings"
                    ) as mock_greet:
                        mock_greet.return_value = []

                        result = await generate_assets(
                            job_id=1, user_id="user-1", resume_content="test",
                        )

        # 低匹配度应有风险标记
        assert any("匹配度过低" in flag for flag in result["assets"].risk_flags)


# ============================================================================
# 限流器测试
# ============================================================================

class TestRateLimiter:
    """频率限制器测试"""

    @pytest.mark.asyncio
    async def test_allow_first_request(self):
        from integrations.boss.rate_limiter import check_rate, RateLimitType

        can, msg = await check_rate("user-test", RateLimitType.CAPTURE)
        assert can is True

    @pytest.mark.asyncio
    async def test_record_and_reset_failures(self):
        from integrations.boss.rate_limiter import record_failure, record_success, get_rate_status

        await record_failure("user-test")
        await record_failure("user-test")

        status = await get_rate_status("user-test")
        assert status["failures"] == 2

        await record_success("user-test")
        status = await get_rate_status("user-test")
        assert status["failures"] == 0

    @pytest.mark.asyncio
    async def test_auto_pause_on_consecutive_failures(self):
        from integrations.boss.rate_limiter import (
            record_failure, get_rate_status,
            MAX_CONSECUTIVE_FAILURES,
        )

        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await record_failure("user-auto-pause")

        status = await get_rate_status("user-auto-pause")
        assert status["paused"] is True
        assert status["failures"] >= MAX_CONSECUTIVE_FAILURES

    @pytest.mark.asyncio
    async def test_blocked_when_paused(self):
        from integrations.boss.rate_limiter import (
            check_rate, record_failure, RateLimitType,
            MAX_CONSECUTIVE_FAILURES,
        )

        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await record_failure("user-blocked")

        can, msg = await check_rate("user-blocked", RateLimitType.SEND)
        assert can is False
        assert "暂停" in msg


# ============================================================================
# 审计日志测试
# ============================================================================

class TestAuditLogger:
    """审计日志测试"""

    @pytest.mark.asyncio
    async def test_create_audit_record(self):
        from integrations.boss.audit_logger import create_audit_record

        record = await create_audit_record(
            user_id="user-1",
            action="send",
            job_id=1,
            resume_id=2,
            greeting_text="您好...",
            send_confirmed=True,
            send_status="sent",
            steps=[
                {"step": "open_page", "status": "success"},
                {"step": "fill_greeting", "status": "success"},
                {"step": "click_send", "status": "success"},
            ],
        )

        assert record.user_id == "user-1"
        assert record.action == "send"
        assert record.send_status == "sent"
        assert len(record.steps) == 3

    @pytest.mark.asyncio
    async def test_get_audit_logs(self):
        from integrations.boss.audit_logger import create_audit_record, get_audit_logs

        await create_audit_record(
            user_id="user-log",
            action="capture",
            job_id=1,
        )
        await create_audit_record(
            user_id="user-log",
            action="send",
            job_id=1,
        )

        logs = await get_audit_logs("user-log")
        assert len(logs) == 2

        # 按 action 过滤
        logs = await get_audit_logs("user-log", action="send")
        assert len(logs) == 1
        assert logs[0]["action"] == "send"

    @pytest.mark.asyncio
    async def test_get_last_audit(self):
        from integrations.boss.audit_logger import create_audit_record, get_last_audit

        await create_audit_record(user_id="user-last", action="capture", job_id=1)
        await create_audit_record(user_id="user-last", action="send", job_id=1)

        last = await get_last_audit("user-last")
        assert last is not None
        assert last["action"] == "send"  # 最后一条是 send

    @pytest.mark.asyncio
    async def test_audit_record_fields(self):
        from integrations.boss.audit_logger import AuditRecord, AuditStep

        step1 = AuditStep(step="open_page", status="success")
        step2 = AuditStep(step="fill_greeting", status="success", detail="selector: textarea")
        step3 = AuditStep(step="click_send", status="failed", error="button not found")

        record = AuditRecord(
            record_id="audit-001",
            user_id="user-1",
            action="send",
            job_id=1,
            send_status="failed",
            steps=[step1, step2, step3],
            error="send failed",
        )

        assert record.send_confirmed is False
        assert len(record.steps) == 3
        assert record.steps[2].status == "failed"
        assert record.steps[2].error == "button not found"
