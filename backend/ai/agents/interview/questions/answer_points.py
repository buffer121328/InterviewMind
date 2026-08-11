"""面试题回答要点的规范化、兜底和序列化工具。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_MAX_ANSWER_POINTS = 5
_MAX_POINT_CHARS = 180


def normalize_answer_points(value: Any) -> list[str]:
    """把列表或多行文本规范为有序、去重且有长度上限的回答要点。"""
    if isinstance(value, str):
        candidates = re.split(r"[\r\n]+", value)
    elif isinstance(value, (list, tuple)):
        candidates = [str(item) for item in value]
    else:
        return []

    points: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        point = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", raw).strip()
        if not point:
            continue
        point = point[:_MAX_POINT_CHARS]
        key = " ".join(point.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        points.append(point)
        if len(points) >= _MAX_ANSWER_POINTS:
            break
    return points


def fallback_answer_points(question: Mapping[str, Any]) -> list[str]:
    """根据题型生成不依赖候选人虚构经历的中文兜底回答要点。"""
    question_type = str(question.get("type") or question.get("question_type") or "tech")
    topic = str(question.get("topic") or question.get("target_skill") or "核心主题").strip()
    if question_type == "intro":
        return [
            "按教育与工作经历、核心能力、岗位匹配三个部分简洁展开",
            "用可核验的项目职责或结果证明关键能力，避免泛泛而谈",
        ]
    if question_type == "behavior":
        return [
            "按情境、目标、行动、结果和复盘组织真实案例",
            "明确自己的职责、关键决策以及可验证的结果或反馈",
        ]
    if question_type == "system_design":
        return [
            "先澄清规模、可靠性、成本和一致性等关键约束",
            "说明核心组件、数据流、技术取舍、故障处理与验证指标",
        ]
    return [
        f"先说明{topic or '该主题'}的核心概念、适用边界和关键原理",
        "结合真实项目说明方案选择、实现步骤、风险处理和验证结果",
    ]


def ensure_question_answer_points(question: Mapping[str, Any]) -> dict[str, Any]:
    """返回带非空 `answer_points` 的题目副本，并兼容旧 `hint`/参考答案字段。"""
    normalized = dict(question)
    points = normalize_answer_points(normalized.get("answer_points"))
    if not points:
        points = normalize_answer_points(
            normalized.get("reference_answer") or normalized.get("hint")
        )
    if not points:
        points = fallback_answer_points(normalized)
    normalized["answer_points"] = points
    return normalized


def ensure_plan_answer_points(
    plan: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """规范化整份面试计划，并标记是否需要持久化兼容结果。"""
    normalized_plan: list[dict[str, Any]] = []
    changed = False
    for raw in plan:
        original = dict(raw)
        normalized = ensure_question_answer_points(original)
        normalized_plan.append(normalized)
        changed = changed or normalized != original
    return normalized_plan, changed


def format_question_answer_points(question: Mapping[str, Any]) -> str | None:
    """把题目中的结构化回答要点序列化为题库兼容的逐行文本。"""
    points = normalize_answer_points(question.get("answer_points"))
    if points:
        return "\n".join(points)
    legacy_hint = str(question.get("hint") or "").strip()
    return legacy_hint or None


def answer_points_hint(question: Mapping[str, Any]) -> str | None:
    """把持久化回答要点格式化为候选人主动请求时可读的提示文本。"""
    points = normalize_answer_points(question.get("answer_points"))
    if points:
        return "\n".join(f"{index}. {point}" for index, point in enumerate(points, start=1))
    legacy_hint = str(question.get("hint") or "").strip()
    return legacy_hint or None
