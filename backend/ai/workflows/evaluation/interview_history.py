"""历史面试问答晋升的可信快照、脱敏和服务端合并边界。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.domain.interview_rounds import valid_round_types
from app.schemas.evaluation.evaluations import (
    EvaluationCaseCreateRequest,
    InterviewEvaluationReviewCase,
    InterviewEvaluationSourceSnapshot,
)

_MAX_TEXT_CHARS = 40_000
_REDACTED_BY_KEY = {
    "api_key": "[REDACTED_API_KEY]",
    "apikey": "[REDACTED_API_KEY]",
    "authorization": "[REDACTED_AUTHORIZATION]",
    "cookie": "[REDACTED_COOKIE]",
    "set_cookie": "[REDACTED_COOKIE]",
    "password": "[REDACTED_PASSWORD]",
    "secret": "[REDACTED_SECRET]",
    "token": "[REDACTED_TOKEN]",
    "access_token": "[REDACTED_TOKEN]",
    "refresh_token": "[REDACTED_TOKEN]",
}

_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;}]+"), r"\1[REDACTED_AUTHORIZATION]"),
    (re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\n,}]+"), r"\1[REDACTED_COOKIE]"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;}]+"), r"\1[REDACTED_API_KEY]"),
    (re.compile(r"(?i)((?:access[_-]?|refresh[_-]?)?token\s*[:=]\s*)[^\s,;}]+"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(?i)((?:client[_-]?)?secret\s*[:=]\s*)[^\s,;}]+"), r"\1[REDACTED_SECRET]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;}]+"), r"\1[REDACTED_PASSWORD]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?:/(?:Users|home|var|private|tmp)/[^\s,;}]+|[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s,;}]+)"), "[REDACTED_LOCAL_PATH]"),
)


def _redact_text(value: str) -> str:
    result = value
    for pattern, replacement in _TEXT_PATTERNS:
        result = pattern.sub(replacement, result)
    if len(result) > _MAX_TEXT_CHARS:
        result = result[:_MAX_TEXT_CHARS] + "[TRUNCATED]"
    return result


def redact_interview_source(value: Any) -> Any:
    """递归确定性脱敏历史面试输入，并使用可审阅的 typed placeholders。"""

    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = key.lower().replace("-", "_")
            placeholder = _REDACTED_BY_KEY.get(normalized_key)
            output[key] = placeholder if placeholder is not None else redact_interview_source(child)
        return output
    if isinstance(value, list):
        return [redact_interview_source(item) for item in value]
    if isinstance(value, tuple):
        return [redact_interview_source(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _canonical_source(session: Any, attempt: Any) -> dict[str, Any]:
    return {
        "session_id": str(session.session_id),
        "user_id": str(session.user_id),
        "status": str(session.status),
        "resume_content": session.resume_content,
        "job_description": session.job_description,
        "company_info": session.company_info,
        "interview_plan": session.interview_plan,
        "question_count": session.question_count,
        "max_questions": session.max_questions,
        "round_index": session.round_index,
        "round_type": session.round_type,
        "attempt": {
            "id": int(attempt.id),
            "user_id": str(attempt.user_id),
            "session_id": str(attempt.session_id),
            "turn_key": str(attempt.turn_key),
            "asked_question": attempt.asked_question,
            "user_answer": attempt.user_answer,
            "sequence": int(attempt.sequence),
            "evaluation": attempt.evaluation,
        },
    }


def source_content_hash(*, session: Any, attempt: Any) -> str:
    """对原始权威来源做稳定哈希，用于确认前检测删除或漂移。"""

    encoded = json.dumps(
        _canonical_source(session, attempt),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan_items(raw_plan: Any) -> list[dict[str, Any]]:
    if isinstance(raw_plan, dict):
        for key in ("questions", "plan", "items"):
            if isinstance(raw_plan.get(key), list):
                raw_plan = raw_plan[key]
                break
    if not isinstance(raw_plan, list):
        return []
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_plan, start=1):
        if not isinstance(raw, Mapping):
            continue
        content = str(raw.get("content") or raw.get("question") or raw.get("question_text") or "").strip()
        if not content:
            continue
        item = {str(key): deepcopy(value) for key, value in raw.items()}
        item["id"] = int(raw.get("id") or index)
        item["content"] = content
        items.append(item)
    return items


def source_ineligibility_reason(*, session: Any, attempt: Any | None) -> str | None:
    """返回稳定 eligibility reason；None 表示可用于创建可信快照。"""

    if str(getattr(session, "status", "")) != "completed":
        return "session_not_completed"
    if attempt is None:
        return "missing_persisted_attempt"
    if str(getattr(session, "user_id", "")) != str(getattr(attempt, "user_id", "")):
        return "owner_mismatch"
    if str(getattr(session, "session_id", "")) != str(getattr(attempt, "session_id", "")):
        return "session_mismatch"
    if not str(getattr(attempt, "asked_question", "") or "").strip():
        return "missing_question"
    if not str(getattr(attempt, "user_answer", "") or "").strip():
        return "missing_answer"
    if not _plan_items(getattr(session, "interview_plan", None)):
        return "missing_interview_plan"
    if not str(getattr(session, "resume_content", "") or "").strip():
        return "missing_resume_context"
    if not str(getattr(session, "job_description", "") or "").strip():
        return "missing_job_context"
    if str(getattr(session, "round_type", "")) not in valid_round_types():
        return "unsupported_round_type"
    return None


def build_source_snapshot(*, session: Any, attempt: Any, capability: str) -> InterviewEvaluationSourceSnapshot:
    """构造模型不可改写的脱敏 input，适配现有 production evaluation case。"""

    if capability not in {"interview_turn", "interview_scoring"}:
        raise ValueError("unsupported interview evaluation capability")
    reason = source_ineligibility_reason(session=session, attempt=attempt)
    if reason:
        raise ValueError(reason)

    plan = _plan_items(session.interview_plan)
    asked = str(attempt.asked_question).strip()
    question_index = next(
        (index for index, item in enumerate(plan) if str(item.get("content") or "").strip() == asked),
        max(0, min(int(attempt.sequence) - 1, len(plan) - 1)),
    )
    if str(plan[question_index].get("content") or "").strip() != asked:
        plan[question_index] = {**plan[question_index], "content": asked}

    raw_input = {
        "messages": [{"role": "user", "content": str(attempt.user_answer).strip()}],
        "resume_context": str(session.resume_content).strip(),
        "job_description": str(session.job_description).strip(),
        "company_info": str(session.company_info or "").strip(),
        "mode": "mock",
        "interview_plan": plan,
        "current_question_index": question_index,
        "max_questions": int(session.max_questions or len(plan)),
        "question_count": max(0, int(attempt.sequence) - 1),
        "question_bank_count": 0,
        "experience_questions": [],
        "follow_up_count": 0,
        "turn_phase": "feedback",
        "current_sub_question": None,
        "max_follow_ups": 2,
        "round_index": int(session.round_index or 1),
        "round_type": str(session.round_type),
        "memory_context": "",
        "memory_items": [],
        "trace": [],
    }
    redacted_input = redact_interview_source(raw_input)
    return InterviewEvaluationSourceSnapshot(
        attempt_id=int(attempt.id),
        session_id=str(session.session_id),
        capability=capability,
        question=redact_interview_source(asked),
        answer=redact_interview_source(str(attempt.user_answer).strip()),
        input=redacted_input,
        evidence_refs=[f"interview-session:{session.session_id}", f"interview-attempt:{attempt.id}"],
        source_hash=source_content_hash(session=session, attempt=attempt),
    )


def _model_name(config: Mapping[str, Any]) -> str:
    return str(config.get("model") or "").strip()


def _is_deepseek_flash(config: Mapping[str, Any]) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", _model_name(config).lower())
    return "deepseek" in normalized and "flash" in normalized


def order_drafting_model_references(
    api_config: Mapping[str, Any], *, scheduler: Any | None = None
) -> list[dict[str, Any]]:
    """按任务偏好排列 credential references，保留 Fast 后备和受治理降级通道。"""

    raw_fast_pool = api_config.get("fast_pool")
    fast_pool = [dict(item) for item in raw_fast_pool if isinstance(item, Mapping)] if isinstance(raw_fast_pool, list) else []
    preferred = [item for item in fast_pool if _is_deepseek_flash(item)]
    remaining = [item for item in fast_pool if not _is_deepseek_flash(item)]
    if scheduler is None:
        from ai.llm.llms import model_gateway

        scheduler = model_gateway.scheduler
    ordered = [
        *scheduler.order("interview_evaluation_draft:deepseek_flash", preferred),
        *scheduler.order("fast_pool", remaining),
    ]
    for channel in ("fast", "general", "smart"):
        item = api_config.get(channel)
        if isinstance(item, Mapping):
            ordered.append(dict(item))
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in ordered:
        model = _model_name(item)
        base_url = str(item.get("base_url") or "").strip()
        if not model or not base_url:
            continue
        identity = (model.lower(), base_url.rstrip("/").lower())
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def contains_sensitive_value(value: Any) -> bool:
    """判断模型输出或待持久化对象是否仍包含未脱敏敏感内容。"""

    return redact_interview_source(value) != value


def merge_reviewed_case(*, snapshot: InterviewEvaluationSourceSnapshot, review: InterviewEvaluationReviewCase, draft_run_id: str) -> EvaluationCaseCreateRequest:
    """只合并允许的人工字段；权威 input、source 和 evidence 始终来自服务端。"""

    if not review.included or not review.reviewed or review.annotation is None:
        raise ValueError("case is not reviewed for inclusion")
    annotation = review.annotation
    case = EvaluationCaseCreateRequest(
        case_key=annotation.case_key,
        category=annotation.category,
        input=deepcopy(snapshot.input),
        expected_facts=annotation.expected_facts,
        forbidden_claims=annotation.forbidden_claims,
        quality_rubric=annotation.quality_rubric,
        evidence_refs=[*snapshot.evidence_refs, f"agent-run:{draft_run_id}"],
        tags=list(dict.fromkeys([*annotation.tags, "candidate", "interview-history", "human-reviewed"])),
        severity=annotation.severity,
    )
    if contains_sensitive_value(case.model_dump(mode="json")):
        raise ValueError("reviewed case contains sensitive data")
    return case
