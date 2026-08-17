"""长期记忆记录的来源分类、规范化与过滤。"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Any, Iterable


class MemorySource(StrEnum):
    """长期记忆记录的稳定公开来源分类。"""

    # 来自简历。
    RESUME = "resume"
    # 用户偏好。
    USER_PREFERENCE = "user_preference"
    # 面试弱项。
    INTERVIEW_WEAKNESS = "interview_weakness"
    # 无法识别。
    UNKNOWN = "unknown"


class MemoryWriteSource(StrEnum):
    """新写入长期记忆时可接受的来源分类。"""

    RESUME = MemorySource.RESUME
    USER_PREFERENCE = MemorySource.USER_PREFERENCE
    INTERVIEW_WEAKNESS = MemorySource.INTERVIEW_WEAKNESS


# 允许新写入的来源值集合（排除 UNKNOWN）。
_WRITABLE_MEMORY_SOURCES = frozenset(source.value for source in MemoryWriteSource)


def project_memory_source(record: dict[str, Any]) -> MemorySource:
    """把存储的元数据映射为稳定的公开来源分类。

    Args:
        record: 记忆记录字典。
    """
    metadata = record.get("metadata")
    raw_source = metadata.get("memory_source") if isinstance(metadata, dict) else None
    try:
        return MemorySource(str(raw_source))
    except ValueError:
        return MemorySource.UNKNOWN


def is_writable_memory_source(value: object) -> bool:
    """判断值是否可作为新的来源分类持久化。

    Args:
        value: 待判断的值。
    """
    return isinstance(value, str) and value in _WRITABLE_MEMORY_SOURCES


def filter_memory_records_by_source(
    records: Iterable[dict[str, Any]],
    sources: Iterable[MemorySource] | None,
) -> list[dict[str, Any]]:
    """按公开来源分类过滤规范化后的记忆记录。

    Args:
        records: 记忆记录序列。
        sources: 要保留的来源集合；为空时不过滤。
    """
    requested = {MemorySource(source) for source in sources or ()}
    if not requested:
        return list(records)
    return [record for record in records if project_memory_source(record) in requested]


MEMORY_DISABLED_MESSAGE = "mem0 未就绪，请检查长期记忆模型通道与 pgvector 配置"

# 助手派生记忆的文本前缀（这类记忆不持久化）。
_ASSISTANT_DERIVED_PREFIXES = (
    "user was recommended",
    "user was advised",
    "user was told to",
    "user received a recommendation",
    "用户被建议",
    "建议用户",
    "已建议用户",
    "向用户推荐",
    "为用户推荐",
)


def normalize_memory_text(text: str) -> str:
    """把记忆文本归一化（NFKC、小写、去空白与标点），用于查重。

    Args:
        text: 原始记忆文本。
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def canonicalize_memory_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对记忆记录去重：丢弃助手派生记忆，归一化文本相同的保留较新/有分者。

    Args:
        records: 记忆记录列表。
    """
    canonical: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for record in records:
        metadata = record.get("metadata")
        safe_metadata = metadata if isinstance(metadata, dict) else {}
        attributed_to = record.get("attributed_to") or safe_metadata.get("attributed_to")
        memory_text = str(record.get("memory", ""))
        # ① 助手派生记忆不入库。
        if _is_assistant_derived_memory(
            memory_text=memory_text,
            attributed_to=attributed_to,
            source=safe_metadata.get("source"),
        ):
            continue

        # ② 按归一化文本查重。
        key = normalize_memory_text(memory_text)
        if not key:
            continue

        position = positions.get(key)
        if position is None:
            positions[key] = len(canonical)
            canonical.append(record)
            continue

        # ③ 同文本冲突时保留排序更高的记录。
        if _memory_record_rank(record) > _memory_record_rank(canonical[position]):
            canonical[position] = record

    return canonical


def _is_assistant_derived_memory(
    *,
    memory_text: str,
    attributed_to: Any,
    source: Any,
) -> bool:
    """判断记忆是否为助手建议派生（不应作为候选人事实持久化）。

    Args:
        memory_text: 记忆文本。
        attributed_to: 归属者。
        source: 记忆来源。
    """
    if isinstance(attributed_to, str) and attributed_to.casefold() == "assistant":
        return True
    if source != "chat_turn":
        return False

    normalized_text = unicodedata.normalize("NFKC", memory_text).casefold().strip()
    return normalized_text.startswith(_ASSISTANT_DERIVED_PREFIXES)


def _memory_record_rank(record: dict[str, Any]) -> tuple[int, float, str]:
    """计算记忆记录的去重排序键（有分>无分，再按分数、时间）。

    Args:
        record: 记忆记录字典。
    """
    score = record.get("score")
    numeric_score = float(score) if isinstance(score, int | float) else 0.0
    timestamp = str(record.get("updated_at") or record.get("created_at") or "")
    return (int(isinstance(score, int | float)), numeric_score, timestamp)


def memory_record_to_item(record: dict[str, Any]) -> dict[str, Any]:
    """把内部记忆记录转换为对外展示条目。

    Args:
        record: 记忆记录字典。
    """
    metadata = record.get("metadata")
    item = {
        "id": record.get("id", ""),
        "memory": record.get("memory", ""),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "source": project_memory_source(record),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }
    if "score" in record:
        item["score"] = record.get("score")
    return item


def memory_history_record_to_item(record: dict[str, Any], *, memory_id: str) -> dict[str, Any]:
    """把记忆历史变更记录转换为对外展示条目。

    Args:
        record: 历史记录字典。
        memory_id: 关联的记忆 ID。
    """
    return {
        "id": record.get("id", ""),
        "memory_id": memory_id,
        "event": record.get("event", ""),
        "old_memory": record.get("old_memory"),
        "new_memory": record.get("new_memory"),
        "created_at": record.get("created_at"),
    }
