"""面试规划和候选人可见输出的兼容性测试。"""

import asyncio
import time

import pytest

from ai.agents.interview.planning import planner as interview_planner
from ai.workflows.interview.response_content import extract_latest_assistant_content
from app.domain.interview_rounds import SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE
from app.schemas.llm_outputs import InterviewQuestionItem, PlanOutput


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


def test_interview_question_items_accept_ordered_answer_points():
    """规划结构应保存内部回答要点，且不会把它们拼进问题正文。"""
    item = InterviewQuestionItem.model_validate({
        "id": 1,
        "topic": "Redis",
        "content": "Redis 为什么快？",
        "type": "tech",
        "answer_points": ["说明内存访问与数据结构", "补充单线程事件循环的边界"],
    })

    assert item.answer_points == ["说明内存访问与数据结构", "补充单线程事件循环的边界"]
    assert "内存访问" not in item.content


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
    assert plan[0]["source_type"] == SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE
    assert "教育与工作经历" in plan[0]["answer_points"][0]


@pytest.mark.asyncio
async def test_planner_timeout_falls_back_without_blocking_interview_start(monkeypatch, caplog):
    """模型池长时间无响应时，启动链路应在总预算内回退，不能累计多通道超时。"""

    async def never_returns(**_kwargs):
        await asyncio.sleep(1)
        raise AssertionError("planner timeout should cancel the pending model call")

    monkeypatch.setattr(interview_planner, "invoke_structured", never_returns)
    monkeypatch.setattr(interview_planner, "build_planner_prompt", lambda **_kwargs: "planner json")
    monkeypatch.setattr(
        interview_planner,
        "get_settings",
        lambda: type("Settings", (), {"interview_plan_timeout_seconds": 0.01})(),
    )

    started = time.perf_counter()
    plan = await interview_planner.generate_interview_plan(
        resume="候选人简历",
        job_description="目标 JD",
        company_info="目标公司",
        max_questions=2,
        api_config={},
        round_type="tech_deep",
        round_index=2,
    )

    assert time.perf_counter() - started < 0.2
    assert len(plan) == 2
    assert "error_type=TimeoutError" in caplog.text


def test_round_fallback_plan_is_exact_length_and_distinct_from_initial_round():
    """第二轮本地兜底应严格返回20道深度题，且不复用首轮题目。"""
    first_round = {"请做一个简短的自我介绍，包括你的教育背景和工作经历。"}
    plan = interview_planner._get_default_questions(
        20,
        round_type="tech_deep",
        previous_questions=list(first_round),
        include_provenance=True,
    )

    contents = [item["content"] for item in plan]
    assert len(plan) == 20
    assert len(set(contents)) == 20
    assert not any("自我介绍" in content for content in contents)
    assert first_round.isdisjoint(contents)
    assert all(item["type"] != "intro" for item in plan)
    assert all(
        item["source_type"] == SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE
        for item in plan
    )
    assert all(item["answer_points"] for item in plan)


@pytest.mark.asyncio
async def test_partial_model_plan_is_filled_to_requested_round_length(monkeypatch):
    """模型只返回少量题目时，规划器也必须补足用户选择的题数。"""

    async def fake_invoke_structured(**_kwargs):
        return PlanOutput.model_validate({
            "questions": [{
                "id": 1,
                "topic": "项目难点",
                "content": "请说明项目中最难解决的技术问题。",
                "type": "tech",
                "sources": ["候选人简历"],
            }],
        })

    monkeypatch.setattr(interview_planner, "invoke_structured", fake_invoke_structured)
    monkeypatch.setattr(interview_planner, "build_planner_prompt", lambda **_kwargs: "planner json")

    plan = await interview_planner.generate_interview_plan(
        resume="候选人简历",
        job_description="目标 JD",
        company_info="目标公司",
        max_questions=20,
        api_config={},
        round_type="tech_deep",
        round_index=2,
        previous_questions=["请做一个简短的自我介绍，包括你的教育背景和工作经历。"],
    )

    contents = [item["content"] for item in plan]
    assert len(plan) == 20
    assert len(set(contents)) == 20
    assert all("自我介绍" not in content for content in contents)
    assert plan[0].get("source_type") != SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE
    assert all(
        item["source_type"] == SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE
        for item in plan[1:]
    )
    assert all(item["answer_points"] for item in plan)
