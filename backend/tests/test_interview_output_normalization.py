"""面试规划和候选人可见输出的兼容性测试。"""

import pytest

from app.schemas.llm_outputs import InterviewQuestionItem, PlanOutput
from ai.agents.interview import interview_planner
from ai.workflows.interview.response_content import extract_latest_assistant_content


def test_plan_source_string_is_normalized_without_retry():
    """来源标签字符串应转换为证据对象，而不是让整份计划解析失败。"""
    item = InterviewQuestionItem.model_validate({
        "id": 1,
        "topic": "自我介绍",
        "content": "请做一个简短的自我介绍。",
        "type": "intro",
        "sources": ["候选人简历"],
    })

    assert item.sources == [{
        "source_type": "model_label",
        "source_id": "",
        "evidence": "候选人简历",
    }]


def test_extract_latest_assistant_content_ignores_raw_candidates():
    """转换层只读取图节点最终消息，不拼接结构化输出重试候选。"""
    output = {
        "raw_candidates": [
            '{"action":"advance"}',
            '{"action":"follow_up"}',
        ],
        "messages": [
            {"role": "user", "content": "我的回答"},
            {"role": "assistant", "content": "好的，接下来进入第二题。"},
        ],
    }

    assert extract_latest_assistant_content(output) == "好的，接下来进入第二题。"


@pytest.mark.asyncio
async def test_planner_uses_fast_channel_and_canonical_intro(monkeypatch):
    """首轮规划使用快速通道，并把首题收敛为稳定的自我介绍题。"""
    calls = []

    async def fake_invoke_structured(**kwargs):
        calls.append(kwargs)
        return PlanOutput.model_validate({
            "questions": [{
                "id": 1,
                "topic": "复杂开场",
                "content": "请同时介绍项目、技术选型和职业规划。",
                "type": "intro",
                "sources": ["候选人简历"],
            }],
        })

    monkeypatch.setattr(interview_planner, "invoke_structured", fake_invoke_structured)

    plan = await interview_planner.generate_interview_plan(
        resume="候选人简历",
        job_description="目标 JD",
        company_info="目标公司",
        max_questions=1,
        api_config={},
        round_type="tech_initial",
    )

    assert calls[0]["channel"] == "fast"
    assert calls[0]["max_retries"] == 1
    assert plan[0]["content"] == "请做一个简短的自我介绍，包括你的教育背景和工作经历。"
