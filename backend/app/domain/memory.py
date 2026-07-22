"""Memory domain mapping rules independent of HTTP routing."""

from __future__ import annotations

from typing import Any

MEMORY_DISABLED_MESSAGE = "mem0 未启用"


def memory_record_to_item(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a mem0 memory record into the API/domain memory item shape."""
    item = {
        "id": record.get("id", ""),
        "memory": record.get("memory", ""),
        "metadata": record.get("metadata", {}),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }
    if "score" in record:
        item["score"] = record.get("score")
    return item


def memory_history_record_to_item(record: dict[str, Any], *, memory_id: str) -> dict[str, Any]:
    """Normalize one mem0 memory history record."""
    return {
        "id": record.get("id", ""),
        "memory_id": memory_id,
        "event": record.get("event", ""),
        "old_memory": record.get("old_memory"),
        "new_memory": record.get("new_memory"),
        "created_at": record.get("created_at"),
    }
