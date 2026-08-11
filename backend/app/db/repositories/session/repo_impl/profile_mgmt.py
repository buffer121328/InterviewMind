import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy import select, update

from app.db.models import async_session, SessionModel, UserProfileModel
from .base import BaseService
from app.clock import utc_now

logger = logging.getLogger(__name__)


def build_recent_company_profiles_stmt(*, limit: int, user_id: str):
    """构建最近公司画像相关后端逻辑。"""
    return (
        select(SessionModel.company_profile)
        .where(
            SessionModel.user_id == user_id,
            SessionModel.round_index == 3,
            SessionModel.status == "completed",
            SessionModel.company_profile.is_not(None),
        )
        .order_by(SessionModel.updated_at.desc())
        .limit(limit)
    )


def build_recent_company_profile_records_stmt(*, limit: int, user_id: str):
    """构建最近公司画像记录相关后端逻辑。"""
    return (
        select(
            SessionModel.session_id,
            SessionModel.series_id,
            SessionModel.title,
            SessionModel.company_info,
            SessionModel.company_profile,
            SessionModel.updated_at,
        )
        .where(
            SessionModel.user_id == user_id,
            SessionModel.round_index == 3,
            SessionModel.status == "completed",
            SessionModel.company_profile.is_not(None),
        )
        .order_by(SessionModel.updated_at.desc())
        .limit(limit)
    )


class ProfileService(BaseService):
    """画像管理服务：负责单轮、公司和用户综合画像。"""

    async def save_profile(self, session_id: str, profile_data: Dict[str, Any], user_id: str) -> bool:
        """按 owner 保存单轮画像；资源不可见或写入失败时返回 ``False``。"""
        async with async_session() as db:
            try:
                result = await db.execute(
                    update(SessionModel)
                    .where(SessionModel.session_id == session_id, SessionModel.user_id == user_id)
                    .values(candidate_profile=profile_data, updated_at=utc_now())
                )
                await db.commit()
                return bool(result.rowcount)
            except Exception as exc:
                logger.error("保存画像失败: %s", type(exc).__name__)
                return False

    async def get_profile(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """按 owner 读取指定会话的单轮画像，避免跨用户泄露。"""
        async with async_session() as db:
            row = (
                await db.execute(
                    select(SessionModel.candidate_profile).where(
                        SessionModel.session_id == session_id,
                        SessionModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            return row or None

    async def get_series_round_profiles(self, series_id: str, user_id: str) -> List[Dict[str, Any]]:
        """获取序列轮次画像相关后端逻辑。"""
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(
                        SessionModel.session_id,
                        SessionModel.round_index,
                        SessionModel.status,
                        SessionModel.candidate_profile,
                        SessionModel.company_info,
                        SessionModel.job_description,
                    )
                    .where(SessionModel.series_id == series_id, SessionModel.user_id == user_id)
                    .order_by(SessionModel.round_index.asc())
                )
            ).all()
            return [
                {
                    "session_id": row.session_id,
                    "round_index": row.round_index or 1,
                    "status": row.status,
                    "profile": row.candidate_profile,
                    "company_info": row.company_info,
                    "job_description": row.job_description,
                }
                for row in rows
            ]

    async def save_company_profile(self, session_id: str, profile_data: Dict[str, Any], user_id: str) -> bool:
        """保存公司画像相关后端逻辑。"""
        async with async_session() as db:
            result = await db.execute(
                update(SessionModel)
                .where(
                    SessionModel.session_id == session_id,
                    SessionModel.user_id == user_id,
                    SessionModel.round_index == 3,
                    SessionModel.status == "completed",
                )
                .values(company_profile=profile_data, updated_at=utc_now())
            )
            await db.commit()
            return bool(result.rowcount)

    async def get_company_profile(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """按 owner 读取第三轮上持久化的公司总画像载荷。"""
        async with async_session() as db:
            row = (
                await db.execute(
                    select(SessionModel.company_profile).where(
                        SessionModel.session_id == session_id,
                        SessionModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            return row or None

    async def get_series_final_profiles(self, limit: int, user_id: str) -> List[Dict[str, Any]]:
        """获取序列最终画像相关后端逻辑。"""
        async with async_session() as db:
            rows = (await db.execute(build_recent_company_profiles_stmt(limit=limit, user_id=user_id))).scalars().all()
            profiles: List[Dict[str, Any]] = []
            for payload in rows:
                if not isinstance(payload, dict):
                    continue
                profile = payload.get("profile")
                if isinstance(profile, dict):
                    profiles.append(profile)
            return profiles

    async def get_series_final_profile_records(self, limit: int, user_id: str) -> List[Dict[str, Any]]:
        """获取序列最终画像记录相关后端逻辑。"""
        async with async_session() as db:
            rows = (await db.execute(
                build_recent_company_profile_records_stmt(limit=limit, user_id=user_id)
            )).all()
            return [
                {
                    "session_id": row.session_id,
                    "series_id": row.series_id,
                    "title": row.title,
                    "company_info": row.company_info,
                    "company_profile": row.company_profile,
                    "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
                }
                for row in rows
            ]

    async def save_user_profile(self, profile_data: Dict[str, Any], user_id: str) -> bool:
        """按用户幂等写入跨公司的综合能力画像。"""
        async with async_session() as db:
            try:
                now = utc_now()
                result = await db.execute(
                    update(UserProfileModel)
                    .where(UserProfileModel.user_id == user_id)
                    .values(profile_data=profile_data, updated_at=now)
                )
                if result.rowcount == 0:
                    db.add(UserProfileModel(user_id=user_id, profile_data=profile_data, created_at=now, updated_at=now))
                await db.commit()
                return True
            except Exception as exc:
                logger.error("保存用户综合能力画像失败: %s", type(exc).__name__)
                return False

    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """读取当前用户的综合能力画像及其更新时间。"""
        async with async_session() as db:
            row = (
                await db.execute(
                    select(UserProfileModel.profile_data, UserProfileModel.updated_at).where(
                        UserProfileModel.user_id == user_id
                    )
                )
            ).first()
            if row and row.profile_data:
                return {"profile": row.profile_data, "updated_at": row.updated_at.isoformat()}
            return None
