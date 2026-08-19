"""Deterministic evaluation coverage for the versioned interview round policy."""

import pytest

from app.domain.interview_round_strategy import (
    repair_round_plan,
    round_question_type_distribution,
    validate_round_plan,
)


@pytest.mark.parametrize(
    ("round_type", "max_questions", "model_types", "technical_assertion"),
    [
        ("tech_initial", 10, ["tech"] * 10, lambda count: count <= 5),
        ("tech_deep", 10, ["behavior"] * 10, lambda count: count == 3),
        ("hr_comprehensive", 5, ["tech", "system_design", "tech", "behavior", "tech"], lambda count: count == 0),
    ],
)
def test_round_type_distribution_is_evaluated_from_structured_types(
    round_type: str,
    max_questions: int,
    model_types: list[str],
    technical_assertion,
) -> None:
    """The evaluator never infers compliance from natural-language keywords."""

    repaired = repair_round_plan(
        [
            {
                "topic": item_type,
                "content": f"{item_type} evaluation case {index}",
                "type": item_type,
            }
            for index, item_type in enumerate(model_types, start=1)
        ],
        round_type=round_type,
        max_questions=max_questions,
    )

    distribution = round_question_type_distribution(repaired)
    assert technical_assertion(distribution["technical_total"])
    assert validate_round_plan(
        repaired,
        round_type=round_type,
        expected_count=max_questions,
    ) == []
