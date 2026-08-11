"""提供面试相关后端功能。"""

from __future__ import annotations

from typing import Final

ROUND_TYPE_DEFAULT_QUESTIONS: Final[dict[str, int]] = {
    "tech_initial": 10,
    "tech_deep": 20,
    "hr_comprehensive": 5,
}

ROUND_INDEX_DEFAULT_TYPES: Final[dict[int, str]] = {
    1: "tech_initial",
    2: "tech_deep",
    3: "hr_comprehensive",
}

DEFAULT_ROUND_TYPE: Final[str] = "tech_initial"
MIN_QUESTIONS: Final[int] = 1
MAX_QUESTIONS: Final[int] = 20
MAX_INTERVIEW_ROUNDS: Final[int] = 3
SYSTEM_FALLBACK_QUESTION_SOURCE_TYPE: Final[str] = "system_fallback"
INTERVIEW_CLOSING_MESSAGE: Final[str] = (
    "感谢你的分享，你的规划很有条理。本次面试到此结束，后续我们会尽快联系你。"
)



def validate_next_round_index(round_index: int) -> int:
    """校验轮次索引相关后端逻辑。"""
    if round_index < 2 or round_index > MAX_INTERVIEW_ROUNDS:
        raise ValueError(f"同一家公司最多只能进行 {MAX_INTERVIEW_ROUNDS} 轮面试")
    return round_index

def valid_round_types() -> tuple[str, ...]:
    """处理有效轮次类型相关后端逻辑。"""
    return tuple(ROUND_TYPE_DEFAULT_QUESTIONS.keys())


def resolve_round_type(round_type: str | None = None, *, round_index: int | None = None) -> str:
    """解析轮次类型相关后端逻辑。"""
    candidate = round_type or ROUND_INDEX_DEFAULT_TYPES.get(round_index or 1, "hr_comprehensive")
    if candidate not in ROUND_TYPE_DEFAULT_QUESTIONS:
        allowed = ", ".join(valid_round_types())
        raise ValueError(f"unsupported round_type: {candidate!r}; expected one of: {allowed}")
    return candidate


def default_questions_for_round_type(
    round_type: str | None = None,
    *,
    round_index: int | None = None,
) -> int:
    """处理默认题目轮次类型相关后端逻辑。"""
    return ROUND_TYPE_DEFAULT_QUESTIONS[resolve_round_type(round_type, round_index=round_index)]


def resolve_max_questions(
    round_type: str | None,
    max_questions: int | None = None,
    *,
    round_index: int | None = None,
) -> int:
    """解析最大题目相关后端逻辑。"""
    resolved_round_type = resolve_round_type(round_type, round_index=round_index)
    resolved = max_questions if max_questions is not None else ROUND_TYPE_DEFAULT_QUESTIONS[resolved_round_type]
    try:
        resolved_int = int(resolved)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_questions must be an integer") from exc
    if resolved_int < MIN_QUESTIONS or resolved_int > MAX_QUESTIONS:
        raise ValueError(f"max_questions must be between {MIN_QUESTIONS} and {MAX_QUESTIONS}")
    return resolved_int
