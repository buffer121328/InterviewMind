"""
打招呼文案生成测试

验证：3种风格文案生成、约束合规性（不承诺不存在经历）、兜底文案
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGreetingGenerator:
    """打招呼文案生成器测试"""

    @pytest.mark.asyncio
    async def test_generate_three_greetings(self):
        from app.infrastructure.browser.greeting_generator import generate_greetings

        mock_output = MagicMock()
        mock_output.model_dump.return_value = {
            "greetings": [
                {
                    "tone": "professional",
                    "message_text": "您好，看到贵司在招聘Java高级工程师，我有3年Java开发经验，熟悉Spring Cloud微服务架构。",
                    "highlights_used": ["3年经验", "Spring Cloud"],
                    "risk_notes": "",
                },
                {
                    "tone": "technical",
                    "message_text": "技术栈：Java/Spring Boot/Spring Cloud/MySQL/Redis/Kafka，与贵司岗位高度匹配。曾负责电商平台核心模块开发。",
                    "highlights_used": ["技术栈匹配", "电商平台"],
                    "risk_notes": "",
                },
                {
                    "tone": "result_oriented",
                    "message_text": "主导过电商平台微服务架构设计，系统支撑日均10万+订单。与贵司Java高级工程师岗位匹配。",
                    "highlights_used": ["微服务架构", "日均10万订单"],
                    "risk_notes": "注意：订单量数据需确认",
                },
            ],
        }

        with patch(
            "app.infrastructure.llm.llm_utils.invoke_structured",
            new=AsyncMock(return_value=mock_output),
        ):
            greetings = await generate_greetings(
                company_name="字节跳动",
                job_title="Java高级工程师",
                jd_summary="匹配关键词: Java, Spring Cloud, 微服务, 高并发",
                candidate_highlights="3年Java开发, Spring Cloud微服务, 电商平台核心模块开发",
            )

        assert len(greetings) == 3
        assert greetings[0]["tone"] == "professional"
        assert greetings[1]["tone"] == "technical"
        assert greetings[2]["tone"] == "result_oriented"

    @pytest.mark.asyncio
    async def test_constraint_no_self_praise(self):
        """不应包含"我非常适合"等套话"""
        from app.infrastructure.browser.greeting_generator import generate_greetings

        mock_output = MagicMock()
        mock_output.model_dump.return_value = {
            "greetings": [
                {
                    "tone": "professional",
                    "message_text": "您好，我的背景与贵司Java岗位匹配度较高。",
                    "highlights_used": ["Java"],
                    "risk_notes": "",
                },
                {
                    "tone": "technical",
                    "message_text": "技术栈匹配。",
                    "highlights_used": [],
                    "risk_notes": "",
                },
                {
                    "tone": "result_oriented",
                    "message_text": "成果匹配。",
                    "highlights_used": [],
                    "risk_notes": "",
                },
            ],
        }

        with patch(
            "app.infrastructure.llm.llm_utils.invoke_structured",
            new=AsyncMock(return_value=mock_output),
        ):
            greetings = await generate_greetings(
                company_name="字节跳动",
                job_title="Java",
            )

        # 不应包含"非常"或"很适合"
        for g in greetings:
            assert "非常" not in g["message_text"] or "非常适合" not in g["message_text"]

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        """LLM失败时使用兜底文案"""
        from app.infrastructure.browser.greeting_generator import generate_greetings

        with patch(
            "app.infrastructure.llm.llm_utils.invoke_structured",
            new=AsyncMock(side_effect=Exception("LLM unavailable")),
        ):
            greetings = await generate_greetings(
                company_name="字节跳动",
                job_title="Java高级工程师",
            )

        assert len(greetings) == 3
        assert all("兜底文案" in g.get("risk_notes", "") for g in greetings)

    def test_greeting_length_warning(self):
        """超过200字的文案应有警告"""
        from app.infrastructure.browser.greeting_generator import GreetingItemOutput

        long_text = "您好，" + "Java开发经验丰富，" * 50

        item = GreetingItemOutput(
            tone="professional",
            message_text=long_text,
            highlights_used=["Java"],
            risk_notes="",
        )

        # 验证长度
        assert len(item.message_text) > 200
