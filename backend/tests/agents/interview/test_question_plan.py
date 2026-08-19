"""面试题目规划与追问预算的纯函数测试。"""

from ai.agents.interview.questions.plan import (
    INTRODUCTION_ROUND_TYPES as QUESTION_PLAN_INTRODUCTION_ROUND_TYPES,
    is_introduction_question,
    is_technical_question,
    merge_question_plan,
    prepare_candidates,
    prepare_question_bank_candidates,
    technical_follow_up_budget,
)

from ai.agents.interview.planning.planner import (
    INTRODUCTION_ROUND_TYPES as PLANNER_INTRODUCTION_ROUND_TYPES,
)


def test_interview_planner_imports_shared_introduction_round_types() -> None:
    assert PLANNER_INTRODUCTION_ROUND_TYPES == QUESTION_PLAN_INTRODUCTION_ROUND_TYPES
    assert "tech_initial" in PLANNER_INTRODUCTION_ROUND_TYPES


def test_candidates_prioritize_experience_and_keep_bank_id():
    candidates = prepare_candidates(
        [{"question_text": "面经题", "source_type": "nowcoder", "source_id": "n1"}],
        [{"id": 9, "question_text": "题库题", "reference_answer": "答案"}],
        max_questions=2,
    )

    assert [item["content"] for item in candidates] == ["面经题", "题库题"]
    assert candidates[1]["question_bank_item_id"] == 9


def test_question_bank_candidates_keep_bank_id():
    candidates = prepare_question_bank_candidates(
        [{"id": 9, "question_text": "题库题", "reference_answer": "答案"}],
        max_questions=2,
    )

    assert [item["content"] for item in candidates] == ["题库题"]
    assert candidates[0]["question_bank_item_id"] == 9


def test_merge_question_plan_deduplicates_and_reindexes():
    candidates = [{"content": "解释 GIL", "type": "tech"}]
    generated = [
        {"id": 8, "content": "解释 GIL", "type": "tech"},
        {"id": 9, "content": "说明协程", "type": "tech"},
    ]

    merged = merge_question_plan(candidates, generated, max_questions=2)

    assert [item["content"] for item in merged] == ["解释 GIL", "说明协程"]
    assert [item["id"] for item in merged] == [1, 2]


def test_candidates_carry_followups_for_runtime_reuse():
    candidates = prepare_question_bank_candidates(
        [
            {
                "id": 9,
                "question_text": "题库题",
                "followups": [{"id": 1, "question_text": "你如何验证这个方案？"}],
            }
        ],
        max_questions=1,
    )

    assert candidates[0]["followups"][0]["question_text"] == "你如何验证这个方案？"


def test_is_introduction_question_recognizes_structured_and_semantic_variants():
    assert is_introduction_question({"content": "请做一个简短的自我介绍。", "type": "behavior"})
    assert is_introduction_question({"content": "请介绍你的教育背景和工作经历。", "type": "behavior"})
    assert is_introduction_question({"content": "请说明这个项目的技术架构。", "type": "intro"})
    assert not is_introduction_question({"content": "请介绍这个项目的技术架构。", "type": "tech"})


def test_merge_question_plan_keeps_one_semantic_intro_for_initial_round():
    candidates = [{"content": "请介绍一下你的教育背景和工作经历。", "type": "behavior"}]
    generated = [
        {"content": "请做一个简短的自我介绍，包括你的教育背景和工作经历。", "type": "intro"},
        {"content": "请选择一个最能代表你能力的项目，说明目标和结果。", "type": "tech"},
    ]

    merged = merge_question_plan(candidates, generated, max_questions=3, round_type="tech_initial")

    assert [item["content"] for item in merged] == [
        "请介绍一下你的教育背景和工作经历。",
        "请选择一个最能代表你能力的项目，说明目标和结果。",
    ]


def test_is_technical_question_supports_tech_and_system_design() -> None:
    assert is_technical_question({"type": "tech"}) is True
    assert is_technical_question({"question_type": "system_design"}) is True
    assert is_technical_question({"type": "behavior"}) is False
    assert is_technical_question(None) is False


def test_technical_follow_up_budget_is_twenty_percent_of_all_main_questions() -> None:
    plan = [
        *[{"type": "tech"} for _ in range(6)],
        *[{"type": "behavior"} for _ in range(14)],
    ]

    assert technical_follow_up_budget(plan) == 4
    assert technical_follow_up_budget(plan[:3]) == 0
    assert technical_follow_up_budget([{"type": "behavior"} for _ in range(5)]) == 1
