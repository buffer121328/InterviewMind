"""
用户确认服务测试

验证：
- 高风险改写识别
- 确认/拒绝流程
- 审计日志记录
- 最终保存逻辑
"""

import pytest
from unittest.mock import AsyncMock, patch
from ai.agents.resume.resume_confirmation_service import (
    ResumeConfirmationService,
    AuditEntry,
)


# ============================================================================
# 模拟数据
# ============================================================================

MOCK_CHANGE_ITEMS = [
    {
        "section_name": "个人简介",
        "change_type": "polish",
        "original_text": "Java开发工程师",
        "optimized_text": "3年Java开发经验",
        "reason": "文字润色",
        "evidence_source": "简历原文",
        "confidence": 0.95,
        "requires_user_confirmation": False,
    },
    {
        "section_name": "项目经历",
        "change_type": "polish",
        "original_text": "参与电商开发",
        "optimized_text": "独立负责电商平台核心模块开发",
        "reason": "专业化表达",
        "evidence_source": "简历原文",
        "confidence": 0.9,
        "requires_user_confirmation": False,
    },
    {
        "section_name": "专业技能",
        "change_type": "fact_inference",
        "original_text": "",
        "optimized_text": "熟悉Kubernetes和Docker容器化部署",
        "reason": "匹配JD要求",
        "evidence_source": "JD关键词",
        "confidence": 0.5,
        "requires_user_confirmation": True,
    },
    {
        "section_name": "工作经历",
        "change_type": "suggest_addition",
        "original_text": "",
        "optimized_text": "主导微服务架构迁移，QPS提升200%",
        "reason": "增强竞争力",
        "evidence_source": "JD关键词",
        "confidence": 0.4,
        "requires_user_confirmation": True,
    },
]

MOCK_ASSEMBLED_RESUME = """
# 张三 | Java高级工程师
## 个人简介
3年Java开发经验，专注电商领域微服务架构设计

## 工作经历
### XX科技 | Java开发 | 2022-至今
- 独立负责电商平台核心模块开发
- 主导微服务架构迁移

## 专业技能
Java, Spring Boot, Spring Cloud, MySQL, Redis, Kubernetes, Docker
"""


# ============================================================================
# 确认服务基础测试
# ============================================================================

class TestConfirmationService:
    """确认服务基础功能测试"""

    def test_load_pending_items(self):
        service = ResumeConfirmationService(user_id="test-user")
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        # 只有 fact_inference 和 requires_user_confirmation=True 的需要确认
        assert len(service._pending_items) == 2
        assert service._pending_items[0]["status"] == "pending"

    def test_no_pending_when_all_safe(self):
        safe_items = [MOCK_CHANGE_ITEMS[0], MOCK_CHANGE_ITEMS[1]]
        service = ResumeConfirmationService()
        service.load_pending_items(safe_items)

        assert len(service._pending_items) == 0
        assert not service.has_pending()

    def test_confirm_single_item(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        pending = service.get_pending_items()
        assert len(pending) > 0

        item_id = pending[0]["item_id"]
        result = service.confirm_item(item_id)

        assert result is True
        assert len(service._confirmed_items) == 1
        assert len(service._pending_items) == 1

    def test_reject_single_item(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        pending = service.get_pending_items()
        item_id = pending[0]["item_id"]
        result = service.reject_item(item_id)

        assert result is True
        assert len(service._rejected_items) == 1

    def test_confirm_all(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        count = service.confirm_all()
        assert count == 2
        assert not service.has_pending()

    def test_reject_all(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        count = service.reject_all()
        assert count == 2
        assert not service.has_pending()

    def test_has_pending(self):
        service = ResumeConfirmationService()
        assert not service.has_pending()

        service.load_pending_items(MOCK_CHANGE_ITEMS)
        assert service.has_pending()

        service.confirm_all()
        assert not service.has_pending()

    def test_get_summary(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        summary = service.get_summary()
        assert summary["total_pending"] == 2
        assert summary["total_confirmed"] == 0
        assert not summary["can_save"]  # 有待确认项，不能保存

        service.confirm_all()
        summary = service.get_summary()
        assert summary["can_save"]  # 全部确认，可以保存


class TestAuditLog:
    """审计日志测试"""

    def test_audit_entry_creation(self):
        entry = AuditEntry(
            user_id="user-123",
            action="confirmed",
            section_name="专业技能",
            original_text="原文",
            optimized_text="优化后",
        )
        assert entry.user_id == "user-123"
        assert entry.action == "confirmed"
        assert entry.entry_id  # 自动生成 UUID

    def test_audit_log_after_confirm(self):
        service = ResumeConfirmationService(user_id="test-user")
        service.load_pending_items(MOCK_CHANGE_ITEMS)
        service.confirm_all()

        log = service.get_audit_log()
        assert len(log) == 2  # 两条确认记录
        assert log[0]["action"] == "confirmed"
        assert log[0]["user_id"] == "test-user"

    def test_audit_log_after_reject(self):
        service = ResumeConfirmationService(user_id="test-user")
        service.load_pending_items(MOCK_CHANGE_ITEMS)
        service.reject_all()

        log = service.get_audit_log()
        assert len(log) == 2
        assert log[0]["action"] == "rejected"


class TestSaveFinalResume:
    """最终保存测试"""

    @pytest.mark.asyncio
    async def test_cannot_save_with_pending(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        result = await service.save_final_resume(MOCK_ASSEMBLED_RESUME)
        assert result is None  # 有待确认项时不能保存

    @pytest.mark.asyncio
    async def test_save_after_all_confirmed(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)
        service.confirm_all()

        # Mock 数据库保存
        with patch(
            "app.db.repositories.resume.resume_generation_repo.get_generation_repo"
        ) as mock_repo:
            mock_instance = AsyncMock()
            mock_instance.save_generated_resume.return_value = "resume-id-123"
            mock_repo.return_value = mock_instance

            result = await service.save_final_resume(MOCK_ASSEMBLED_RESUME)
            assert result == "resume-id-123"

    def test_confirm_nonexistent_item(self):
        service = ResumeConfirmationService()
        service.load_pending_items(MOCK_CHANGE_ITEMS)

        result = service.confirm_item("nonexistent-id")
        assert result is False
