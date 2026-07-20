import logging
from typing import Optional
from datetime import datetime
from app.schemas.session import InterviewSession, MessageItem
from sqlalchemy import select, update
from app.infrastructure.db.models import async_session, MessageModel, SessionModel
from .base import BaseService
from .session_mgmt import SessionManagementService

logger = logging.getLogger(__name__)

class MessageService(BaseService):
    """消息管理服务：负责消息的增删及对话内容提取"""

    def __init__(self, mgmt_service: SessionManagementService):
        self.mgmt = mgmt_service

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        question_index: int = 0,
        audio_url: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Optional[InterviewSession]:
        """向会话添加消息"""
        async with async_session() as db:
            if not await self._check_session_access(session_id, user_id):
                return None
            
            timestamp = datetime.now()
            db.add(MessageModel(session_id=session_id, role=role, content=content, timestamp=timestamp, question_index=question_index, audio_url=audio_url))
            await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(updated_at=timestamp))
            await db.commit()
            
            return await self.mgmt.get_session(session_id, user_id=user_id)

    async def get_session_conversations(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> list:
        """获取并解析会话的 QA 对"""
        async with async_session() as db:
            if not await self._check_session_access(session_id, user_id):
                return []
            
            rows = (await db.execute(select(MessageModel.role, MessageModel.content).where(MessageModel.session_id == session_id).order_by(MessageModel.timestamp.asc()))).all()
            
            qa_pairs = []
            for i in range(len(rows) - 1):
                msg = rows[i]
                next_msg = rows[i + 1]
                if msg.role == "assistant" and next_msg.role == 'user':
                    question = msg.content.strip()
                    answer = next_msg.content.strip()
                    if question and answer:
                        qa_pairs.append({"question": question, "answer": answer})
            
            return qa_pairs
