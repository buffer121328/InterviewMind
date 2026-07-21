"""统一面试轮次类型与默认题数规则。"""

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


def valid_round_types() -> tuple[str, ...]:
    """返回当前支持的面试类型。"""
    return tuple(ROUND_TYPE_DEFAULT_QUESTIONS.keys())


def resolve_round_type(round_type: str | None = None, *, round_index: int | None = None) -> str:
    """解析并校验面试类型。

    未传 ``round_type`` 时按轮次自动推进：1=综合面，2=技术深挖，3+=HR 综合。
    传入非法类型时抛出 ``ValueError``，让 API schema 返回明确的 422。
    """
    candidate = round_type or ROUND_INDEX_DEFAULT_TYPES.get(round_index or 1, "hr_comprehensive")
    if candidate not in ROUND_TYPE_DEFAULT_QUESTIONS:
        allowed = ", ".join(valid_round_types())
        raise ValueError(f"unsupported round_type: {candidate!r}; expected one of: {allowed}")
    return candidate


def default_questions_for_round_type(round_type: str | None = None, *, round_index: int | None = None) -> int:
    """获取某轮面试类型对应的默认题数。"""
    return ROUND_TYPE_DEFAULT_QUESTIONS[resolve_round_type(round_type, round_index=round_index)]


def resolve_max_questions(round_type: str | None, max_questions: int | None = None, *, round_index: int | None = None) -> int:
    """解析最大题数：显式传入值优先，否则使用面试类型默认值。"""
    resolved_round_type = resolve_round_type(round_type, round_index=round_index)
    resolved = max_questions if max_questions is not None else ROUND_TYPE_DEFAULT_QUESTIONS[resolved_round_type]
    try:
        resolved_int = int(resolved)
    except (TypeError, ValueError) as exc:  # pragma: no cover - Pydantic 通常已拦截
        raise ValueError("max_questions must be an integer") from exc
    if resolved_int < MIN_QUESTIONS or resolved_int > MAX_QUESTIONS:
        raise ValueError(f"max_questions must be between {MIN_QUESTIONS} and {MAX_QUESTIONS}")
    return resolved_int
