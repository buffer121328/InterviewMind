"""当前面试题重新生成与口头面试约束测试。"""

import pytest

from ai.agents.interview.planning.planner import ROUND_DEFAULT_QUESTIONS
from ai.prompts.interview import build_planner_prompt, build_regenerate_question_prompt
from ai.workflows.interview.questions.regeneration import (
    QuestionRegenerationError,
    _validate_question,
)


def test_deep_round_default_question_is_independent_and_oral():
    question = ROUND_DEFAULT_QUESTIONS["tech_deep"][0]["content"]
    assert "上一轮" not in question
    assert "画出" not in question
    assert "口头" in question


def test_planner_prompt_forbids_written_exam_dependencies():
    prompt = build_planner_prompt(
        round_index=2,
        round_type="tech_deep",
        max_questions=3,
        planning_context="岗位：后端开发",
    )
    assert "独立的口头面试" in prompt
    assert "不得要求绘制完整组件图" in prompt
    assert "不得要求候选人先复述上一轮" in prompt


def test_regeneration_prompt_includes_user_reason_and_current_question():
    prompt = build_regenerate_question_prompt(
        round_index=2,
        round_type="tech_deep",
        reason="范围太大",
        current_question="请介绍项目架构",
        existing_questions="- 请介绍项目架构",
        context="岗位：后端开发",
    )
    assert "范围太大" in prompt
    assert "请介绍项目架构" in prompt
    assert "口头回答" in prompt


def test_question_validation_rejects_cross_round_and_written_exam_wording():
    with pytest.raises(QuestionRegenerationError):
        _validate_question(
            {"content": "请回顾上一轮并画出完整架构图", "type": "system_design"},
            [],
        )


def test_question_validation_normalizes_type_and_keeps_answer_points():
    question = _validate_question(
        {
            "topic": "技术取舍",
            "content": "请说明一次技术取舍，以及你如何验证最终结果。",
            "type": "unknown",
            "answer_points": ["背景", "取舍", "验证"],
        },
        ["请介绍项目经历"],
    )
    assert question["type"] == "tech"
    assert question["answer_points"] == ["背景", "取舍", "验证"]

@pytest.mark.asyncio
async def test_regeneration_use_case_replaces_only_the_current_active_question(monkeypatch):
    from ai.workflows.interview.sessions.management import SessionManagementUseCases
    from app.schemas.interview.session import InterviewSession, SessionMetadata

    session = InterviewSession(
        session_id="session-1",
        title="测试面试",
        metadata=SessionMetadata(
            mode="mock",
            question_count=1,
            max_questions=3,
            status="active",
            interview_plan=[
                {"id": 1, "content": "第一题", "type": "tech"},
                {"id": 2, "content": "旧的当前题", "type": "tech"},
            ],
        ),
    )

    class Repo:
        def __init__(self):
            self.replacement = None

        async def get_session(self, *_args, **_kwargs):
            return session

        async def replace_current_question(self, **kwargs):
            self.replacement = kwargs
            return True

    repo = Repo()
    use_cases = object.__new__(SessionManagementUseCases)
    use_cases._session_repo = repo

    async def fake_regenerate_question(**_kwargs):
        return {"topic": "新题", "content": "请说明一次关键技术取舍。", "type": "tech", "answer_points": ["背景"]}

    monkeypatch.setattr(
        "ai.workflows.interview.sessions.management.regenerate_question",
        fake_regenerate_question,
    )

    replacement = await use_cases.regenerate_question(
        session_id="session-1",
        question_index=1,
        reason="范围太大",
        api_config={},
        user_id="owner-1",
    )

    assert replacement["id"] == 2
    assert repo.replacement["plan"][0]["content"] == "第一题"
    assert repo.replacement["plan"][1]["content"] == "请说明一次关键技术取舍。"


@pytest.mark.asyncio
async def test_regeneration_use_case_rejects_completed_or_noncurrent_question():
    from ai.workflows.interview.sessions.management import (
        SessionManagementBadRequest,
        SessionManagementUseCases,
    )
    from app.schemas.interview.session import InterviewSession, SessionMetadata

    session = InterviewSession(
        session_id="session-2",
        title="已完成面试",
        metadata=SessionMetadata(
            mode="mock",
            question_count=1,
            max_questions=1,
            status="completed",
            interview_plan=[{"id": 1, "content": "题目", "type": "tech"}],
        ),
    )

    class Repo:
        async def get_session(self, *_args, **_kwargs):
            return session

    use_cases = object.__new__(SessionManagementUseCases)
    use_cases._session_repo = Repo()

    with pytest.raises(SessionManagementBadRequest) as exc_info:
        await use_cases.regenerate_question(
            session_id="session-2",
            question_index=0,
            reason=None,
            api_config={},
            user_id="owner-1",
        )
    assert exc_info.value.message == "面试已完成，不能重新生成题目"
