"""历史面试问答晋升评测数据集的应用用例。"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ai.workflows.agent_runs.use_cases import AgentRunUseCaseError, agent_run_use_cases
from ai.workflows.evaluation.contracts import EvaluationUseCaseError
from ai.workflows.evaluation.interview_history import (
    build_source_snapshot,
    merge_reviewed_case,
    redact_interview_source,
    source_ineligibility_reason,
)
from app.db.models import AgentRunModel, async_session
from app.db.unit_of_work import UnitOfWork
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_EVALUATION_DRAFT
from app.schemas.evaluations import (
    EvaluationDatasetCreateRequest,
    InterviewEvaluationConfirmRequest,
    InterviewEvaluationDraftRequest,
    InterviewEvaluationRetryRequest,
)

logger = logging.getLogger(__name__)


def _safe_attempt_summary(attempt: Any) -> dict[str, Any]:
    return {
        "attempt_id": int(attempt.id),
        "sequence": int(attempt.sequence),
        "question": redact_interview_source(str(attempt.asked_question)),
        "created_at": attempt.created_at.isoformat(),
    }


class InterviewHistoryEvaluationUseCasesMixin:
    """编排来源读取、草稿 AgentRun 和人工确认事务。"""

    async def list_interview_history_sources(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """返回 completed session 和可选 attempt 摘要，不返回回答或简历/JD。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            sessions, attempts_by_session, total = (
                await self.repository.list_interview_history_sessions(
                    uow.db,
                    user_id=user_id,
                    limit=limit,
                    offset=offset,
                    session_id=session_id,
                )
            )
            items = []
            for source_session in sessions:
                attempts = attempts_by_session.get(source_session.session_id, [])
                session_reason = source_ineligibility_reason(
                    session=source_session,
                    attempt=attempts[0] if attempts else None,
                )
                eligible_attempts = [
                    attempt
                    for attempt in attempts
                    if source_ineligibility_reason(session=source_session, attempt=attempt)
                    is None
                ]
                items.append(
                    {
                        "session_id": source_session.session_id,
                        "series_id": source_session.series_id,
                        "title": source_session.title,
                        "round_index": source_session.round_index,
                        "round_type": source_session.round_type,
                        "completed_at": source_session.updated_at.isoformat(),
                        "eligible": bool(eligible_attempts),
                        "ineligibility_reason": None if eligible_attempts else session_reason,
                        "attempt_count": len(attempts),
                        "eligible_attempt_count": len(eligible_attempts),
                        "attempts": [_safe_attempt_summary(item) for item in eligible_attempts],
                    }
                )
            logger.info(
                "interview evaluation sources listed: sessions=%s eligible_attempts=%s",
                len(items),
                sum(item["eligible_attempt_count"] for item in items),
            )
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_interview_history_source(
        self, *, user_id: str, attempt_id: int, capability: str
    ) -> dict[str, Any]:
        """返回一个重新校验并脱敏的可信来源快照。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.get_interview_history_attempt(
                uow.db, user_id=user_id, attempt_id=attempt_id
            )
            if row is None:
                self._not_found("面试问答不存在或无权访问")
            source_session, attempt = row
            reason = source_ineligibility_reason(session=source_session, attempt=attempt)
            if reason:
                raise EvaluationUseCaseError(
                    f"面试问答不可用于评测：{reason}", status_code=409
                )
            return build_source_snapshot(
                session=source_session, attempt=attempt, capability=capability
            ).model_dump(mode="json")

    async def create_interview_history_draft(
        self,
        *,
        user_id: str,
        request: InterviewEvaluationDraftRequest,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """在模型执行前验证所有来源，再创建加密 payload 的 queued AgentRun。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows = await self.repository.get_interview_history_attempts(
                uow.db, user_id=user_id, attempt_ids=request.attempt_ids
            )
            if len(rows) != len(request.attempt_ids):
                self._not_found("部分面试问答不存在或无权访问")
            for attempt_id in request.attempt_ids:
                source_session, attempt = rows[attempt_id]
                reason = source_ineligibility_reason(
                    session=source_session, attempt=attempt
                )
                if reason:
                    raise EvaluationUseCaseError(
                        f"面试问答 {attempt_id} 不可用于评测：{reason}",
                        status_code=409,
                    )
        fallback_key = "interview-eval-draft:" + hashlib.sha256(
            json.dumps(
                {
                    "user_id": user_id,
                    "attempt_ids": request.attempt_ids,
                    "capability": request.capability,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        try:
            response = await agent_run_use_cases.create_queued_run(
                task_type=TASK_TYPE_INTERVIEW_EVALUATION_DRAFT,
                payload=request.model_dump(mode="json"),
                user_id=user_id,
                idempotency_key=idempotency_key or fallback_key,
            )
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, status_code=exc.status_code) from exc
        logger.info(
            "interview evaluation draft queued: selected=%s capability=%s",
            len(request.attempt_ids),
            request.capability,
        )
        return response.payload

    async def get_interview_history_draft(
        self, *, user_id: str, draft_run_id: str
    ) -> dict[str, Any]:
        """读取 owner-scoped 草稿任务及其安全结果。"""

        try:
            payload = await agent_run_use_cases.get_run(
                run_id=draft_run_id, user_id=user_id
            )
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, status_code=exc.status_code) from exc
        if payload.get("task_type") != TASK_TYPE_INTERVIEW_EVALUATION_DRAFT:
            self._not_found("整理草稿不存在或无权访问")
        return payload

    async def retry_interview_history_draft_cases(
        self,
        *,
        user_id: str,
        draft_run_id: str,
        request: InterviewEvaluationRetryRequest,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """只把父草稿中选定的失败案例提交为新的整理 AgentRun。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            run = await uow.db.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.id == draft_run_id,
                    AgentRunModel.user_id == user_id,
                    AgentRunModel.task_type == TASK_TYPE_INTERVIEW_EVALUATION_DRAFT,
                )
            )
            if run is None:
                self._not_found("整理草稿不存在或无权访问")
            if run.status != "succeeded" or not isinstance(run.result, dict):
                raise EvaluationUseCaseError("整理草稿尚未完成，不能重试案例", status_code=409)
            capability = run.result.get("capability")
            raw_cases = run.result.get("cases")
            if capability not in {"interview_turn", "interview_scoring"} or not isinstance(
                raw_cases, list
            ):
                raise EvaluationUseCaseError("整理草稿结果无效", status_code=409)
            failed_attempt_ids = {
                int(item["attempt_id"])
                for item in raw_cases
                if isinstance(item, dict)
                and item.get("attempt_id") is not None
                and item.get("validation_status") == "failed"
            }
            if not set(request.attempt_ids).issubset(failed_attempt_ids):
                raise EvaluationUseCaseError("仅可重试父草稿中校验失败的案例", status_code=409)

        payload = InterviewEvaluationDraftRequest(
            attempt_ids=request.attempt_ids,
            capability=capability,
            api_config=request.api_config,
        ).model_dump(mode="json")
        selected_ids = set(request.attempt_ids)
        payload["_case_order"] = [
            int(item["attempt_id"])
            for item in raw_cases
            if isinstance(item, dict) and item.get("attempt_id") is not None
        ]
        payload["_retained_cases"] = [
            item
            for item in raw_cases
            if isinstance(item, dict)
            and item.get("attempt_id") is not None
            and int(item["attempt_id"]) not in selected_ids
        ]
        fallback_key = (
            f"interview-eval-draft-retry:{draft_run_id}:"
            + hashlib.sha256(
                json.dumps(request.attempt_ids, sort_keys=True).encode()
            ).hexdigest()
        )
        try:
            response = await agent_run_use_cases.create_queued_run(
                task_type=TASK_TYPE_INTERVIEW_EVALUATION_DRAFT,
                payload=payload,
                user_id=user_id,
                idempotency_key=idempotency_key or fallback_key,
            )
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, status_code=exc.status_code) from exc
        logger.info(
            "interview evaluation failed cases requeued: selected=%s capability=%s",
            len(request.attempt_ids),
            capability,
        )
        return response.payload

    async def confirm_interview_history_draft(
        self,
        *,
        user_id: str,
        draft_run_id: str,
        request: InterviewEvaluationConfirmRequest,
    ) -> dict[str, Any]:
        """重验来源后在单一事务中幂等创建 draft Candidate Dataset。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            run = await uow.db.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.id == draft_run_id,
                    AgentRunModel.user_id == user_id,
                    AgentRunModel.task_type == TASK_TYPE_INTERVIEW_EVALUATION_DRAFT,
                )
            )
            if run is None:
                self._not_found("整理草稿不存在或无权访问")
            if run.status != "succeeded" or not isinstance(run.result, dict):
                raise EvaluationUseCaseError("整理草稿尚未进入人工审阅状态", status_code=409)

            existing = await self.repository.get_dataset_by_name_version(
                uow.db, user_id=user_id, name=request.name, version=request.version
            )
            expected_source = f"interview_history:{draft_run_id}"
            if existing is not None:
                if existing.source == expected_source:
                    from ai.workflows.evaluation.serializers import _dataset

                    return _dataset(existing)
                raise EvaluationUseCaseError("数据集名称和版本已存在", status_code=409)

            raw_cases = run.result.get("cases")
            if not isinstance(raw_cases, list):
                raise EvaluationUseCaseError("整理草稿结果无效", status_code=409)
            draft_by_attempt = {
                int(item["attempt_id"]): item
                for item in raw_cases
                if isinstance(item, dict) and item.get("attempt_id") is not None
            }
            included = [item for item in request.cases if item.included]
            rows = await self.repository.get_interview_history_attempts(
                uow.db,
                user_id=user_id,
                attempt_ids=[item.attempt_id for item in included],
            )
            cases = []
            for review in included:
                draft_case = draft_by_attempt.get(review.attempt_id)
                source_row = rows.get(review.attempt_id)
                if draft_case is None or source_row is None:
                    raise EvaluationUseCaseError("源问答已删除或草稿不完整", status_code=409)
                if draft_case.get("validation_status") != "valid":
                    raise EvaluationUseCaseError("包含尚未通过校验的案例", status_code=409)
                source_session, attempt = source_row
                snapshot = build_source_snapshot(
                    session=source_session,
                    attempt=attempt,
                    capability=str(run.result.get("capability") or ""),
                )
                if snapshot.source_hash != draft_case.get("source_hash"):
                    raise EvaluationUseCaseError("源问答已发生变化，请重新整理", status_code=409)
                cases.append(
                    merge_reviewed_case(
                        snapshot=snapshot, review=review, draft_run_id=draft_run_id
                    )
                )
            dataset_request = EvaluationDatasetCreateRequest(
                name=request.name,
                version=request.version,
                source=expected_source,
                cases=cases,
            )
            try:
                dataset = await self.repository.create_dataset(
                    uow.db, user_id=user_id, request=dataset_request
                )
            except IntegrityError as exc:
                raise EvaluationUseCaseError("数据集名称和版本已存在", status_code=409) from exc
            from ai.workflows.evaluation.serializers import _dataset

            logger.info(
                "interview evaluation dataset confirmed: cases=%s status=draft",
                len(cases),
            )
            return _dataset(dataset)
