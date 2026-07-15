"""文字与语音面试共享上下文的单元测试。"""

from types import SimpleNamespace

import pytest

from app.services.interview import interview_context, interview_planner, voice_interview


class _Question:
    def model_dump(self) -> dict:
        return {"content": "解释事件循环", "source_id": "experience-1"}


@pytest.mark.asyncio
async def test_context_resolves_session_fallback_and_normalizes_sources(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_memory(user_id: str, job_description: str, company_info: str):
        captured.update(
            user_id=user_id,
            job_description=job_description,
            company_info=company_info,
        )
        return "候选人偏好深挖项目", [{"id": "memory-1"}]

    monkeypatch.setattr(interview_context, "load_interview_memory", fake_memory)
    metadata = SimpleNamespace(
        resume_content="已保存简历",
        job_description="已保存 JD",
        company_info="已保存公司",
        max_questions=4,
        round_index=2,
        round_type="tech_deep",
    )

    context = await interview_context.build_interview_context(
        user_id="user-1",
        resume_context=None,
        job_description="本次 JD",
        company_info="未知",
        max_questions=None,
        question_bank_count=20,
        experience_questions=[_Question()],
        session_metadata=metadata,
    )

    assert context.resume_context == "已保存简历"
    assert context.job_description == "本次 JD"
    assert context.company_info == "已保存公司"
    assert context.max_questions == 4
    assert context.question_bank_count == 4
    assert context.round_index == 2
    assert context.round_type == "tech_deep"
    assert context.experience_questions[0]["source_id"] == "experience-1"
    assert context.memory_context == "候选人偏好深挖项目"
    assert captured == {
        "user_id": "user-1",
        "job_description": "本次 JD",
        "company_info": "已保存公司",
    }


@pytest.mark.asyncio
async def test_graph_fields_are_independent_copies(monkeypatch):
    async def no_memory(*_args):
        return "", [{"details": {"level": "senior"}}]

    monkeypatch.setattr(interview_context, "load_interview_memory", no_memory)
    context = await interview_context.build_interview_context(
        user_id="user-1",
        resume_context="简历",
        job_description="JD",
        company_info="公司",
        max_questions=5,
        experience_questions=[{"content": "原始问题"}],
    )

    first = context.graph_fields()
    first["experience_questions"][0]["content"] = "已修改"
    first["memory_items"][0]["details"]["level"] = "junior"

    second = context.graph_fields()
    assert second["experience_questions"][0]["content"] == "原始问题"
    assert second["memory_items"][0]["details"]["level"] == "senior"


@pytest.mark.asyncio
async def test_voice_planner_receives_shared_memory_context(monkeypatch):
    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return [{"topic": "项目", "content": "介绍一个项目"}]

    monkeypatch.setattr(interview_planner, "generate_interview_plan", fake_generate)

    result = await voice_interview.node_planner(
        resume="简历",
        job_description="JD",
        company_info="公司",
        max_questions=3,
        api_config={},
        memory_context="候选人偏好深挖项目",
    )

    assert captured["memory_context"] == "候选人偏好深挖项目"
    assert result["interview_plan"][0]["content"] == "介绍一个项目"
