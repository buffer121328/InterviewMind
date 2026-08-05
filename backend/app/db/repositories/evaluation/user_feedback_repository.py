"""用户满意度反馈持久化与全量聚合统计。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_feedback import UserFeedbackModel
from app.clock import utc_now

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
            for aspect, count in sorted(
                frequencies.items(), key=lambda item: (-item[1], item[0])
            )[:_MAX_ASPECTS]
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
        created_at=_now(),
    )
    session.add(record)
    await session.flush()
    return record, True


async def stats(session: AsyncSession) -> dict[str, Any]:
    """全量聚合满意度统计,不含可识别个体信息。"""

    rows = await session.scalars(select(UserFeedbackModel))
    return aggregate_feedback(list(rows))
