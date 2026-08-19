"""将题库/面经候选题转换并合入面试计划。"""

from math import floor
from typing import Any, Iterable, Mapping

from app.domain.interview_round_strategy import (
    ROUND_STRATEGY_VERSION,
    repair_round_plan,
    select_question_bank_candidates,
)
from app.domain.interview_round_strategy import (
    is_technical_question as _strategy_is_technical_question,
)

from .answer_points import ensure_question_answer_points


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """规范化 `candidate`。

    Args:
        candidate: 经过类型边界校验的 `candidate`；其格式和可选值由参数类型及调用流程约束。
    """
    content = str(candidate.get("question_text") or candidate.get("content") or "").strip()
    if not content:
        return None
    item = ensure_question_answer_points({
        "topic": str(candidate.get("target_skill") or candidate.get("topic") or "题库题"),
        "content": content,
        "type": str(candidate.get("question_type") or candidate.get("type") or "tech"),
        "answer_points": candidate.get("answer_points"),
        "hint": str(candidate.get("reference_answer") or candidate.get("hint") or ""),
        "source_type": str(candidate.get("source_type") or "question_bank"),
        "source_id": candidate.get("source_id"),
        "tags": candidate.get("tags") if isinstance(candidate.get("tags"), list) else [],
        "difficulty": str(candidate.get("difficulty") or "medium"),
        "followups": candidate.get("followups") if isinstance(candidate.get("followups"), list) else [],
    })
    if candidate.get("id") is not None:
        item["question_bank_item_id"] = candidate["id"]
    return item


def prepare_candidates(
    experience_questions: Iterable[dict[str, Any]],
    question_bank_items: Iterable[dict[str, Any]],
    max_questions: int,
) -> list[dict[str, Any]]:
    """面经显式选择优先，并按题目文本去重。

    Args:
        experience_questions: 经验相关题目列表。
        question_bank_items: 题库题目列表。
        max_questions: 计划题目数。
    """
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in [*experience_questions, *question_bank_items]:
        item = normalize_candidate(raw)
        if item is None:
            continue
        key = " ".join(item["content"].lower().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= max_questions:
            break
    return result


INTRODUCTION_ROUND_TYPES = frozenset({"tech_initial", "voice_default"})
_TECHNICAL_QUESTION_TYPES = frozenset({"tech", "technical", "system_design"})


def _question_text(question: object) -> str:
    """提取候选题的题干文本，兼容计划、题库和纯文本输入。

    Args:
        question: 候选题字典或题干文本。
    """

    if isinstance(question, Mapping):
        return str(
            question.get("content")
            or question.get("question_text")
            or question.get("topic")
            or ""
        ).strip()
    return str(question or "").strip()


def is_introduction_question(question: object) -> bool:
    """判断题目是否要求候选人介绍自身背景或经历。

    优先使用结构化题型；对题库和模型输出中常见的非标准题型，使用
    收敛的中文题干模式补足识别，避免将“介绍项目架构”等技术题误判。

    Args:
        question: 候选题字典或题干文本。
    """

    if isinstance(question, Mapping):
        question_type = question.get("type") or question.get("question_type")
        if isinstance(question_type, str) and question_type.strip().casefold() == "intro":
            return True

    normalized = "".join(_question_text(question).casefold().split())
    if not normalized:
        return False
    return (
        "自我介绍" in normalized
        or "介绍一下你自己" in normalized
        or "介绍你自己" in normalized
        or ("教育背景" in normalized and "工作经历" in normalized)
        or ("个人背景" in normalized and "工作经历" in normalized)
    )


def prepare_question_bank_candidates(
    question_bank_items: Iterable[dict[str, Any]],
    max_questions: int,
    *,
    round_type: str = "tech_initial",
    selection_limit: int | None = None,
    enforce_strategy: bool = False,
) -> list[dict[str, Any]]:
    """Convert ordered question-bank items and optionally enforce round quotas.

    Compatibility callers retain the historical conversion-only behavior. The
    interview start flows opt into ``enforce_strategy`` before planning so a
    user-configured question-bank quota cannot bypass the shared policy.
    """

    limit = max_questions if selection_limit is None else min(max_questions, selection_limit)
    candidates = prepare_candidates((), question_bank_items, limit)
    if not enforce_strategy:
        return candidates
    selected = select_question_bank_candidates(
        candidates,
        round_type=round_type,
        plan_max_questions=max_questions,
        selection_limit=limit,
    )
    return [ensure_question_answer_points(item) for item in selected]


def _legacy_merge_question_plan(
    candidates: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    max_questions: int,
    *,
    round_type: str,
) -> list[dict[str, Any]]:
    """Preserve established merge ordering for non-governed compatibility callers."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    limit_introduction = round_type in INTRODUCTION_ROUND_TYPES
    introduction_seen = False
    for item in [*candidates, *generated]:
        content = _question_text(item)
        key = " ".join(content.casefold().split())
        if not content or key in seen:
            continue
        if limit_introduction and is_introduction_question(item):
            if introduction_seen:
                continue
            introduction_seen = True
        seen.add(key)
        merged.append(ensure_question_answer_points(item))
        if len(merged) >= max_questions:
            break
    for index, item in enumerate(merged, start=1):
        item["id"] = index
    return merged


def merge_question_plan(
    candidates: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    max_questions: int,
    *,
    round_type: str = "tech_initial",
    enforce_strategy: bool = False,
) -> list[dict[str, Any]]:
    """Merge plans, with explicit opt-in to deterministic strategy repair.

    Existing programmatic callers retain the legacy de-duplication contract;
    real interview-start workflows pass ``enforce_strategy=True`` and receive
    quota repairs and local safe fill-ins.
    """

    legacy = _legacy_merge_question_plan(
        candidates,
        generated,
        max_questions,
        round_type=round_type,
    )
    if not enforce_strategy:
        return legacy
    merged = repair_round_plan(
        legacy,
        round_type=round_type,
        max_questions=max_questions,
    )
    for item in merged:
        item.setdefault("round_strategy_version", ROUND_STRATEGY_VERSION)
    return [ensure_question_answer_points(item) for item in merged]


def is_technical_question(question: object) -> bool:
    """判断题目是否属于技术题。

    题目可能来自旧的 ``type`` 字段，也可能来自题库的
    ``question_type`` 字段；非字典或缺少题型时按非技术题处理。

    Args:
        question: 题目文本。
    """

    if not isinstance(question, dict):
        return False
    return _strategy_is_technical_question(question)


def technical_follow_up_budget(plan: Iterable[dict[str, Any]] | None) -> int:
    """按全部主问题数计算本轮最多技术追问数。

    追问预算固定为主问题总数的 20% 向下取整。调用方仍会在运行时
    限制只有技术主问题可追问；不足五道主问题时不保留最低一次追问。

    Args:
        plan: 计划数据。
    """

    total_main_questions = sum(1 for _ in (plan or ()))
    return floor(total_main_questions * 0.2)
