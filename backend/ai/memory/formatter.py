"""
记忆格式化模块

将 mem0 搜索结果格式化为 prompt context，注入到面试流程中。
"""

import logging
from typing import Optional

from .config import get_mem0_context_char_limit

logger = logging.getLogger(__name__)

# 记忆类型中文映射
MEMORY_TYPE_LABELS = {
    "preference": "偏好",
    "candidate_fact": "候选人事实",
    "weakness": "短板",
    "practice_goal": "练习目标",
    "delivery_strategy": "投递策略",
    "safety_preference": "隐私偏好",
}


def format_memory_context(
    memories: list[dict],
    max_items: int = 5,
    char_limit: Optional[int] = None,
) -> str:
    """
    将 mem0 搜索结果格式化为 prompt context

    Args:
        memories: mem0 返回的记忆列表
        max_items: 最大条数
        char_limit: 总字符数限制

    Returns:
        str: 格式化后的记忆上下文，如果没有记忆则返回空字符串
    """
    if not memories:
        return ""

    # 应用字符数限制
    if char_limit is None:
        char_limit = get_mem0_context_char_limit()

    # 取前 max_items 条
    items = memories[:max_items]

    lines = [
        "[长期记忆]",
        "以下内容来自 mem0 长期记忆，可能随时间变化。若与用户当前输入冲突，以当前输入为准，并先确认是否更新记忆。",
        "",
    ]

    total_chars = len("\n".join(lines))

    for i, memory in enumerate(items, 1):
        # 提取记忆内容
        content = memory.get("memory", "")
        if not content:
            content = memory.get("text", "")
        if not content:
            continue

        # 提取记忆类型
        metadata = memory.get("metadata", {})
        memory_type = metadata.get("memory_type", "")
        type_label = MEMORY_TYPE_LABELS.get(memory_type, memory_type)

        # 格式化单条记忆
        if type_label:
            line = f"{i}. [{type_label}] {content}"
        else:
            line = f"{i}. {content}"

        # 检查字符数限制
        if total_chars + len(line) + 1 > char_limit:
            logger.debug(f"记忆上下文达到字符数限制: {total_chars}/{char_limit}")
            break

        lines.append(line)
        total_chars += len(line) + 1  # +1 for newline

    return "\n".join(lines)


def format_memory_for_planner(
    memories: list[dict],
    max_items: int = 5,
) -> str:
    """
    为 planner 节点格式化记忆上下文

    侧重于短板和练习目标，帮助规划面试题目。

    Args:
        memories: mem0 返回的记忆列表
        max_items: 最大条数

    Returns:
        str: 格式化后的记忆上下文
    """
    if not memories:
        return ""

    # 按记忆类型分组
    weaknesses = []
    goals = []
    facts = []
    others = []

    for m in memories:
        meta = m.get("metadata", {})
        mtype = meta.get("memory_type", "")

        if mtype == "weakness":
            weaknesses.append(m)
        elif mtype == "practice_goal":
            goals.append(m)
        elif mtype == "candidate_fact":
            facts.append(m)
        else:
            others.append(m)

    # 优先显示短板和目标
    prioritized = weaknesses + goals + facts + others

    return format_memory_context(prioritized, max_items=max_items)


def format_memory_for_responder(
    memories: list[dict],
    max_items: int = 3,
) -> str:
    """
    为 responder 节点格式化记忆上下文

    侧重于用户偏好，帮助调整回复风格。

    Args:
        memories: mem0 返回的记忆列表
        max_items: 最大条数

    Returns:
        str: 格式化后的记忆上下文
    """
    if not memories:
        return ""

    # 按记忆类型分组
    preferences = []
    others = []

    for m in memories:
        meta = m.get("metadata", {})
        mtype = meta.get("memory_type", "")

        if mtype == "preference":
            preferences.append(m)
        else:
            others.append(m)

    # 优先显示偏好
    prioritized = preferences + others

    return format_memory_context(prioritized, max_items=max_items)


def format_memory_for_summary(
    memories: list[dict],
    max_items: int = 5,
) -> str:
    """
    为 summary 节点格式化记忆上下文

    侧重于历史短板和目标，帮助生成有针对性的总结。

    Args:
        memories: mem0 返回的记忆列表
        max_items: 最大条数

    Returns:
        str: 格式化后的记忆上下文
    """
    if not memories:
        return ""

    # 按记忆类型分组
    weaknesses = []
    goals = []
    others = []

    for m in memories:
        meta = m.get("metadata", {})
        mtype = meta.get("memory_type", "")

        if mtype == "weakness":
            weaknesses.append(m)
        elif mtype == "practice_goal":
            goals.append(m)
        else:
            others.append(m)

    # 优先显示短板和目标
    prioritized = weaknesses + goals + others

    return format_memory_context(prioritized, max_items=max_items)
