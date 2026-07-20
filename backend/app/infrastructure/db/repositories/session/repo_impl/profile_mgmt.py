import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import select, update, exists
from app.infrastructure.db.models import async_session, SessionModel, UserProfileModel
from .base import BaseService

logger = logging.getLogger(__name__)

class ProfileService(BaseService):
    """画像管理服务：负责单个面试画像和用户综合画像"""

    async def save_profile(self, session_id: str, profile_data: Dict[str, Any]) -> bool:
        """保存候选人画像到会话"""
        async with async_session() as db:
            try:
                await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(candidate_profile=profile_data, updated_at=datetime.now()))
                await db.commit()
                return True
            except Exception as e:
                logger.error(f"保存画像失败: {e}")
                return False

    async def get_profile(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取单个会话的候选人画像"""
        async with async_session() as db:
            row = (await db.execute(select(SessionModel.candidate_profile).where(SessionModel.session_id == session_id))).scalar_one_or_none()
            if row:
                return row
            return None

    async def get_recent_profiles(self, limit: int = 5, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取最近的画像列表"""
        async with async_session() as db:
            stmt = select(SessionModel.candidate_profile).where(SessionModel.candidate_profile.is_not(None))
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            rows = (await db.execute(stmt.order_by(SessionModel.updated_at.desc()).limit(limit))).scalars().all()
            return [r for r in rows if r]

    async def get_series_final_profiles(self, limit: int = 5, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取路径终点（叶子节点）的画像"""
        async with async_session() as db:
            child_exists = exists().where(SessionModel.parent_session_id == SessionModel.session_id)
            stmt = select(SessionModel.candidate_profile).where(SessionModel.candidate_profile.is_not(None)).where(~child_exists)
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            rows = (await db.execute(stmt.order_by(SessionModel.updated_at.desc()).limit(limit))).scalars().all()
            return [r for r in rows if r]

    async def save_user_profile(self, profile_data: Dict[str, Any], user_id: str = "default_user") -> bool:
        """保存用户综合能力画像"""
        async with async_session() as db:
            try:
                now = datetime.now()
                stmt = update(UserProfileModel).where(UserProfileModel.user_id == user_id).values(profile_data=profile_data, updated_at=now)
                result = await db.execute(stmt)
                if result.rowcount == 0:
                    db.add(UserProfileModel(user_id=user_id, profile_data=profile_data, created_at=now, updated_at=now))
                await db.commit()
                return True
            except Exception as e:
                logger.error(f"保存用户综合能力画像失败: {e}")
                return False

    async def get_user_profile(self, user_id: str = "default_user") -> Optional[Dict[str, Any]]:
        """获取用户综合能力画像"""
        async with async_session() as db:
            row = (await db.execute(select(UserProfileModel.profile_data, UserProfileModel.updated_at).where(UserProfileModel.user_id == user_id))).first()
            if row and row.profile_data:
                return {"profile": row.profile_data, "updated_at": row.updated_at.isoformat()}
            return None
