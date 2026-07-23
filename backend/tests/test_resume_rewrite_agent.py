"""受控简历改写 Agent 节点测试。"""

import pytest

from ai.agents.resume import resume_rewrite_agent as agent
from app.schemas.llm_outputs import ChangeItem, ContentSuggestionsOutput


@pytest.mark.asyncio
async def test_rewrite_agent_normalizes_fact_inference_confirmation(monkeypatch):
    calls = []

    async def fake_invoke(prompt, output_model, api_config=None, channel="smart", max_retries=2, temperature=0.7):
        calls.append((output_model, channel))
        if output_model is agent.ResumeRewritePlanOutput:
            return agent.ResumeRewritePlanOutput(
                focus_sections=["专业技能"],
                evidence_to_use=["简历原文", "JD关键词"],
                avoid_risks=["不要新增技能事实"],
                rewrite_strategy="优先把已有 Java 经验改写得更匹配 JD",
            )
        assert output_model is ContentSuggestionsOutput
        return ContentSuggestionsOutput(
            change_items=[
                ChangeItem(
                    section_name="专业技能",
                    original_text="Java, Spring Boot",
                    optimized_text="建议补充 Spring Cloud 相关项目经验，如实际使用过再加入专业技能",
                    change_type="fact_inference",
                    reason="匹配 JD 关键词但原简历未明确出现",
                    evidence_source="JD关键词",
                    requires_user_confirmation=False,
                    confidence=1.7,
                )
            ]
        )

    monkeypatch.setattr(agent, "invoke_structured", fake_invoke)

    result = await agent.run_resume_rewrite_agent(
        resume_content="Java 后端开发，熟悉 Spring Boot",
        job_description="需要 Spring Cloud 微服务经验",
        jd_analysis={"missing_keywords": ["Spring Cloud"], "match_score": 70},
        material_pool={"resume": "Java 后端开发"},
        api_config={"content_writer": {"api_key": "fake"}},
        mode="balanced",
    )

    assert [call[0] for call in calls] == [agent.ResumeRewritePlanOutput, ContentSuggestionsOutput]
    assert result["change_items"][0]["requires_user_confirmation"] is True
    assert result["change_items"][0]["confidence"] == 1.0
    assert result["requires_user_review"] is True


@pytest.mark.asyncio
async def test_fast_mode_skips_planning(monkeypatch):
    calls = []

    async def fake_invoke(prompt, output_model, api_config=None, channel="smart", max_retries=2, temperature=0.7):
        calls.append((output_model, channel, max_retries))
        return ContentSuggestionsOutput(
            change_items=[
                ChangeItem(
                    section_name="个人简介",
                    optimized_text="Java 后端开发，具备电商订单模块经验",
                    change_type="polish",
                    evidence_source="简历原文",
                    confidence=0.9,
                )
            ]
        )

    monkeypatch.setattr(agent, "invoke_structured", fake_invoke)

    result = await agent.run_resume_rewrite_agent(
        resume_content="Java 后端开发，做过订单模块",
        job_description="招聘 Java 后端",
        jd_analysis={},
        material_pool={},
        api_config={"fast": {"api_key": "fake"}},
        mode="fast",
    )

    assert calls == [(ContentSuggestionsOutput, "fast", 1)]
    assert len(result["change_items"]) == 1


def test_normalize_change_items_drops_invalid_and_clamps_fields():
    items = agent.normalize_change_items([
        {"section_name": "", "optimized_text": "无效"},
        {
            "section_name": "项目经历",
            "optimized_text": "如有 Kafka 经验，可补充消息削峰场景",
            "change_type": "suggest_addition",
            "confidence": -5,
        },
        {
            "section_name": "工作经历",
            "optimized_text": "负责订单模块开发",
            "change_type": "unknown",
            "confidence": "bad",
        },
    ])

    assert len(items) == 2
    assert items[0]["requires_user_confirmation"] is True
    assert items[0]["confidence"] == 0.0
    assert items[1]["change_type"] == "polish"
    assert items[1]["confidence"] == 0.8
