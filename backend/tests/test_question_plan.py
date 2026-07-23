from ai.agents.interview.question_plan import merge_question_plan, prepare_candidates


def test_candidates_prioritize_experience_and_keep_bank_id():
    candidates = prepare_candidates(
        [{"question_text": "面经题", "source_type": "nowcoder", "source_id": "n1"}],
        [{"id": 9, "question_text": "题库题", "reference_answer": "答案"}],
        max_questions=2,
    )

    assert [item["content"] for item in candidates] == ["面经题", "题库题"]
    assert candidates[1]["question_bank_item_id"] == 9


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
    candidates = prepare_candidates(
        [],
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
