"""Evaluation repository 共享的纯辅助函数。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.security.security import redact_secret_text
from app.clock import utc_now


def _now() -> datetime:
    """返回便于测试替换的本地时间。"""

    return utc_now()


def _safe_candidate_label(value: Any) -> str | None:
    """把结构化观测值收敛为安全 tag 片段，拒绝正文和自由文本。"""

    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value
    ):
        return None
    return value


def _safe_evidence_refs(values: Sequence[Any]) -> list[str]:
    """仅保留稳定引用格式，避免历史脏数据被复制进 Candidate Dataset。"""

    refs: list[str] = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,255}", value
        ):
            continue
        if "cookie" in value.lower() or redact_secret_text(value) != value:
            continue
        refs.append(value)
    return list(dict.fromkeys(refs))


def _candidate_governance_metadata(
    *,
    record: Mapping[str, Any],
    error_category: str | None,
    scores: Sequence[Any],
) -> tuple[list[str], list[str]]:
    """从脱敏运行记录和评分派生 Candidate Dataset 的治理 tags 与证据引用。"""

    tags: set[str] = set()
    evidence_refs: list[Any] = []
    tool_calls = record.get("tool_calls")
    if isinstance(tool_calls, list):
        for item in tool_calls:
            if not isinstance(item, Mapping):
                continue
            tool_name = _safe_candidate_label(item.get("tool_name"))
            if tool_name:
                tags.add(f"tool:{tool_name}")
            if item.get("effect") == "external":
                tags.add("effect:external")
            tool_error = _safe_candidate_label(item.get("error_category"))
            if tool_error:
                tags.add(f"error:{tool_error}")
            item_refs = item.get("evidence_refs")
            if isinstance(item_refs, (list, tuple)):
                evidence_refs.extend(item_refs)

    approvals = record.get("approvals")
    if isinstance(approvals, list):
        for item in approvals:
            if not isinstance(item, Mapping):
                continue
            status = _safe_candidate_label(item.get("status"))
            if status:
                tags.add(f"approval:{status}")
            item_refs = item.get("evidence_refs")
            if isinstance(item_refs, (list, tuple)):
                evidence_refs.extend(item_refs)

    retrievals = record.get("retrievals")
    if isinstance(retrievals, list) and retrievals:
        tags.add("retrieval:observed")
        if any(
            isinstance(item, Mapping)
            and (item.get("empty_result") is True or item.get("result_count") == 0)
            for item in retrievals
        ):
            tags.add("retrieval:empty")

    observability = record.get("observability")
    if isinstance(observability, Mapping):
        completeness = observability.get("trace_completeness")
        if isinstance(completeness, Mapping) and completeness.get("complete") is False:
            tags.add("trace:incomplete")

    primary_error = _safe_candidate_label(error_category)
    if primary_error:
        tags.add(f"error:{primary_error}")
    for score in scores:
        status = str(getattr(score, "status", ""))
        hard_gate = bool(getattr(score, "hard_gate", False))
        metric_name = _safe_candidate_label(getattr(score, "metric_name", None))
        if hard_gate and status != "passed" and metric_name:
            tags.add(f"gate:{metric_name}")
        if status != "passed":
            score_refs = getattr(score, "evidence_refs", None)
            if isinstance(score_refs, (list, tuple)):
                evidence_refs.extend(score_refs)
    return sorted(tags), _safe_evidence_refs(evidence_refs)


def _merge_candidate_tags(
    request_tags: Sequence[str],
    governance_tags: Sequence[str],
) -> list[str]:
    """优先保留闭环治理 tags，再在 40 个标签上限内合并调用方标签。"""

    ordered = ["candidate", "regression", *governance_tags, *request_tags]
    return list(dict.fromkeys(ordered))[:40]


def _id(prefix: str) -> str:
    """生成带领域前缀的 UUID 标识。"""

    return f"{prefix}_{uuid.uuid4().hex}"


def _hash(value: Any) -> str:
    """对规范化 JSON 计算稳定 SHA-256。"""

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
