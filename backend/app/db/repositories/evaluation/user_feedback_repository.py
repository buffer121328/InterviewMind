"""用户满意度反馈持久化与全量聚合统计。"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import utc_now
from app.db.models.evaluation import EvaluationDatasetVersionModel
from app.db.models.resume import ResumeResultModel
from app.db.models.session import SessionModel
from app.db.models.user_feedback import UserFeedbackModel
from app.security.security import redact_secret_text

_MAX_ASPECTS = 20
_MAX_ASPECT_LENGTH = 100


def _now() -> datetime:
    """返回便于测试替换的本地时间。"""

    return utc_now()


def _id(prefix: str) -> str:
    """生成带领域前缀的 UUID 标识。"""

    return f"{prefix}_{uuid.uuid4().hex}"


def _clean_aspects(aspects: Sequence[Any]) -> list[str]:
    """清洗方面标签:trim、截断到 100 字符、去空串、去重、上限 20 条,超出截断而非报错。"""

    normalized: list[str] = []
    for aspect in aspects:
        if not isinstance(aspect, str):
            continue
        text = aspect.strip()[:_MAX_ASPECT_LENGTH]
        if text:
            normalized.append(text)
    return list(dict.fromkeys(normalized))[:_MAX_ASPECTS]


def aggregate_feedback(rows: Sequence[Any]) -> dict[str, Any]:
    """对任意带 rating/satisfied_aspects/dissatisfied_aspects 属性的对象做全量聚合。

    仅统计非空星级(空星级计入 total_count 但排除在均值与分布外);频次按出现次数降序取 Top 20。
    """

    total_count = 0
    ratings: list[int] = []
    distribution = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    satisfied: dict[str, int] = {}
    dissatisfied: dict[str, int] = {}

    for row in rows:
        total_count += 1
        rating = getattr(row, "rating", None)
        if isinstance(rating, int) and 1 <= rating <= 5:
            ratings.append(rating)
            distribution[str(rating)] += 1
        for aspect in getattr(row, "satisfied_aspects", None) or []:
            satisfied[aspect] = satisfied.get(aspect, 0) + 1
        for aspect in getattr(row, "dissatisfied_aspects", None) or []:
            dissatisfied[aspect] = dissatisfied.get(aspect, 0) + 1

    rating_count = len(ratings)
    avg_rating = round(sum(ratings) / rating_count, 1) if rating_count else None

    def _top(frequencies: dict[str, int]) -> list[dict[str, str | int]]:
        """按出现次数降序(同频按方面名升序稳定)取 Top 20。"""

        return [
            {"aspect": aspect, "count": count}
            for aspect, count in sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[
                :_MAX_ASPECTS
            ]
        ]

    return {
        "total_count": total_count,
        "rating_count": rating_count,
        "avg_rating": avg_rating,
        "rating_distribution": distribution,
        "satisfied_frequencies": _top(satisfied),
        "dissatisfied_frequencies": _top(dissatisfied),
    }


async def submit(
    session: AsyncSession,
    *,
    user_id: str,
    agent_type: str,
    ref_key: str,
    rating: int | None,
    satisfied_aspects: Sequence[Any],
    dissatisfied_aspects: Sequence[Any],
    comment: str | None,
) -> tuple[UserFeedbackModel, bool]:
    """按 (user_id, agent_type, ref_key) 幂等提交;已有记录直接返回 (existing, False)。"""

    existing = await session.scalar(
        select(UserFeedbackModel).where(
            UserFeedbackModel.user_id == user_id,
            UserFeedbackModel.agent_type == agent_type,
            UserFeedbackModel.ref_key == ref_key,
        )
    )
    if existing is not None:
        return existing, False

    record = UserFeedbackModel(
        id=_id("ufb"),
        user_id=user_id,
        agent_type=agent_type,
        ref_key=ref_key,
        rating=rating,
        satisfied_aspects=_clean_aspects(satisfied_aspects),
        dissatisfied_aspects=_clean_aspects(dissatisfied_aspects),
        comment=comment,
        source_verified=True,
        review_status=(
            "pending"
            if (rating is not None and rating <= 2) or bool(_clean_aspects(dissatisfied_aspects))
            else "not_required"
        ),
        created_at=_now(),
    )
    session.add(record)
    await session.flush()
    return record, True


async def validate_feedback_source(
    session: AsyncSession, *, user_id: str, agent_type: str, ref_key: str
) -> bool:
    """验证反馈引用确实属于当前 owner，避免伪造或跨用户引用。"""

    if agent_type == "interview":
        statement = select(SessionModel.session_id).where(
            SessionModel.session_id == ref_key,
            SessionModel.user_id == user_id,
            SessionModel.status == "completed",
        )
    elif agent_type == "resume_optimize":
        try:
            result_id = int(ref_key)
        except (TypeError, ValueError):
            return False
        statement = select(ResumeResultModel.id).where(
            ResumeResultModel.id == result_id,
            ResumeResultModel.user_id == user_id,
        )
    else:
        return False
    return await session.scalar(statement) is not None


async def stats(
    session: AsyncSession,
    *,
    user_id: str,
    agent_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> dict[str, Any]:
    """按 owner、Agent 与时间范围聚合满意度统计。"""

    statement = select(UserFeedbackModel).where(UserFeedbackModel.user_id == user_id)
    if agent_type:
        statement = statement.where(UserFeedbackModel.agent_type == agent_type)
    if created_from:
        statement = statement.where(UserFeedbackModel.created_at >= created_from)
    if created_to:
        statement = statement.where(UserFeedbackModel.created_at <= created_to)
    rows = await session.scalars(statement.order_by(UserFeedbackModel.created_at.desc()))
    return aggregate_feedback(list(rows))


async def list_feedback(
    session: AsyncSession,
    *,
    user_id: str,
    agent_type: str | None = None,
    review_status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """返回 owner 隔离的反馈明细；评论在出库时统一脱敏。"""

    conditions = [UserFeedbackModel.user_id == user_id]
    if agent_type:
        conditions.append(UserFeedbackModel.agent_type == agent_type)
    if review_status:
        conditions.append(UserFeedbackModel.review_status == review_status)
    if created_from:
        conditions.append(UserFeedbackModel.created_at >= created_from)
    if created_to:
        conditions.append(UserFeedbackModel.created_at <= created_to)
    total = int(
        await session.scalar(select(func.count()).select_from(UserFeedbackModel).where(*conditions))
        or 0
    )
    rows = await session.scalars(
        select(UserFeedbackModel)
        .where(*conditions)
        .order_by(UserFeedbackModel.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return [
        {
            "id": row.id,
            "agent_type": row.agent_type,
            "ref_key": row.ref_key,
            "rating": row.rating,
            "satisfied_aspects": row.satisfied_aspects or [],
            "dissatisfied_aspects": row.dissatisfied_aspects or [],
            "comment": redact_secret_text(row.comment) if row.comment else None,
            "source_verified": bool(row.source_verified),
            "review_status": row.review_status,
            "review_note": redact_secret_text(row.review_note) if row.review_note else None,
            "candidate_dataset_id": row.candidate_dataset_id,
            "created_at": row.created_at,
        }
        for row in rows
    ], total


async def resolve_feedback(
    session: AsyncSession, *, user_id: str, feedback_id: str, reviewer_key: str, note: str
) -> UserFeedbackModel | None:
    """完成人工复核；只能操作当前 owner 的待处理反馈。"""

    row = await session.scalar(
        select(UserFeedbackModel).where(
            UserFeedbackModel.id == feedback_id,
            UserFeedbackModel.user_id == user_id,
        )
    )
    if row is None:
        return None
    if row.review_status == "pending":
        row.review_status = "resolved"
        row.reviewed_at = _now()
        row.reviewer_key = reviewer_key
        row.review_note = note
        await session.flush()
    return row


async def link_feedback_promotion(
    session: AsyncSession, *, user_id: str, feedback_id: str, dataset_id: str, capability: str
) -> UserFeedbackModel | None:
    """Link an adapter-created draft dataset to one verified negative feedback item."""

    row = await session.scalar(
        select(UserFeedbackModel).where(
            UserFeedbackModel.id == feedback_id, UserFeedbackModel.user_id == user_id
        )
    )
    if row is None:
        return None
    dataset = await session.scalar(
        select(EvaluationDatasetVersionModel).where(
            EvaluationDatasetVersionModel.id == dataset_id,
            EvaluationDatasetVersionModel.user_id == user_id,
        )
    )
    if dataset is None:
        raise ValueError("评测数据集不存在或无权访问")
    expected_capability = (
        "interview_planner" if row.agent_type == "interview" else "resume_optimizer"
    )
    source_key = hashlib.sha256(row.ref_key.encode()).hexdigest()[:16]
    expected_prefix = f"production_history:{expected_capability}:{source_key}:"
    if capability != expected_capability or not dataset.source.startswith(expected_prefix):
        raise ValueError("数据集来源与反馈业务记录不匹配")
    if not row.source_verified or row.review_status not in {"resolved", "promoted"}:
        raise ValueError("负面反馈必须先完成来源验证和人工复核")
    if row.candidate_dataset_id and row.candidate_dataset_id != dataset_id:
        raise ValueError("该反馈已经关联其他评测数据集")
    row.candidate_dataset_id = dataset_id
    row.review_status = "promoted"
    await session.flush()
    return row
