import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select, update, func
from app.models import async_session, SessionModel, MessageModel
from .base import BaseService

logger = logging.getLogger(__name__)

class InterviewPlanService(BaseService):
    """面试计划管理服务"""

    async def get_interview_plan(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """获取面试题目清单"""
        async with async_session() as db:
            plan = (await db.execute(select(SessionModel.interview_plan).where(SessionModel.session_id == session_id))).scalar_one_or_none()
            if plan:
                return plan
            return None

    async def save_interview_plan(self, session_id: str, plan: List[Dict[str, Any]]) -> bool:
        """保存面试题目清单"""
        async with async_session() as db:
            try:
                await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(interview_plan=plan, updated_at=datetime.now()))
                await db.commit()
                return True
            except Exception as e:
                logger.error(f"保存面试计划失败: {e}")
                return False

    async def update_session_question_count(self, session_id: str, count: int) -> bool:
        """更新会话的问题计数"""
        async with async_session() as db:
            try:
                await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(question_count=count, updated_at=datetime.now()))
                await db.commit()
                return True
            except Exception as e:
                logger.error(f"更新问题计数失败: {e}")
                return False

    async def get_completed_sessions_for_resume(
        self,
        user_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取可用于简历优化的已完成会话列表"""
        async with async_session() as db:
            stmt = select(
                SessionModel.session_id,
                SessionModel.title,
                SessionModel.updated_at,
                SessionModel.round_index,
                SessionModel.round_type,
                func.count(MessageModel.id).label("message_count"),
            ).outerjoin(MessageModel, MessageModel.session_id == SessionModel.session_id).where(SessionModel.status == 'completed').group_by(SessionModel.session_id)
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            rows = (await db.execute(stmt.order_by(SessionModel.updated_at.desc()).limit(limit))).all()
            sessions = []
            for row in rows:
                updated_at = row.updated_at
                sessions.append({
                    'session_id': row.session_id,
                    'title': row.title,
                    'updated_at': updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
                    'round_index': row.round_index or 1,
                    'round_type': row.round_type or 'tech_initial',
                    'message_count': row.message_count
                })
            return sessions
