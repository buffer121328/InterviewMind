from datetime import datetime

import pytest

from app.db.repositories.interview.archive_mapper import (
    build_archived_turns,
    extract_candidate_question,
)
from app.db.repositories.interview.question_archive_repo import (
    QuestionArchiveRepo,
    should_persist_plan_question,
)
from app.domain.interview_rounds import SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE


def test_build_archived_turns_separates_main_question_and_followup():
    plan = [{"content": "解释 Python GIL"}]
    messages = [
        {"role": "assistant", "content": "解释 Python GIL", "question_index": 0},
        {"role": "user", "content": "它是一把解释器锁", "question_index": 0},
        {"role": "assistant", "content": "它对多线程有什么影响？", "question_index": 0},
        {"role": "user", "content": "CPU 密集线程不能并行执行字节码", "question_index": 0},
    ]

    turns = build_archived_turns(plan, messages)

    assert [turn.turn_key for turn in turns] == ["main:0", "followup:0:1"]
    assert turns[0].asked_question == "解释 Python GIL"
    assert turns[1].asked_question == "它对多线程有什么影响？"
    assert turns[1].user_answer == "CPU 密集线程不能并行执行字节码"


def test_build_archived_turns_falls_back_to_plan_question():
    turns = build_archived_turns(
        [{"content": "什么是事务隔离级别？"}],
        [{"role": "user", "content": "用于控制并发可见性", "question_index": 0}],
    )

    assert len(turns) == 1
    assert turns[0].asked_question == "什么是事务隔离级别？"


def test_system_fallback_question_is_not_persisted_to_question_bank():
    """系统兜底题的作答可以归档，但题目本身不得写回个人题库。"""
    assert should_persist_plan_question({
        "content": "请做一个简短的自我介绍。",
        "source_type": SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE,
    }) is False
    assert should_persist_plan_question({
        "content": "请说明你在项目中的技术选型。",
        "source_type": "interview_session",
    }) is True



def test_extract_candidate_question_uses_last_visible_question_from_concatenated_json():
    raw = (
        '{"assessment":"结构清晰","action":"advance","content":"请介绍一个你最有成就感的项目。"}'
        '{"action":"follow_up","content":"你在 InterviewMind 项目中具体负责什么？"}'
        '{"evaluation":"回答完整","follow_up":"","advance":"好的，感谢你的介绍。接下来，请介绍一个你最有成就感的项目。","end_round":""}'
    )

    assert extract_candidate_question(raw) == "请介绍一个你最有成就感的项目。"


def test_extract_candidate_question_keeps_plain_question_and_cleans_repeated_instruction():
    assert extract_candidate_question("它对多线程有什么影响？") == "它对多线程有什么影响？"
    assert extract_candidate_question("HTTP 请求的生命周期是什么？") == "HTTP 请求的生命周期是什么？"
    assert extract_candidate_question(
        '{"action":"follow_up","content":"请针对当前题目重新回答：请做一个简短的自我介绍。"}'
    ) == "请做一个简短的自我介绍。"


def test_build_archived_turns_normalizes_structured_assistant_output():
    turns = build_archived_turns(
        [{"content": "请做一个简短的自我介绍。"}],
        [
            {"role": "assistant", "content": "请做一个简短的自我介绍。", "question_index": 0},
            {"role": "user", "content": "我毕业于……", "question_index": 0},
            {
                "role": "assistant",
                "content": (
                    '{"action":"follow_up","content":"请重点介绍你的教育背景。"}'
                    '{"evaluation":"缺少工作经历","action":"follow_up","content":"请简单介绍一下你的工作经历。"}'
                ),
                "question_index": 0,
            },
            {"role": "user", "content": "我曾负责……", "question_index": 0},
        ],
    )

    assert turns[1].asked_question == "请简单介绍一下你的工作经历。"



class _EmptyScalarResult:
    """Provides the minimal SQLAlchemy-result boundary needed by the archive helper test."""

    def scalar_one_or_none(self):
        """Return no existing question so the repository creates a new archive item."""
        return None


class _ArchiveDbStub:
    """Captures newly created archive models without opening a real database transaction."""

    def __init__(self):
        """Initialize the captured model list."""
        self.added = []

    async def execute(self, _statement):
        """Return an empty lookup result for the generated question business key."""
        return _EmptyScalarResult()

    def add(self, model):
        """Capture the model that would be persisted."""
        self.added.append(model)

    async def flush(self):
        """Match the async database boundary; no generated id is needed for this assertion."""


@pytest.mark.asyncio
async def test_new_archived_question_keeps_reference_answer_empty():
    """候选人真实作答保留在 attempts，不能直接冒充尚未设计的回答要点。"""
    db = _ArchiveDbStub()

    question = await QuestionArchiveRepo()._get_or_create_question(
        db,
        "user-1",
        "session-1",
        0,
        {"content": "请介绍你的工作经历。", "source_type": "interview_session"},
        "请介绍你的工作经历。",
        datetime(2026, 8, 3),
    )

    assert db.added == [question]
    assert question.reference_answer is None
