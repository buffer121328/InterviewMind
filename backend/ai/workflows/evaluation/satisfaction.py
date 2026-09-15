"""用户满意度反馈用例:幂等提交与全量聚合统计。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.evaluation.production_history import (
    _load_source,
    production_history_source_marker,
)
from ai.workflows.evaluation.satisfaction_journal import append_satisfaction_daily_log
from ai.workflows.evaluation.serializers import _dataset
from app.db.models.user_feedback import UserFeedbackModel
from app.db.repositories.evaluation import EvaluationRepository
from app.db.repositories.evaluation.user_feedback_repository import (
    link_feedback_promotion,
    list_feedback,
    resolve_feedback,
    stats,
    submit,
    validate_feedback_source,
)
from app.schemas.evaluation.evaluations import (
    EvaluationCaseCreateRequest,
    EvaluationDatasetCreateRequest,
    ProductionHistoryConfirmRequest,
)
from app.schemas.evaluation.satisfaction_schemas import (
    SatisfactionFeedbackItem,
    SatisfactionFeedbackListResponse,
    SatisfactionStatsResponse,
    SatisfactionSubmitResponse,
)
from app.security.security import redact_secret_text


class SatisfactionUseCases:
    """满意度提交与统计应用服务,经会话依赖透传持久化。"""

    async def submit(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent_type: str,
        ref_key: str,
        rating: int | None,
        satisfied_aspects: list[str],
        dissatisfied_aspects: list[str],
        comment: str | None,
    ) -> SatisfactionSubmitResponse:
        """幂等提交反馈;created=False 表示该用户该任务实例已有记录。

        Args:
            session: 当前数据库会话。
            user_id: 当前用户标识。
            agent_type: Agent 类型。
            ref_key: 任务实例引用键。
            rating: 评分（可空）。
            satisfied_aspects: 满意的方面列表。
            dissatisfied_aspects: 不满意的方面列表。
            comment: 文字反馈（可空）。
        """

        if not await validate_feedback_source(
            session, user_id=user_id, agent_type=agent_type, ref_key=ref_key
        ):
            raise LookupError("未找到可反馈的业务记录")
        record, created = await submit(
            session,
            user_id=user_id,
            agent_type=agent_type,
            ref_key=ref_key,
            rating=rating,
            satisfied_aspects=satisfied_aspects,
            dissatisfied_aspects=dissatisfied_aspects,
            comment=comment,
        )
        if created:
            await session.commit()
            await append_satisfaction_daily_log(record)
        return SatisfactionSubmitResponse(id=record.id, created=created)

    async def stats(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent_type: str | None = None,
        created_from=None,
        created_to=None,
    ) -> SatisfactionStatsResponse:
        """返回满意度全量聚合统计,不含可识别个体信息。

        Args:
            session: 当前数据库会话。
        """

        return SatisfactionStatsResponse(
            **(
                await stats(
                    session,
                    user_id=user_id,
                    agent_type=agent_type,
                    created_from=created_from,
                    created_to=created_to,
                )
            )
        )

    async def list(self, session: AsyncSession, **filters) -> SatisfactionFeedbackListResponse:
        items, total = await list_feedback(session, **filters)
        return SatisfactionFeedbackListResponse(
            items=[SatisfactionFeedbackItem(**item) for item in items],
            total=total,
            page=filters.get("page", 1),
            limit=filters.get("limit", 20),
        )

    async def resolve(
        self, session: AsyncSession, *, user_id: str, feedback_id: str, note: str
    ) -> SatisfactionFeedbackItem:
        row = await resolve_feedback(
            session, user_id=user_id, feedback_id=feedback_id, reviewer_key=user_id, note=note
        )
        if row is None:
            raise LookupError("未找到反馈记录")
        await session.commit()
        return SatisfactionFeedbackItem(
            id=row.id,
            agent_type=row.agent_type,
            ref_key=row.ref_key,
            rating=row.rating,
            satisfied_aspects=row.satisfied_aspects or [],
            dissatisfied_aspects=row.dissatisfied_aspects or [],
            comment=redact_secret_text(row.comment) if row.comment else None,
            source_verified=bool(row.source_verified),
            review_status=row.review_status,
            review_note=redact_secret_text(row.review_note) if row.review_note else None,
            candidate_dataset_id=row.candidate_dataset_id,
            created_at=row.created_at,
        )

    async def link_promotion(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        feedback_id: str,
        dataset_id: str,
        capability: str,
    ) -> SatisfactionFeedbackItem:
        try:
            row = await link_feedback_promotion(
                session,
                user_id=user_id,
                feedback_id=feedback_id,
                dataset_id=dataset_id,
                capability=capability,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if row is None:
            raise LookupError("未找到反馈记录")
        await session.commit()
        return SatisfactionFeedbackItem(
            id=row.id,
            agent_type=row.agent_type,
            ref_key=row.ref_key,
            rating=row.rating,
            satisfied_aspects=row.satisfied_aspects or [],
            dissatisfied_aspects=row.dissatisfied_aspects or [],
            comment=redact_secret_text(row.comment) if row.comment else None,
            source_verified=bool(row.source_verified),
            review_status=row.review_status,
            review_note=redact_secret_text(row.review_note) if row.review_note else None,
            candidate_dataset_id=row.candidate_dataset_id,
            created_at=row.created_at,
        )

    async def promote(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        feedback_id: str,
        capability: str,
        confirmation: ProductionHistoryConfirmRequest,
    ) -> dict:
        """Atomically create the governed dataset and link one reviewed negative feedback."""

        try:
            row = await session.scalar(
                select(UserFeedbackModel).where(
                    UserFeedbackModel.id == feedback_id, UserFeedbackModel.user_id == user_id
                )
            )
            if row is None:
                raise LookupError("未找到反馈记录")
            expected_capability = (
                "interview_planner" if row.agent_type == "interview" else "resume_optimizer"
            )
            if (
                capability != expected_capability
                or not row.source_verified
                or row.review_status not in {"resolved", "promoted"}
            ):
                raise RuntimeError("反馈必须先完成来源验证和人工复核")
            source = await _load_source(
                session, user_id=user_id, capability=capability, source_id=row.ref_key
            )
            if source is None:
                raise LookupError("业务记录不存在、上下文不完整或无权访问")
            if not confirmation.reviewed or source["source_hash"] != confirmation.source_hash:
                raise RuntimeError("来源记录已变化，请重新预览并完成人工确认")
            repository = EvaluationRepository()
            marker = production_history_source_marker(
                capability, row.ref_key, confirmation.source_hash
            )
            existing = await repository.get_dataset_by_name_version(
                session, user_id=user_id, name=confirmation.name, version=confirmation.version
            )
            if existing is None:
                case = EvaluationCaseCreateRequest(
                    case_key=f"{capability}-{row.ref_key}",
                    category=capability,
                    input=source["input"],
                    expected_output=confirmation.expected_output,
                    expected_facts=confirmation.expected_facts,
                    forbidden_claims=confirmation.forbidden_claims,
                    expected_tool_calls=confirmation.expected_tool_calls,
                    allowed_tool_calls=confirmation.allowed_tool_calls,
                    quality_rubric=confirmation.quality_rubric,
                    evidence_refs=[f"production_history:{capability}:{row.ref_key}"],
                    tags=list(
                        dict.fromkeys(
                            [
                                "production-history",
                                "negative-feedback",
                                capability,
                                *confirmation.tags,
                            ]
                        )
                    ),
                    severity=confirmation.severity,
                    latency_budget_ms=confirmation.latency_budget_ms,
                    token_budget=confirmation.token_budget,
                )
                existing = await repository.create_dataset(
                    session,
                    user_id=user_id,
                    request=EvaluationDatasetCreateRequest(
                        name=confirmation.name,
                        version=confirmation.version,
                        source=marker,
                        cases=[case],
                    ),
                )
            elif existing.source != marker:
                raise RuntimeError("数据集名称和版本已存在")
            if row.candidate_dataset_id and row.candidate_dataset_id != existing.id:
                raise RuntimeError("该反馈已经关联其他评测数据集")
            row.candidate_dataset_id = existing.id
            row.review_status = "promoted"
            await session.flush()
            await session.commit()
            return _dataset(existing)
        except Exception:
            await session.rollback()
            raise


satisfaction_use_cases = SatisfactionUseCases()
