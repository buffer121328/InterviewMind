from app.services.question_bank.session_archive import build_archived_turns


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
