"""可持久化的简历人工审阅规则。

状态保存在 resume_results.result_data 中；本模块不依赖进程内存，
因此服务重启后仍可恢复。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


class ReviewConflictError(ValueError):
    """审阅版本已变更。"""


def initialize_review(result_data: dict[str, Any]) -> dict[str, Any]:
    """为新的优化结果初始化持久化审阅状态。"""
    result = _ensure_item_ids(deepcopy(result_data))
    items = result.get("confirmation_items") or []
    result["human_review"] = {
        "status": "pending" if items else "not_required",
        "version": 1,
        "decisions": {},
        "events": [],
        "resolved_resume": result.get("assembled_resume") if not items else None,
    }
    return result


def apply_review_decisions(
    result_data: dict[str, Any],
    *,
    decisions: list[dict[str, str]],
    expected_version: int,
) -> dict[str, Any]:
    """应用审阅决定，并在所有项已处理时生成最终简历。"""
    result = _ensure_item_ids(deepcopy(result_data))
    review = result.get("human_review") or initialize_review(result)["human_review"]
    current_version = int(review.get("version", 1))
    if current_version != expected_version:
        raise ReviewConflictError(
            f"审阅版本冲突：期望 {expected_version}，当前 {current_version}"
        )

    items = {item.get("item_id"): item for item in result.get("confirmation_items") or []}
    if not items:
        raise ValueError("该结果无需人工审阅")

    stored_decisions = dict(review.get("decisions") or {})
    events = list(review.get("events") or [])
    now = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()
    for decision in decisions:
        item_id = decision["item_id"]
        action = decision["decision"]
        if item_id in seen:
            raise ValueError(f"重复的审阅项: {item_id}")
        if item_id not in items:
            raise ValueError(f"未知的审阅项: {item_id}")
        if action not in {"approved", "rejected"}:
            raise ValueError(f"无效的审阅决定: {action}")
        seen.add(item_id)
        stored_decisions[item_id] = action
        events.append({"item_id": item_id, "decision": action, "at": now})

    unresolved = set(items) - set(stored_decisions)
    resolved_resume = None
    status = "pending"
    if not unresolved:
        resolved_resume = _resolve_resume(result.get("assembled_resume", ""), items, stored_decisions)
        status = "completed"

    result["human_review"] = {
        "status": status,
        "version": current_version + 1,
        "decisions": stored_decisions,
        "events": events,
        "resolved_resume": resolved_resume,
    }
    return result


def public_review_state(result_data: dict[str, Any]) -> dict[str, Any]:
    """返回前端所需的审阅状态，不暴露内部事件记录。"""
    result_data = _ensure_item_ids(deepcopy(result_data))
    review = result_data.get("human_review") or initialize_review(result_data)["human_review"]
    decisions = review.get("decisions") or {}
    items = []
    for item in result_data.get("confirmation_items") or []:
        public_item = dict(item)
        public_item["status"] = decisions.get(item.get("item_id"), "pending")
        items.append(public_item)
    return {
        "status": review["status"],
        "version": review["version"],
        "items": items,
        "resolved_resume": review.get("resolved_resume"),
    }


def _ensure_item_ids(result_data: dict[str, Any]) -> dict[str, Any]:
    """确保 `item ids`。

    Args:
        result_data: result 数据。
    """
    for index, item in enumerate(result_data.get("confirmation_items") or []):
        if item.get("item_id"):
            continue
        canonical_item = {key: value for key, value in item.items() if key != "item_id"}
        canonical = json.dumps(
            {"index": index, "item": canonical_item},
            ensure_ascii=False,
            sort_keys=True,
        )
        item["item_id"] = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    return result_data


def _resolve_resume(
    assembled_resume: str,
    items: dict[str, dict[str, Any]],
    decisions: dict[str, str],
) -> str:
    """解析 `resume`。

    Args:
        assembled_resume: 调用方传入的 `assembled_resume` 参数。
        items: 数据列表。
        decisions: 调用方传入的 `decisions` 参数。
    """
    resolved = assembled_resume
    for item_id, decision in decisions.items():
        if decision != "rejected":
            continue
        item = items[item_id]
        optimized = str(item.get("optimized_text") or "")
        original = str(item.get("original_text") or "")
        if not optimized or optimized not in resolved:
            raise ReviewConflictError(f"无法安全撤回审阅项: {item_id}")
        resolved = resolved.replace(optimized, original, 1)
    return resolved
