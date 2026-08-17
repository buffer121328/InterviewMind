from types import SimpleNamespace

from ai.workflows.interview.chat.stream import _count_issued_technical_follow_ups


def _message(role: str, question_index: int) -> SimpleNamespace:
    return SimpleNamespace(role=role, question_index=question_index)


def test_count_issued_technical_follow_ups_ignores_first_answers_and_non_technical_questions():
    plan = [
        {"content": "请自我介绍。", "type": "intro"},
        {"content": "解释缓存穿透。", "type": "tech"},
        {"content": "如何处理团队冲突？", "type": "behavior"},
        {"content": "设计消息幂等方案。", "type": "system_design"},
    ]
    messages = [
        _message("user", 0),
        _message("user", 1),
        _message("user", 1),
        _message("user", 1),
        _message("user", 2),
        _message("user", 2),
        _message("user", 3),
        _message("user", 3),
        _message("assistant", 1),
    ]

    assert _count_issued_technical_follow_ups(messages, plan) == 3
