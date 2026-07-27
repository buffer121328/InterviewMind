from typing import Optional, List, Dict, Any
import logging
from sqlalchemy import select
from app.db.models import async_session, SessionModel

logger = logging.getLogger(__name__)

class BaseService:
    """应用或基础设施协作者，负责 `BaseService` 的职责；依赖通过构造或模块边界注入，外部调用、状态持久化和安全校验不向调用方隐藏。"""

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
