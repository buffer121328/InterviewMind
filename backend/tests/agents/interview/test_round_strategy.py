"""Acceptance tests for deterministic three-round interview strategy enforcement."""

import pytest

from ai.agents.interview.interview_runtime import InterviewRuntime
from ai.prompts.voice import build_interview_voice_system_prompt
from app.domain.interview_round_strategy import (
    ROUND_STRATEGY_VERSION,
    repair_round_plan,
    round_question_type_distribution,
    select_question_bank_candidates,
    validate_round_plan,
)


async def _unused_invoker(*_args, **_kwargs):
    raise AssertionError("This test does not invoke a model")


def _question(question_type: str, index: int) -> dict[str, str]:
    return {
        "topic": question_type,
        "content": f"{question_type} question {index}",
        "type": question_type,
    }


def test_initial_round_repair_enforces_balanced_distribution_and_version() -> None:
    repaired = repair_round_plan(
        [*[_question("tech", index) for index in range(8)], _question("behavior", 9)],
        round_type="tech_initial",
        max_questions=10,
    )

    distribution = round_question_type_distribution(repaired)
    assert len(repaired) == 10
    assert distribution["intro"] == 1
    assert distribution["technical_total"] <= 5
    assert distribution["non_technical_total"] >= 4
    assert validate_round_plan(repaired, round_type="tech_initial", expected_count=10) == []
    assert {item["round_strategy_version"] for item in repaired} == {ROUND_STRATEGY_VERSION}


def test_deep_round_repairs_to_exact_rounded_thirty_percent_technical_mix() -> None:
    repaired = repair_round_plan(
        [_question("intro", 1), *[_question("tech", index) for index in range(2, 21)]],
        round_type="tech_deep",
        max_questions=20,
    )

    distribution = round_question_type_distribution(repaired)
    assert len(repaired) == 20
    assert distribution["technical_total"] == 6
    assert distribution["behavior"] == 14
    assert distribution["intro"] == 0
    assert validate_round_plan(repaired, round_type="tech_deep", expected_count=20) == []


def test_deep_round_uses_nearest_integer_for_non_divisible_question_counts() -> None:
    repaired = repair_round_plan([], round_type="tech_deep", max_questions=7)

    distribution = round_question_type_distribution(repaired)
    assert len(repaired) == 7
    assert distribution["technical_total"] == 2
    assert distribution["behavior"] == 5
    assert validate_round_plan(repaired, round_type="tech_deep", expected_count=7) == []


def test_hr_round_never_retains_technical_main_questions() -> None:
    repaired = repair_round_plan(
        [*[_question("tech", index) for index in range(4)], _question("system_design", 5)],
        round_type="hr_comprehensive",
        max_questions=5,
    )

    distribution = round_question_type_distribution(repaired)
    assert len(repaired) == 5
    assert distribution["technical_total"] == 0
    assert validate_round_plan(repaired, round_type="hr_comprehensive", expected_count=5) == []


def test_question_bank_selection_cannot_use_required_technical_questions_to_break_initial_cap() -> None:
    selected = select_question_bank_candidates(
        [
            {**_question("tech", index), "priority": "required", "source_type": "question_bank"}
            for index in range(1, 8)
        ]
        + [{**_question("behavior", 8), "priority": "low", "source_type": "question_bank"}],
        round_type="tech_initial",
        plan_max_questions=10,
        selection_limit=8,
    )

    distribution = round_question_type_distribution(selected)
    assert len(selected) <= 8
    assert distribution["technical_total"] <= 5
    assert all(item["source_type"] == "question_bank" for item in selected)


def test_hr_runtime_blocks_follow_up_for_legacy_technical_plan() -> None:
    runtime = InterviewRuntime(
        {
            "interview_plan": [_question("tech", 1)],
            "current_question_index": 0,
            "round_type": "hr_comprehensive",
            "max_follow_ups": 2,
            "max_total_follow_ups": 2,
        },
        _unused_invoker,
    )

    assert runtime._follow_up_block_reason() == "当前轮次禁止技术追问"


def test_hr_voice_prompt_prohibits_technical_follow_ups() -> None:
    prompt = build_interview_voice_system_prompt(
        [_question("behavior", 1)],
        round_type="hr_comprehensive",
    )

    assert "不得发起算法、技术原理、架构或系统设计追问" in prompt


async def _metadata_invoker(*_args, **kwargs):
    return kwargs["call_metadata"]


class _MetadataContext:
    def model_event_fields(self) -> dict[str, object]:
        return {"context_contract_version": "test"}


@pytest.mark.asyncio
async def test_runtime_model_metadata_contains_safe_round_policy_fields() -> None:
    runtime = InterviewRuntime(
        {
            "interview_plan": [_question("tech", 1), _question("behavior", 2)],
            "current_question_index": 0,
            "round_type": "tech_initial",
            "round_strategy_version": ROUND_STRATEGY_VERSION,
        },
        _metadata_invoker,
    )

    assert runtime.round_strategy_version == ROUND_STRATEGY_VERSION
    assert runtime.round_question_type_distribution == {
        "intro": 0,
        "tech": 1,
        "behavior": 1,
        "system_design": 0,
        "other": 0,
        "technical_total": 1,
        "non_technical_total": 1,
    }

    metadata = await runtime._invoke_evaluating_model("prompt", _MetadataContext().model_event_fields())
    assert metadata["round_strategy_version"] == ROUND_STRATEGY_VERSION
    assert metadata["round_question_type_distribution"] == runtime.round_question_type_distribution
    assert "content" not in metadata
