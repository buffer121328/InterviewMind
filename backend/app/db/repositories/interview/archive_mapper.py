"""将已完成模拟面试的真实问答整理为可持久化记录。"""

from dataclasses import dataclass
import json
from json import JSONDecodeError
import re
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ArchivedTurn:
    """一次真实作答；followup_order=0 表示主问题。"""

    question_index: int
    followup_order: int
    asked_question: str
    user_answer: str
    sequence: int

    @property
    def turn_key(self) -> str:
        """返回 `turn key` 属性值。"""
        prefix = "main" if self.followup_order == 0 else "followup"
        suffix = "" if self.followup_order == 0 else f":{self.followup_order}"
        return f"{prefix}:{self.question_index}{suffix}"


def _value(item: Any, name: str, default: Any = None) -> Any:
    """从对象或字典读取字段，兼容属性不存在和显式默认值。

    Args:
        item: 单条数据。
        name: 名称。
        default: 字段缺失或兼容对象不提供该属性时使用的安全默认值。
    """
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _decode_decision_objects(content: str) -> list[Mapping[str, Any]]:
    """连续解析相邻 JSON 对象，跳过无法解码的噪声片段。"""
    decoder = json.JSONDecoder()
    cursor = 0
    decisions: list[Mapping[str, Any]] = []
    while cursor < len(content):
        start = content.find("{", cursor)
        if start < 0:
            break
        try:
            payload, end = decoder.raw_decode(content, start)
        except JSONDecodeError:
            cursor = start + 1
            continue
        cursor = end
        if isinstance(payload, Mapping):
            decisions.append(payload)
    return decisions


def _decision_visible_text(decision: Mapping[str, Any]) -> str:
    """从一个模型决策对象读取候选人实际可见的推进或追问文本。"""
    content = decision.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    for field in ("follow_up", "advance", "end_round"):
        value = decision.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _strip_interview_transition(text: str) -> str:
    """移除评价和推进过渡语，只保留最后一个以“请”开始的明确问题。"""
    normalized = re.sub(r"\s+", " ", text).strip().strip("*\"'")
    request_markers = list(re.finditer(r"(?:^|[。！？!?，,:：；;\s])(请(?!求))", normalized))
    if request_markers:
        return normalized[request_markers[-1].start(1):].strip()
    return normalized


def extract_candidate_question(content: str) -> str:
    """从普通文本或拼接模型决策 JSON 中提取最后一个候选人可见问题。"""
    source = str(content or "").strip()
    if not source:
        return ""
    decisions = _decode_decision_objects(source)
    if decisions:
        candidate = ""
        for decision in decisions:
            visible_text = _decision_visible_text(decision)
            if visible_text:
                candidate = visible_text
        return _strip_interview_transition(candidate)
    return _strip_interview_transition(source)


def build_archived_turns(
    interview_plan: list[dict[str, Any]],
    messages: Iterable[Any],
) -> list[ArchivedTurn]:
    """按消息时间顺序提取主问题与追问的真实作答。"""
    latest_assistant: dict[int, str] = {}
    answer_counts: dict[int, int] = {}
    turns: list[ArchivedTurn] = []

    for message in messages:
        role = str(_value(message, "role", ""))
        content = str(_value(message, "content", "") or "").strip()
        question_index = int(_value(message, "question_index", 0) or 0)
        if not content or question_index < 0:
            continue

        if role == "assistant":
            visible_question = extract_candidate_question(content)
            if visible_question:
                latest_assistant[question_index] = visible_question
            continue
        if role != "user":
            continue

        followup_order = answer_counts.get(question_index, 0)
        plan_question = ""
        if question_index < len(interview_plan):
            plan_question = str(interview_plan[question_index].get("content", "")).strip()
        asked_question = latest_assistant.get(question_index) or plan_question
        if not asked_question:
            continue

        turns.append(
            ArchivedTurn(
                question_index=question_index,
                followup_order=followup_order,
                asked_question=asked_question,
                user_answer=content,
                sequence=len(turns),
            )
        )
        answer_counts[question_index] = followup_order + 1

    return turns
