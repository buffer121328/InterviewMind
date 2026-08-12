"""面试回答要点生成、评分与公开输出隔离的回归测试。"""

from importlib import import_module
from types import SimpleNamespace

import pytest

from ai.agents.interview.interview_analysis import (
    build_qa_history,
    build_scoring_qa_history,
)
from ai.agents.interview.questions.answer_points import ensure_plan_answer_points
from ai.workflows.analysis.analysis_service import SessionReportAnalysisService
from ai.workflows.analysis.reviewers.contexts import build_reviewer_contexts
from ai.workflows.interview.sessions.actions import InterviewSessionUseCases
from app.domain.interview_reports import build_structured_interview_report


def test_ensure_plan_answer_points_backfills_without_overwriting_existing_points():
    plan = [
        {
            "content": "Redis 为什么快？",
            "topic": "Redis",
            "type": "tech",
            "answer_points": ["说明内存访问", "说明高效数据结构"],
        },
        {
            "content": "请介绍一次冲突处理经历。",
            "topic": "冲突处理",
            "type": "behavior",
        },
    ]

    normalized, changed = ensure_plan_answer_points(plan)
    normalized_again, changed_again = ensure_plan_answer_points(normalized)

    assert changed is True
    assert normalized[0]["answer_points"] == ["说明内存访问", "说明高效数据结构"]
    assert normalized[1]["answer_points"]
    assert normalized_again == normalized
    assert changed_again is False


def test_scoring_qa_history_contains_answer_points_but_public_history_does_not():
    messages = [
        {"role": "assistant", "content": "Redis 为什么快？", "question_index": 0},
        {"role": "user", "content": "因为主要在内存中操作。", "question_index": 0},
    ]
    plan = [
        {
            "content": "Redis 为什么快？",
            "topic": "Redis",
            "type": "tech",
            "answer_points": ["说明内存访问", "说明高效数据结构"],
        }
    ]

    public_history = build_qa_history(messages)
    scoring_history = build_scoring_qa_history(messages, plan)

    assert public_history == [
        {"question": "Redis 为什么快？", "answer": "因为主要在内存中操作。"}
    ]
    assert "answer_points" not in public_history[0]
    assert scoring_history[0]["answer_points"] == ["说明内存访问", "说明高效数据结构"]
    assert "内部评分参考" in SessionReportAnalysisService._format_qa(scoring_history)
    reviewer_contexts = build_reviewer_contexts(
        resume="候选人简历",
        job_description="Agent 开发",
        company_info="公司",
        evidence=[
            {
                "question_id": "Q1",
                "question_summary": "Redis 为什么快？",
                "candidate_claims": ["主要在内存中操作"],
            }
        ],
        answer_points_by_question={"Q1": scoring_history[0]["answer_points"]},
    )
    assert "说明高效数据结构" in reviewer_contexts["technical_depth"]


def test_structured_report_does_not_expose_internal_answer_points():
    _profile, weakness = build_structured_interview_report(
        {"profile": {"overall_assessment": "基础扎实"}},
        {
            "report_data": {
                "question_evidence": [
                    {
                        "question_id": "Q1",
                        "question_summary": "Redis 为什么快？",
                        "answer_points": ["说明内存访问"],
                    }
                ],
                "question_failures": [
                    {
                        "question": "Redis 为什么快？",
                        "user_answer": "主要在内存中操作",
                        "issue": "缺少数据结构说明",
                        "better_example": "补充说明编码结构",
                        "answer_points": ["说明内存访问", "说明高效数据结构"],
                    }
                ],
            }
        },
    )

    serialized = str(weakness)
    assert "answer_points" not in serialized
    assert "说明高效数据结构" not in serialized


class _LegacySessionRepo:
    def __init__(self):
        self.plan = [
            {
                "content": "解释事件循环",
                "topic": "事件循环",
                "type": "tech",
            }
        ]
        self.saved_plans = []

    async def get_session(self, *_args, **_kwargs):
        return SimpleNamespace(session_id="session-1")

    async def get_interview_plan(self, *_args, **_kwargs):
        return self.plan

    async def save_interview_plan(self, _session_id, plan):
        self.saved_plans.append(plan)
        self.plan = plan
        return True


@pytest.mark.asyncio
async def test_hint_read_backfills_and_persists_legacy_plan_answer_points():
    use_cases = InterviewSessionUseCases()
    repo = _LegacySessionRepo()
    use_cases._session_repo = repo

    response = await use_cases.get_hint(
        session_id="session-1",
        question_index=0,
        user_id="user-1",
    )

    assert response["generating"] is False
    assert repo.saved_plans
    assert repo.saved_plans[0][0]["answer_points"]
    assert "1." in str(response["hint"])


@pytest.mark.asyncio
async def test_report_trigger_backfills_plan_and_passes_points_only_to_scoring(
    monkeypatch,
):
    from ai.agents.interview.interview_analysis import trigger_session_report_analysis

    captured = {}

    class FakeSessionRepo:
        def __init__(self):
            self.saved_plans = []

        async def get_session(self, *_args, **_kwargs):
            return SimpleNamespace(
                messages=[
                    SimpleNamespace(
                        role="assistant",
                        content="解释事件循环",
                        question_index=0,
                    ),
                    SimpleNamespace(
                        role="user",
                        content="通过任务队列调度异步任务",
                        question_index=0,
                    ),
                ],
                metadata=SimpleNamespace(
                    interview_plan=[
                        {
                            "content": "解释事件循环",
                            "topic": "事件循环",
                            "type": "tech",
                        }
                    ],
                    resume_content="候选人简历",
                    job_description="Agent 开发",
                    company_info="公司",
                    round_index=1,
                    series_id=None,
                ),
            )

        async def save_interview_plan(self, _session_id, plan):
            self.saved_plans.append(plan)
            return True

        async def save_profile(self, *_args, **_kwargs):
            return True

    class FakeAnalysisService:
        async def generate_session_report(self, **kwargs):
            captured.update(kwargs)
            profile = SimpleNamespace(model_dump=lambda: {"overall_assessment": "完成"})
            return profile, {"question_evidence": []}

    class FakeWeaknessRepo:
        async def save_report(self, **_kwargs):
            return 1

    session_repo = FakeSessionRepo()
    session_module = import_module("app.db.repositories.session.session_repo")
    analysis_module = import_module("ai.workflows.analysis.analysis_service")
    weakness_module = import_module(
        "app.db.repositories.interview.weakness_report_repo"
    )
    monkeypatch.setattr(session_module, "SessionRepo", lambda: session_repo)
    monkeypatch.setattr(
        analysis_module,
        "get_session_report_analysis_service",
        lambda: FakeAnalysisService(),
    )
    monkeypatch.setattr(
        weakness_module,
        "get_weakness_report_repo",
        lambda: FakeWeaknessRepo(),
    )

    await trigger_session_report_analysis(
        "session-1",
        user_id="user-1",
        raise_on_error=True,
    )

    assert session_repo.saved_plans[0][0]["answer_points"]
    assert captured["qa_history"][0]["answer_points"]
    assert set(build_qa_history((await session_repo.get_session()).messages)[0]) == {
        "question",
        "answer",
    }
