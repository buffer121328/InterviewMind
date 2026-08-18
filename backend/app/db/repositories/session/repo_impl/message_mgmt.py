import logging
from typing import Optional
from datetime import datetime
from app.schemas.interview.session import InterviewSession, MessageItem
from sqlalchemy import select, update
from app.db.models import async_session, MessageModel, SessionModel
from .base import BaseService
from .session_mgmt import SessionManagementService
from app.clock import utc_now

logger = logging.getLogger(__name__)

class MessageService(BaseService):
    """消息管理服务：负责消息的增删及对话内容提取"""

    def __init__(self, mgmt_service: SessionManagementService):
        """初始化 `MessageService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            mgmt_service: mgmt 服务实例。
        """
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
        """向会话添加消息；完成或归档后拒绝继续写入。

        Args:
            session_id: 面试会话 ID。
            role: 角色标识。
            content: 文本内容。
            question_index: 题目下标。
            audio_url: 音频 URL。
            user_id: 用户 ID，所有者范围限定。
        """
        visible_session = await self.mgmt.get_session(session_id, user_id=user_id)
        if visible_session is None:
            return None
        if visible_session.metadata.status in {"completed", "archived"}:
            raise ValueError("面试已完成，不能继续提交回答")

        async with async_session() as db:
            timestamp = utc_now()
            db.add(MessageModel(session_id=session_id, role=role, content=content, timestamp=timestamp, question_index=question_index, audio_url=audio_url))
            await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(updated_at=timestamp))
            await db.commit()

            return await self.mgmt.get_session(session_id, user_id=user_id)

    async def replace_current_question(
        self,
        session_id: str,
        question_index: int,
        content: str,
        plan: list[dict],
        user_id: Optional[str] = None,
    ) -> bool:
        """原子替换当前计划题与对应 assistant 消息，失败时不留下半更新状态。"""
        visible_session = await self.mgmt.get_session(session_id, user_id=user_id)
        if visible_session is None or visible_session.metadata.status != "active":
            return False
        async with async_session() as db:
            timestamp = utc_now()
            message_result = await db.execute(
                update(MessageModel)
                .where(
                    MessageModel.session_id == session_id,
                    MessageModel.role == "assistant",
                    MessageModel.question_index == question_index,
                )
                .values(content=content, timestamp=timestamp)
            )
            if not message_result.rowcount:
                await db.rollback()
                return False
            await db.execute(
                update(SessionModel)
                .where(SessionModel.session_id == session_id)
                .values(interview_plan=plan, updated_at=timestamp)
            )
            await db.commit()
            return True

    async def get_session_conversations(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> list:
        """获取并解析会话的 QA 对

        Args:
            session_id: 面试会话 ID。
            user_id: 用户 ID，所有者范围限定。
        """
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
