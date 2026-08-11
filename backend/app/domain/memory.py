"""提供记忆相关后端功能。"""

from __future__ import annotations

import unicodedata
from typing import Any

MEMORY_DISABLED_MESSAGE = "mem0 未就绪，请检查长期记忆模型通道与 pgvector 配置"

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
    """规范化记忆文本相关后端逻辑。"""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def canonicalize_memory_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """处理规范化记忆记录相关后端逻辑。"""

    canonical: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for record in records:
        metadata = record.get("metadata")
        safe_metadata = metadata if isinstance(metadata, dict) else {}
        attributed_to = record.get("attributed_to") or safe_metadata.get("attributed_to")
        memory_text = str(record.get("memory", ""))
        if _is_assistant_derived_memory(
            memory_text=memory_text,
            attributed_to=attributed_to,
            source=safe_metadata.get("source"),
        ):
            continue

        key = normalize_memory_text(memory_text)
        if not key:
            continue

        position = positions.get(key)
        if position is None:
            positions[key] = len(canonical)
            canonical.append(record)
            continue

        if _memory_record_rank(record) > _memory_record_rank(canonical[position]):
            canonical[position] = record

    return canonical


def _is_assistant_derived_memory(
    *,
    memory_text: str,
    attributed_to: Any,
    source: Any,
) -> bool:
    """处理记忆相关后端逻辑。"""

    if isinstance(attributed_to, str) and attributed_to.casefold() == "assistant":
        return True
    if source != "chat_turn":
        return False

    normalized_text = unicodedata.normalize("NFKC", memory_text).casefold().strip()
    return normalized_text.startswith(_ASSISTANT_DERIVED_PREFIXES)


def _memory_record_rank(record: dict[str, Any]) -> tuple[int, float, str]:
    """处理记忆记录排序相关后端逻辑。"""

    score = record.get("score")
    numeric_score = float(score) if isinstance(score, int | float) else 0.0
    timestamp = str(record.get("updated_at") or record.get("created_at") or "")
    return (int(isinstance(score, int | float)), numeric_score, timestamp)


def memory_record_to_item(record: dict[str, Any]) -> dict[str, Any]:
    """处理记忆记录条目相关后端逻辑。"""
    metadata = record.get("metadata")
    item = {
        "id": record.get("id", ""),
        "memory": record.get("memory", ""),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }
    if "score" in record:
        item["score"] = record.get("score")
    return item


def memory_history_record_to_item(record: dict[str, Any], *, memory_id: str) -> dict[str, Any]:
    """处理记忆历史记录条目相关后端逻辑。"""
    return {
        "id": record.get("id", ""),
        "memory_id": memory_id,
        "event": record.get("event", ""),
        "old_memory": record.get("old_memory"),
        "new_memory": record.get("new_memory"),
        "created_at": record.get("created_at"),
    }
