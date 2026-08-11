"""Tests for generate -> reflect -> bounded rewrite greeting generation."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError


def _message(suffix: str) -> str:
    """Build one valid first-person 260-680 character greeting fixture."""
    return (
        "您好，我关注到贵司正在招聘Java高级工程师。我有真实的Java服务开发和Spring Cloud项目经历，"
        "能够结合接口设计、问题排查和协作交付说明自己的职责与技术取舍，也愿意补充可验证的项目结果。"
        "我重视工程可维护性、团队协作和交付质量，希望结合岗位关键词说明自己的技术实践、项目职责与可验证证据。"
        "我也愿意进一步介绍与岗位最相关的案例、问题解决过程和后续学习计划。"
        "如果岗位需要，我可以围绕技术方案、协作过程、故障处理和交付结果补充更多可核验细节。"
        "我会保持信息真实、表达具体，并优先说明与岗位要求直接相关的工作内容。"
        f"希望有机会进一步了解团队业务重点与岗位预期。{suffix}"
    )


def _draft(output_model):
    """Build the requested structured writer or reflector output."""
    from ai.agents.jobs.greeting_generator import GreetingListOutput, GreetingReflectionOutput

    if output_model is GreetingReflectionOutput:
        return GreetingReflectionOutput(
            approved=True,
            truthfulness_pass=True,
            relevance_pass=True,
            length_pass=True,
            issues=[],
        )
    return GreetingListOutput.model_validate({
        "greetings": [
            {
                "tone": "professional",
                "message_text": _message(""),
                "highlights_used": ["3年Java开发"],
                "risk_notes": "",
            },
            {
                "tone": "technical",
                "message_text": _message("我也关注工程可维护性。"),
                "highlights_used": ["Spring Cloud微服务"],
                "risk_notes": "",
            },
            {
                "tone": "result_oriented",
                "message_text": _message("我会以真实结果说明贡献。"),
                "highlights_used": ["电商平台核心模块开发"],
                "risk_notes": "",
            },
        ]
    })


class TestGreetingGenerator:
    """Greeting writer and reflector contracts."""

    @pytest.mark.asyncio
    async def test_generate_three_greetings_and_reflect(self):
        """A compliant first draft is returned after one independent reflection call."""
        from ai.agents.jobs.greeting_generator import generate_greetings

        calls: list[tuple[type, str, float]] = []

        async def invoke(_prompt, output_model, _api_config=None, **kwargs):
            calls.append((output_model, kwargs["channel"], kwargs["temperature"]))
            return _draft(output_model)

        with patch("ai.llm.llm_utils.invoke_structured", new=invoke):
            greetings = await generate_greetings(
                company_name="字节跳动",
                job_title="Java高级工程师",
                jd_summary="匹配关键词: Java, Spring Cloud, 微服务, 高并发",
                candidate_highlights="3年Java开发，Spring Cloud微服务，电商平台核心模块开发",
            )

        assert [item["tone"] for item in greetings] == [
            "professional",
            "technical",
            "result_oriented",
        ]
        assert [channel for _model, channel, _temperature in calls] == [
            "content_writer",
            "reflector",
        ]
        assert calls[-1][2] == 0.0

    @pytest.mark.asyncio
    async def test_reflection_rejection_rewrites_once(self):
        """A rejected first draft triggers exactly one bounded rewrite round."""
        from ai.agents.jobs.greeting_generator import GreetingReflectionOutput, generate_greetings

        reflection_count = 0
        prompts: list[str] = []

        async def invoke(prompt, output_model, _api_config=None, **_kwargs):
            nonlocal reflection_count
            prompts.append(prompt)
            if output_model is GreetingReflectionOutput:
                reflection_count += 1
                if reflection_count == 1:
                    return GreetingReflectionOutput(
                        approved=False,
                        truthfulness_pass=True,
                        relevance_pass=False,
                        length_pass=True,
                        issues=["technical 与岗位技术关注点关联不足"],
                    )
            return _draft(output_model)

        with patch("ai.llm.llm_utils.invoke_structured", new=invoke):
            greetings = await generate_greetings(
                company_name="示例科技",
                job_title="Java高级工程师",
                candidate_highlights=["3年Java开发", "Spring Cloud微服务", "电商平台核心模块开发"],
            )

        assert len(greetings) == 3
        assert reflection_count == 2
        assert any("上轮自审反馈" in prompt for prompt in prompts)

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        """Writer or reflector failure returns deterministic evidence-only copy."""
        from ai.agents.jobs.greeting_generator import generate_greetings

        with patch(
            "ai.llm.llm_utils.invoke_structured",
            new=AsyncMock(side_effect=Exception("LLM unavailable")),
        ):
            greetings = await generate_greetings(
                company_name="字节跳动",
                job_title="Java高级工程师",
            )

        assert len(greetings) == 3
        assert all("兜底文案" in item.get("risk_notes", "") for item in greetings)

    def test_greeting_length_contract_rejects_oversized_text(self):
        """The structured contract rejects text over 680 characters."""
        from ai.agents.jobs.greeting_generator import GreetingItemOutput

        with pytest.raises(ValidationError):
            GreetingItemOutput(
                tone="professional",
                message_text="您好，" + "Java开发经验丰富，" * 100,
                highlights_used=["Java"],
                risk_notes="",
            )

    @pytest.mark.asyncio
    async def test_fallback_greetings_are_first_person_and_complete(self):
        """Fallback copy also satisfies subject and length contracts."""
        from ai.agents.jobs.greeting_generator import generate_greetings

        with patch(
            "ai.llm.llm_utils.invoke_structured",
            new=AsyncMock(side_effect=Exception("LLM unavailable")),
        ):
            greetings = await generate_greetings(
                company_name="示例科技",
                job_title="AI Agent 后端工程师",
                candidate_highlights=["我负责过基于 Django、MCP 与工作流编排的求职 Agent 项目"],
            )

        assert {item["tone"] for item in greetings} == {
            "professional",
            "technical",
            "result_oriented",
        }
        assert all("我" in item["message_text"] for item in greetings)
        assert all(260 <= len(item["message_text"]) <= 800 for item in greetings)
        assert all("您的项目" not in item["message_text"] for item in greetings)
        assert all("欢迎深入沟通" not in item["message_text"] for item in greetings)
