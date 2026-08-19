"""Versioned interview-round question and follow-up constraints.

This module is deliberately independent of prompt construction so question-bank
selection, plan repair, local fallbacks, and runtime follow-up checks apply the
same deterministic policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from typing import Any, Final, Iterable, Mapping, Sequence

ROUND_STRATEGY_VERSION: Final[str] = "2026-08-18.interview-round-strategy.v2"
TECHNICAL_QUESTION_TYPES: Final[frozenset[str]] = frozenset({"tech", "system_design"})
NON_TECHNICAL_QUESTION_TYPES: Final[frozenset[str]] = frozenset({"intro", "behavior"})

_TYPE_ALIASES: Final[dict[str, str]] = {
    "technical": "tech",
    "technology": "tech",
    "system": "system_design",
    "system-design": "system_design",
    "system design": "system_design",
    "behaviour": "behavior",
    "hr": "behavior",
    "motivation": "behavior",
    "career": "behavior",
    "communication": "behavior",
    "collaboration": "behavior",
    "leadership": "behavior",
}


@dataclass(frozen=True, slots=True)
class InterviewRoundStrategy:
    """One authoritative strategy for planning and executing an interview round."""

    round_type: str
    name: str
    focus: str
    requirements: str
    allowed_question_types: frozenset[str]
    exact_intro_count: int | None = None
    min_technical_ratio: float = 0.0
    max_technical_ratio: float = 1.0
    min_non_technical_ratio: float = 0.0
    exact_technical_ratio: float | None = None
    allows_technical_follow_ups: bool = True


ROUND_STRATEGIES: Final[dict[str, InterviewRoundStrategy]] = {
    "tech_initial": InterviewRoundStrategy(
        round_type="tech_initial",
        name="综合面",
        focus="基础专业能力、项目概述、行为面试题、综合素质初评",
        requirements=(
            "1. 第 1 道为自我介绍题；同一轮不得再生成自我介绍题。\n"
            "2. 技术题与系统设计题合计不得超过主问题总数的 50%。\n"
            "3. 自我介绍、行为、岗位动机、沟通协作或项目贡献类问题合计不少于主问题总数的 40%。\n"
            "4. 重点考察简历中提到的核心技能和专业知识，覆盖广度而非深度。\n"
            "5. 每道题应该独立、具体，避免一道题包含过多子问题。"
        ),
        allowed_question_types=frozenset({"intro", "tech", "behavior", "system_design"}),
        exact_intro_count=1,
        max_technical_ratio=0.5,
        min_non_technical_ratio=0.4,
    ),
    "tech_deep": InterviewRoundStrategy(
        round_type="tech_deep",
        name="技术面",
        focus="项目深挖、技术验证与综合表达",
        requirements=(
            "1. 不需要自我介绍，直接进入项目、技术和综合能力问题。\n"
            "2. 技术题与系统设计题合计占主问题总数的约 30%，按最接近整数确定。\n"
            "3. 其余题目围绕项目贡献、协作、决策表达和可验证结果展开。\n"
            "4. 技术题优先验证技术原理、系统设计、权衡、故障恢复和项目真实性。\n"
            "5. 每道题聚焦单一知识点或能力维度。"
        ),
        allowed_question_types=frozenset({"tech", "behavior", "system_design"}),
        exact_technical_ratio=0.3,
    ),
    "hr_comprehensive": InterviewRoundStrategy(
        round_type="hr_comprehensive",
        name="HR面",
        focus="职业规划、软技能、文化匹配度、薪资期望、综合素质终评",
        requirements=(
            "1. 只围绕职业规划、求职动机、沟通协作、领导力、冲突处理、抗压、价值观、"
            "文化匹配、薪资或到岗等 HR 主题提问。\n"
            "2. 不得生成技术题或系统设计题。\n"
            "3. 候选人主动谈到技术实现时，只能从沟通、决策、协作或影响角度追问。\n"
            "4. 关注候选人的职业发展规划和成长潜力。"
        ),
        allowed_question_types=frozenset({"intro", "behavior"}),
        allows_technical_follow_ups=False,
    ),
    "voice_default": InterviewRoundStrategy(
        round_type="voice_default",
        name="语音面试",
        focus="全面考察候选人能力",
        requirements=(
            "1. 以自我介绍、项目经历、技术能力、问题解决、团队协作与岗位匹配为主。\n"
            "2. 每道题聚焦一个明确能力维度。"
        ),
        allowed_question_types=frozenset({"intro", "tech", "behavior", "system_design"}),
        exact_intro_count=1,
    ),
}


ROUND_QUESTION_TYPE_ORDER: Final[dict[str, tuple[str, ...]]] = {
    "tech_initial": ("intro", "tech", "behavior", "system_design"),
    "tech_deep": ("tech", "behavior", "system_design"),
    "hr_comprehensive": ("intro", "behavior"),
    "voice_default": ("intro", "tech", "behavior", "system_design"),
}


def ordered_question_types(round_type: str | None) -> tuple[str, ...]:
    """Return compatible types in the stable ordering used by database filters."""

    strategy = resolve_round_strategy(round_type)
    return ROUND_QUESTION_TYPE_ORDER[strategy.round_type]


def resolve_round_strategy(round_type: str | None) -> InterviewRoundStrategy:
    """Return the registered strategy, preserving the historical initial-round fallback."""

    return ROUND_STRATEGIES.get(str(round_type or ""), ROUND_STRATEGIES["tech_initial"])


def normalize_question_type(value: object) -> str:
    """Normalize known historical/model question-type aliases to strategy types."""

    normalized = str(value or "").strip().casefold().replace("-", "_")
    return _TYPE_ALIASES.get(normalized, normalized)


def question_type(question: Mapping[str, Any] | object) -> str:
    """Return the canonical question type from a plan or question-bank item."""

    if not isinstance(question, Mapping):
        return ""
    return normalize_question_type(question.get("type") or question.get("question_type"))


def is_technical_question(question: Mapping[str, Any] | object) -> bool:
    """Whether a structured question belongs to a technical examination track."""

    return question_type(question) in TECHNICAL_QUESTION_TYPES


def round_question_type_distribution(
    questions: Iterable[Mapping[str, Any] | object],
) -> dict[str, int]:
    """Produce safe, source-free type counts for persistence and evaluation."""

    counts = {"intro": 0, "tech": 0, "behavior": 0, "system_design": 0, "other": 0}
    for item in questions:
        normalized = question_type(item)
        counts[normalized if normalized in counts else "other"] += 1
    counts["technical_total"] = counts["tech"] + counts["system_design"]
    counts["non_technical_total"] = counts["intro"] + counts["behavior"]
    return counts


def strategy_quota(round_type: str, total_questions: int) -> dict[str, int | None]:
    """Return integer quota boundaries for a requested number of main questions."""

    total = max(0, int(total_questions or 0))
    strategy = resolve_round_strategy(round_type)
    if strategy.exact_technical_ratio is not None:
        exact_technical = min(
            total,
            floor(total * strategy.exact_technical_ratio + 0.5),
        )
        min_technical = exact_technical
        max_technical = exact_technical
    else:
        min_technical = ceil(total * strategy.min_technical_ratio)
        max_technical = floor(total * strategy.max_technical_ratio)
    return {
        "exact_intro": strategy.exact_intro_count,
        "min_technical": min_technical,
        "max_technical": max_technical,
        "min_non_technical": ceil(total * strategy.min_non_technical_ratio),
    }


def validate_round_plan(
    questions: Sequence[Mapping[str, Any] | object],
    *,
    round_type: str,
    expected_count: int | None = None,
) -> list[str]:
    """Return deterministic validation messages without inspecting question source text."""

    strategy = resolve_round_strategy(round_type)
    total = len(questions) if expected_count is None else max(0, int(expected_count))
    distribution = round_question_type_distribution(questions)
    quotas = strategy_quota(strategy.round_type, total)
    failures: list[str] = []
    if expected_count is not None and len(questions) != total:
        failures.append("question_count")
    if any(question_type(item) not in strategy.allowed_question_types for item in questions):
        failures.append("incompatible_question_type")
    exact_intro = quotas["exact_intro"]
    if exact_intro is not None and distribution["intro"] != exact_intro:
        failures.append("intro_quota")
    if distribution["technical_total"] < int(quotas["min_technical"] or 0):
        failures.append("technical_minimum")
    if distribution["technical_total"] > int(quotas["max_technical"] or 0):
        failures.append("technical_maximum")
    if distribution["non_technical_total"] < int(quotas["min_non_technical"] or 0):
        failures.append("non_technical_minimum")
    return failures


def _question_content(question: Mapping[str, Any]) -> str:
    return str(question.get("content") or question.get("question_text") or "").strip()


def _normalized_copy(
    question: Mapping[str, Any],
    *,
    round_type: str,
) -> dict[str, Any] | None:
    content = _question_content(question)
    normalized_type = question_type(question)
    if not content:
        return None
    if not normalized_type:
        normalized_type = "tech" if round_type == "tech_deep" else "behavior"
    copied = dict(question)
    copied["content"] = content
    copied["type"] = normalized_type
    copied.pop("question_type", None)
    return copied


def _deduplicated_candidates(
    candidates: Iterable[Mapping[str, Any] | object],
    *,
    round_type: str,
) -> list[dict[str, Any]]:
    strategy = resolve_round_strategy(round_type)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        item = _normalized_copy(raw, round_type=strategy.round_type)
        if item is None or item["type"] not in strategy.allowed_question_types:
            continue
        key = " ".join(item["content"].casefold().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _append_if_allowed(
    selected: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    round_type: str,
    total_questions: int,
) -> bool:
    strategy = resolve_round_strategy(round_type)
    if candidate["type"] not in strategy.allowed_question_types:
        return False
    distribution = round_question_type_distribution(selected)
    quotas = strategy_quota(strategy.round_type, total_questions)
    if candidate["type"] == "intro" and quotas["exact_intro"] is not None:
        if distribution["intro"] >= int(quotas["exact_intro"]):
            return False
    if candidate["type"] in TECHNICAL_QUESTION_TYPES:
        if distribution["technical_total"] >= int(quotas["max_technical"] or 0):
            return False
    else:
        # Preserve enough open plan slots for a required technical quota when
        # the current candidate is non-technical. This lets local fallbacks
        # repair model/question-bank candidates that contain only behavior.
        remaining_after_append = total_questions - len(selected) - 1
        if (
            distribution["technical_total"] + remaining_after_append
            < int(quotas["min_technical"] or 0)
        ):
            return False
    selected.append(candidate)
    return True


def _safe_question(round_type: str, ordinal: int, question_kind: str) -> dict[str, Any]:
    strategy = resolve_round_strategy(round_type)
    templates = {
        "intro": (
            "自我介绍",
            "请做一个简短的自我介绍，包括你的教育背景、相关经历，以及你为什么关注这个岗位。",
        ),
        "tech": (
            "技术深挖",
            f"请结合一个真实项目说明你在关键技术决策中的判断、取舍、实施过程和可验证结果（第 {ordinal} 题）。",
        ),
        "system_design": (
            "系统设计",
            f"请结合一个你参与过的业务场景，说明系统设计、主要权衡、风险控制和故障恢复思路（第 {ordinal} 题）。",
        ),
        "behavior": (
            "综合能力",
            f"请结合一个真实案例说明当时的目标和约束、你的行动、协作方式以及可验证结果（第 {ordinal} 题）。",
        ),
    }
    topic, content = templates[question_kind]
    return {
        "topic": topic,
        "content": content,
        "type": question_kind,
        "source_type": "system_fallback",
        "fallback_reason": "round_strategy_repair",
        "round_strategy_version": ROUND_STRATEGY_VERSION,
        "round_strategy": strategy.round_type,
    }


def _fallback_order(
    round_type: str,
    selected: Sequence[Mapping[str, Any]],
    *,
    total_questions: int,
) -> tuple[str, ...]:
    strategy = resolve_round_strategy(round_type)
    distribution = round_question_type_distribution(selected)
    if strategy.exact_intro_count is not None and distribution["intro"] < strategy.exact_intro_count:
        return ("intro", "behavior", "tech", "system_design")
    if strategy.round_type == "tech_initial":
        return ("behavior", "tech", "system_design")
    if strategy.round_type == "tech_deep":
        quotas = strategy_quota(strategy.round_type, total_questions)
        if distribution["technical_total"] < int(quotas["min_technical"] or 0):
            return ("tech", "system_design", "behavior")
        return ("behavior", "tech", "system_design")
    return ("behavior", "intro")


def _strategy_passes(round_type: str, candidates: Sequence[dict[str, Any]]) -> tuple[tuple[str, ...], ...]:
    strategy = resolve_round_strategy(round_type)
    if strategy.round_type == "tech_initial":
        return (("intro",), ("behavior",), ("tech", "system_design"), tuple(strategy.allowed_question_types))
    if strategy.round_type == "tech_deep":
        return (("tech", "system_design"), ("behavior",))
    return (("behavior", "intro"),)


def repair_round_plan(
    candidates: Iterable[Mapping[str, Any] | object],
    *,
    round_type: str,
    max_questions: int,
    ensure_intro: bool = True,
) -> list[dict[str, Any]]:
    """Repair a plan deterministically so no generation path bypasses round policy.

    Candidate order is preserved within each policy-required type pass.  When the
    model/question-bank candidates cannot meet the contract, locally generated
    safe questions complete the plan without an additional LLM call.
    """

    requested = max(0, int(max_questions or 0))
    if requested == 0:
        return []
    strategy = resolve_round_strategy(round_type)
    prepared = _deduplicated_candidates(candidates, round_type=strategy.round_type)
    selected: list[dict[str, Any]] = []

    for allowed_types in _strategy_passes(strategy.round_type, prepared):
        for item in prepared:
            if len(selected) >= requested or item["type"] not in allowed_types:
                continue
            if not ensure_intro and item["type"] == "intro":
                continue
            _append_if_allowed(
                selected,
                item,
                round_type=strategy.round_type,
                total_questions=requested,
            )

    for item in prepared:
        if len(selected) >= requested or item in selected:
            continue
        if not ensure_intro and item["type"] == "intro":
            continue
        _append_if_allowed(
            selected,
            item,
            round_type=strategy.round_type,
            total_questions=requested,
        )

    attempt = 0
    while len(selected) < requested:
        attempt += 1
        added = False
        for question_kind in _fallback_order(
            strategy.round_type,
            selected,
            total_questions=requested,
        ):
            if not ensure_intro and question_kind == "intro":
                continue
            fallback = _safe_question(strategy.round_type, len(selected) + 1 + attempt, question_kind)
            if _append_if_allowed(
                selected,
                fallback,
                round_type=strategy.round_type,
                total_questions=requested,
            ):
                added = True
                break
        if not added:
            # All strategies define a non-empty compatible fallback order. This
            # guard prevents a future misconfiguration from causing an infinite loop.
            break

    for index, item in enumerate(selected, start=1):
        item["id"] = index
        item["round_strategy_version"] = ROUND_STRATEGY_VERSION
        item["round_strategy"] = strategy.round_type
    return selected


def select_question_bank_candidates(
    candidates: Iterable[Mapping[str, Any] | object],
    *,
    round_type: str,
    plan_max_questions: int,
    selection_limit: int,
) -> list[dict[str, Any]]:
    """Keep priority-ordered bank rows that fit the round's hard upper bounds.

    Callers pass rows already ordered by ``required``, ``high``, ``low`` and
    stable tie breakers. This helper therefore never reorders those rows; it
    only rejects incompatible or over-quota types and never synthesizes a
    fallback question for a user-configured question-bank quota.
    """

    if selection_limit <= 0 or plan_max_questions <= 0:
        return []
    strategy = resolve_round_strategy(round_type)
    prepared = _deduplicated_candidates(candidates, round_type=strategy.round_type)
    selected: list[dict[str, Any]] = []
    for item in prepared:
        if len(selected) >= selection_limit:
            break
        _append_if_allowed(
            selected,
            item,
            round_type=strategy.round_type,
            total_questions=plan_max_questions,
        )
    for item in selected:
        item["round_strategy_version"] = ROUND_STRATEGY_VERSION
        item["round_strategy"] = strategy.round_type
    return selected


def allows_technical_follow_ups(round_type: str | None) -> bool:
    """Whether the round may open a technical follow-up branch at runtime."""

    return resolve_round_strategy(round_type).allows_technical_follow_ups
