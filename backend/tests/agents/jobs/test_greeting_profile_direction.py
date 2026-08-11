"""Regression tests for the longer standard greeting direction."""

import pytest


def test_greeting_prompt_contains_standard_candidate_profile_and_keyword_rule():
    from ai.prompts.jobs import build_greeting_prompt

    prompt = build_greeting_prompt(
        company_name="示例科技",
        job_title="Agent 应用开发工程师",
        jd_summary="Python、FastAPI、RAG、MCP",
        highlights_text="- Python + FastAPI\n- LangGraph",
    )
    assert "26 届计算机技术硕士" in prompt
    assert "Harness Engineering" in prompt
    assert "根据岗位关键词做增减" in prompt
    assert "不能变成候选人已具备的事实" in prompt


def test_longer_greeting_output_contract_accepts_profile_length():
    from ai.agents.jobs.greeting_generator import GreetingItemOutput

    message = "您好，我是 26 届计算机技术硕士，求职方向为 Agent / AI 应用开发。" + "我有真实项目与实习经历，" * 20
    item = GreetingItemOutput(
        tone="professional",
        message_text=message[:680],
        highlights_used=[],
    )
    assert len(item.message_text) >= 260


@pytest.mark.asyncio
async def test_fallback_uses_standard_profile_when_model_fails():
    from unittest.mock import patch

    from ai.agents.jobs.greeting_generator import generate_greetings

    with patch("ai.llm.llm_utils.invoke_structured", side_effect=RuntimeError("boom")):
        greetings = await generate_greetings(
            company_name="示例科技",
            job_title="Agent 应用开发工程师",
            jd_summary="Python、FastAPI、RAG、MCP",
            candidate_highlights=["Python + FastAPI", "LangGraph"],
        )

    assert len(greetings) == 3
    assert all("26 届计算机技术硕士" in item["message_text"] for item in greetings)
    assert all(len(item["message_text"]) <= 800 for item in greetings)
