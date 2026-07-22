"""将已完成模拟面试的真实问答整理为可持久化记录。"""

from dataclasses import dataclass
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
    """执行 `_value` 相关逻辑。

    Args:
        item: 单条数据。
        name: 名称。
        default: 调用方传入的 `default` 参数。
    """
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


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
            latest_assistant[question_index] = content
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
