from typing import Optional, List, Dict, Any
import logging
from sqlalchemy import select
from app.infrastructure.db.models import async_session, SessionModel

logger = logging.getLogger(__name__)

class BaseService:
    """基础服务类，提供通用数据库操作"""

    async def _check_session_access(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> bool:
        """检查用户是否有权访问指定会话"""
        async with async_session() as db:
            stmt = select(SessionModel.session_id).where(SessionModel.session_id == session_id)
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none() is not None
