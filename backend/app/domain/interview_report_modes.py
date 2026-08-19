"""面试报告模式与来源身份契约。"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any


class InterviewReportMode(str, Enum):
    """用户可选择的面试报告生成模式。"""

    STANDARD = "standard"
    DEEP = "deep"


REPORT_MODE_COMPATIBILITY_DEFAULT = InterviewReportMode.DEEP
REPORT_MODE_UI_RECOMMENDATION = InterviewReportMode.STANDARD
LEGACY_REPORT_SOURCE_VERSION = "legacy"


def normalize_report_mode(
    value: InterviewReportMode | str | None,
    *,
    default: InterviewReportMode = REPORT_MODE_COMPATIBILITY_DEFAULT,
) -> InterviewReportMode:
    """把缺省报告模式归一化为兼容默认值，不接受未知模式。"""

    if value is None or value == "":
        return default
    if isinstance(value, InterviewReportMode):
        return value
    try:
        return InterviewReportMode(str(value))
    except ValueError as exc:
        raise ValueError(f"unsupported interview report mode: {value}") from exc


def normalize_report_source_version(value: str | None) -> str:
    """为旧任务补齐稳定的报告来源版本标识。"""

    normalized = str(value or "").strip()
    return normalized or LEGACY_REPORT_SOURCE_VERSION


def build_report_idempotency_key(session_id: str, report_mode: InterviewReportMode | str | None, source_version: str | None) -> str:
    """构造模式和来源版本隔离的幂等键，不携带任何来源正文。"""

    mode = normalize_report_mode(report_mode).value
    source = normalize_report_source_version(source_version)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return f"report:{session_id}:{mode}:{digest}"


def scope_report_idempotency_key(
    client_key: str | None,
    *,
    session_id: str,
    report_mode: InterviewReportMode | str | None,
    source_version: str | None,
) -> str:
    """在客户端幂等键后追加模式和来源身份，避免跨模式复用运行。"""

    scoped = build_report_idempotency_key(session_id, report_mode, source_version)
    return f"{client_key.strip()}:{scoped}" if client_key and client_key.strip() else scoped


def build_authoritative_report_source_version(session: Any) -> str:
    """为面试报告生成权威来源指纹；只返回哈希，不记录或暴露来源正文。"""

    metadata = getattr(session, "metadata", None)
    messages = getattr(session, "messages", None) or []
    canonical = {
        "version": "rsv1",
        "session_id": str(getattr(session, "session_id", "")),
        "resume_content": getattr(metadata, "resume_content", None),
        "job_description": getattr(metadata, "job_description", None),
        "company_info": getattr(metadata, "company_info", None),
        "interview_plan": getattr(metadata, "interview_plan", None) or [],
        "round_type": getattr(metadata, "round_type", None),
        "max_questions": getattr(metadata, "max_questions", None),
        "messages": [
            {
                "role": getattr(message, "role", None),
                "content": getattr(message, "content", None),
                "question_index": getattr(message, "question_index", None),
                "timestamp": getattr(message, "timestamp", None),
            }
            for message in messages
        ],
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"rsv1-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
