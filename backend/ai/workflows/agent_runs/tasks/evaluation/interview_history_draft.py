"""可恢复的历史面试评测草稿任务。"""

from __future__ import annotations

import json
from typing import Any

from ai.llm.llm_utils import invoke_structured
from ai.runtime.execution.deadlines import TaskDeadline
from ai.workflows.agent_runs.contracts import ProgressCallback
from ai.workflows.evaluation.interview_history import (
    build_source_snapshot,
    contains_sensitive_value,
    order_drafting_model_references,
    redact_interview_source,
    source_ineligibility_reason,
)
from app.db.models import async_session
from app.db.repositories.evaluation import EvaluationRepository
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluations import (
    InterviewEvaluationDraftAnnotation,
    InterviewEvaluationDraftCase,
    InterviewEvaluationDraftRequest,
    InterviewEvaluationDraftResult,
)
from app.security.model_credentials import get_model_credential_store
from app.security.security import safe_error_message
from observability import record_model_event

_MAX_PROMPT_CHARS = 24_000
_MAX_MODEL_ATTEMPTS = 5
_TASK_TIMEOUT_SECONDS = 180


def _safe_model_metadata(config: dict[str, Any], *, fallback_index: int) -> dict[str, Any]:
    """只返回可审阅的模型身份，不包含 URL、凭据或内部 key。"""

    return {
        "model": str(config.get("model") or "unknown")[:160],
        "provider": str(config.get("provider") or config.get("integration") or "unknown")[:80],
        "channel": "fast",
        "fallback_index": fallback_index,
    }


def _draft_prompt(snapshot: Any) -> str:
    source = {
        "capability": snapshot.capability,
        "question": snapshot.question,
        "answer": snapshot.answer,
        "round_type": snapshot.input.get("round_type"),
        "round_index": snapshot.input.get("round_index"),
        "interview_plan": snapshot.input.get("interview_plan"),
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True)
    if len(encoded) > _MAX_PROMPT_CHARS:
        encoded = encoded[:_MAX_PROMPT_CHARS]
    return f"""你在整理一个人工审阅前的 Agent Evaluation case 草稿。
仅根据下面已经脱敏的 JSON 来源生成非权威评测约束；不得补造候选人事实。
只输出符合 schema 的 JSON：case_key、category、expected_facts、forbidden_claims、quality_rubric、tags、severity、explanation。
不得输出或改写 input、question、answer、resume、job_description、owner、session 或 source identity。
expected_facts 必须能从回答或问题直接支持；不确定时留空并在 explanation 说明。

SOURCE JSON:
{encoded}
"""


async def _draft_annotation(
    *,
    snapshot: Any,
    references: list[dict[str, Any]],
    user_id: str,
    deadline: TaskDeadline,
) -> tuple[InterviewEvaluationDraftAnnotation, dict[str, Any]]:
    """只在即将尝试候选时水合其模型名凭据，再经统一网关调用。"""

    store = get_model_credential_store()
    last_error: Exception | None = None
    hydrated_count = 0
    for reference in references[:_MAX_MODEL_ATTEMPTS]:
        model_name = str(reference.get("model") or "").strip()
        legacy_id = reference.get("legacy_credential_id")
        api_key = await store.get(
            user_id,
            model_name,
            legacy_id=legacy_id if isinstance(legacy_id, str) else None,
        )
        if not api_key:
            continue
        fallback_index = hydrated_count
        hydrated_count += 1
        config = {**reference, "api_key": api_key}
        try:
            annotation = await invoke_structured(
                prompt=_draft_prompt(snapshot),
                output_model=InterviewEvaluationDraftAnnotation,
                api_config={"fast": config},
                channel="fast",
                max_retries=1 if fallback_index == 0 else 0,
                temperature=0.1,
                deadline=deadline,
                call_metadata={
                    "task_type": "interview_evaluation_draft",
                    "capability": snapshot.capability,
                    "fallback_index": fallback_index,
                },
            )
            if contains_sensitive_value(annotation.model_dump(mode="json")):
                raise ValueError("model output contains sensitive data")
            return annotation, _safe_model_metadata(
                config, fallback_index=fallback_index
            )
        except Exception as exc:  # candidate fallback is intentionally bounded
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("没有可用的历史面试整理模型凭据")


async def execute_interview_evaluation_draft(
    payload: dict[str, Any], user_id: str, progress: ProgressCallback
) -> dict[str, Any]:
    """加载、脱敏、逐案例整理并返回 needs-review 草稿；不创建 Dataset。"""

    request = InterviewEvaluationDraftRequest.model_validate(
        {key: value for key, value in payload.items() if not key.startswith("_")}
    )
    retained_cases = [
        InterviewEvaluationDraftCase.model_validate(item)
        for item in payload.get("_retained_cases", [])
        if isinstance(item, dict)
    ]
    case_order = [
        int(item) for item in payload.get("_case_order", []) if isinstance(item, int)
    ]
    repository = EvaluationRepository()
    await progress("loading_sources")
    async with UnitOfWork(async_session) as uow:
        rows = await repository.get_interview_history_attempts(
            uow.db, user_id=user_id, attempt_ids=request.attempt_ids
        )
    if len(rows) != len(request.attempt_ids):
        raise LookupError("部分面试问答不存在或无权访问")

    await progress("redacting")
    snapshots: dict[int, Any] = {}
    failures: dict[int, str] = {}
    for attempt_id in request.attempt_ids:
        source_session, attempt = rows[attempt_id]
        reason = source_ineligibility_reason(session=source_session, attempt=attempt)
        if reason:
            failures[attempt_id] = reason
            continue
        try:
            snapshots[attempt_id] = build_source_snapshot(
                session=source_session,
                attempt=attempt,
                capability=request.capability,
            )
        except Exception as exc:
            failures[attempt_id] = safe_error_message(exc)

    references = order_drafting_model_references(dict(request.api_config))
    if not references:
        raise RuntimeError("没有可用的历史面试整理模型配置，请重新保存 Fast 模型设置")

    await progress("drafting")
    deadline = TaskDeadline(_TASK_TIMEOUT_SECONDS)
    draft_cases: list[InterviewEvaluationDraftCase] = []
    for attempt_id in request.attempt_ids:
        snapshot = snapshots.get(attempt_id)
        if snapshot is None:
            draft_cases.append(
                InterviewEvaluationDraftCase(
                    attempt_id=attempt_id,
                    session_id=str(rows[attempt_id][0].session_id),
                    source_hash="0" * 64,
                    question="[UNAVAILABLE]",
                    answer="[UNAVAILABLE]",
                    frozen_input={},
                    evidence_refs=[f"interview-attempt:{attempt_id}"],
                    validation_status="failed",
                    failure_reason=failures.get(attempt_id, "source_validation_failed"),
                )
            )
            continue
        try:
            annotation, model_metadata = await _draft_annotation(
                snapshot=snapshot,
                references=references,
                user_id=user_id,
                deadline=deadline,
            )
            draft_cases.append(
                InterviewEvaluationDraftCase(
                    attempt_id=snapshot.attempt_id,
                    session_id=snapshot.session_id,
                    source_hash=snapshot.source_hash,
                    question=snapshot.question,
                    answer=snapshot.answer,
                    frozen_input=snapshot.input,
                    evidence_refs=snapshot.evidence_refs,
                    validation_status="valid",
                    annotation=annotation,
                    model=model_metadata,
                )
            )
        except Exception as exc:
            draft_cases.append(
                InterviewEvaluationDraftCase(
                    attempt_id=snapshot.attempt_id,
                    session_id=snapshot.session_id,
                    source_hash=snapshot.source_hash,
                    question=snapshot.question,
                    answer=snapshot.answer,
                    frozen_input=snapshot.input,
                    evidence_refs=snapshot.evidence_refs,
                    validation_status="failed",
                    failure_reason=redact_interview_source(safe_error_message(exc)),
                )
            )

    await progress("validating")
    safe_cases = []
    for item in draft_cases:
        dumped = item.model_dump(mode="json")
        if contains_sensitive_value(dumped):
            dumped.update(
                {
                    "validation_status": "failed",
                    "annotation": None,
                    "model": {},
                    "failure_reason": "sensitive_output_rejected",
                }
            )
            dumped = redact_interview_source(dumped)
        safe_cases.append(InterviewEvaluationDraftCase.model_validate(dumped))

    if retained_cases:
        merged_by_attempt = {
            item.attempt_id: item for item in [*retained_cases, *safe_cases]
        }
        ordered_ids = case_order or list(merged_by_attempt)
        safe_cases = [
            merged_by_attempt[attempt_id]
            for attempt_id in ordered_ids
            if attempt_id in merged_by_attempt
        ]

    await progress("needs_review")
    valid_count = sum(item.validation_status == "valid" for item in safe_cases)
    result = InterviewEvaluationDraftResult(
        capability=request.capability,
        selected_count=len(safe_cases),
        valid_count=valid_count,
        failed_count=len(safe_cases) - valid_count,
        cases=safe_cases,
    )
    redaction_failure_count = sum(
        item.failure_reason == "sensitive_output_rejected" for item in safe_cases
    )
    record_model_event(
        event_type="interview_evaluation_draft.summary",
        operation="interview_history_draft",
        status="needs_review",
        item_count=result.selected_count,
        result_count=result.valid_count,
        source_breakdown={
            "valid": result.valid_count,
            "rejected": result.failed_count,
            "redaction_failed": redaction_failure_count,
        },
    )
    return result.model_dump(mode="json")
