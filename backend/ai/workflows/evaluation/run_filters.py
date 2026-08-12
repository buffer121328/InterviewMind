"""评测运行脱敏记录的纯筛选谓词。"""

from __future__ import annotations

from typing import Any


def record_has_tool(record: Any, tool_name: str) -> bool:
    """只从 owner 已授权的脱敏 record 中匹配工具名。"""
    if not isinstance(record, dict):
        return False
    return any(
        isinstance(item, dict) and item.get("tool_name") == tool_name
        for item in record.get("tool_calls") or ()
    )


def record_has_tool_effect(record: Any, tool_effect: str) -> bool:
    """只从脱敏 ToolCall 列表匹配副作用等级。"""
    return record_has_item_value(
        record,
        collection="tool_calls",
        key="effect",
        value=tool_effect,
    )


def record_has_tool_status(record: Any, tool_status: str) -> bool:
    """只从脱敏 ToolCall 列表匹配工具终态。"""
    return record_has_item_value(
        record,
        collection="tool_calls",
        key="status",
        value=tool_status,
    )


def record_has_approval_status(record: Any, approval_status: str) -> bool:
    """从 ToolCall 或 Approval 安全字段匹配审批状态。"""
    return record_has_item_value(
        record,
        collection="tool_calls",
        key="approval_status",
        value=approval_status,
    ) or record_has_item_value(
        record,
        collection="approvals",
        key="status",
        value=approval_status,
    )


def record_has_external_side_effect(record: Any) -> bool:
    """判断脱敏轨迹中是否存在 external effect Tool。"""
    return record_has_tool_effect(record, "external")


def record_trace_incomplete(record: Any) -> bool:
    """历史记录缺少完整性字段时不伪造 incomplete，仅匹配显式 false。"""
    if not isinstance(record, dict):
        return False
    observability = record.get("observability")
    if not isinstance(observability, dict):
        return False
    completeness = observability.get("trace_completeness")
    return isinstance(completeness, dict) and completeness.get("complete") is False


def record_has_empty_retrieval(record: Any) -> bool:
    """从脱敏 Retrieval 列表识别显式空召回案例。"""
    if not isinstance(record, dict):
        return False
    return any(
        isinstance(item, dict)
        and (item.get("empty_result") is True or item.get("result_count") == 0)
        for item in record.get("retrievals") or ()
    )


def record_has_item_value(
    record: Any,
    *,
    collection: str,
    key: str,
    value: str,
) -> bool:
    """在已脱敏结构化列表中执行精确短标量匹配。"""
    if not isinstance(record, dict):
        return False
    return any(
        isinstance(item, dict) and item.get(key) == value
        for item in record.get(collection) or ()
    )
