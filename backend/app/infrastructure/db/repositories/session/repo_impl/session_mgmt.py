import logging
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select, update, delete, func

from app.schemas.session import (
    InterviewSession, 
    SessionListItem, 
    SessionMetadata,
    MessageItem
)
from app.infrastructure.db.models import async_session, SessionModel, MessageModel
from .base import BaseService

logger = logging.getLogger(__name__)

class SessionManagementService(BaseService):
    """会话管理服务：负责创建、删除、获取和更新会话"""

    async def create_session(
        self,
        session_id: str,
        mode: str,
        title: Optional[str] = None,
        resume_filename: Optional[str] = None,
        resume_content: Optional[str] = None,
        job_description: Optional[str] = None,
        company_info: Optional[str] = None,
        max_questions: int = 5,
        user_id: str = "default_user"
    ) -> InterviewSession:
        """创建新会话"""
        if title is None:
            mode_text = "辅导模式" if mode == "coach" else "模拟面试"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            title = f"{mode_text} - {timestamp}"
        
        now = datetime.now()
        
        async with async_session() as db:
            try:
                db_obj = SessionModel(
                    session_id=session_id,
                    user_id=user_id,
                    title=title,
                    created_at=now,
                    updated_at=now,
                    mode=mode,
                    resume_filename=resume_filename,
                    resume_content=resume_content,
                    job_description=job_description,
                    company_info=company_info,
                    question_count=0,
                    max_questions=max_questions,
                    status='active',
                    pinned=False,
                )
                db.add(db_obj)
                await db.commit()
                
                logger.info(f"创建新会话: {session_id}")
                return await self.get_session(session_id)
                
            except Exception as e:
                if 'duplicate key' in str(e).lower():
                    logger.error(f"会话已存在: {session_id}")
                    raise ValueError(f"会话 {session_id} 已存在")
                raise

    async def get_session(
        self, 
        session_id: str, 
        include_resume_content: bool = False, 
        user_id: Optional[str] = None
    ) -> Optional[InterviewSession]:
        """获取会话详情"""
        async with async_session() as db:
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            messages_stmt = select(MessageModel).where(MessageModel.session_id == session_id).order_by(MessageModel.timestamp.asc(), MessageModel.id.asc())
            messages_result = await db.execute(messages_stmt)
            messages_rows = messages_result.scalars().all()

            messages = [
                MessageItem(
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.timestamp.isoformat() if isinstance(msg.timestamp, datetime) else msg.timestamp,
                    question_index=msg.question_index or 0,
                    audio_url=msg.audio_url
                )
                for msg in messages_rows
            ]

            resume_content = None
            if include_resume_content:
                resume_content = row.resume_content

            metadata = SessionMetadata(
                mode=row.mode,
                resume_filename=row.resume_filename,
                resume_content=resume_content,
                job_description=row.job_description,
                company_info=row.company_info if row.company_info else None,
                question_count=row.question_count,
                max_questions=row.max_questions,
                status=row.status,
                pinned=bool(row.pinned),
                series_id=row.series_id,
                round_index=row.round_index or 1,
                round_type=row.round_type,
                parent_session_id=row.parent_session_id,
                interview_plan=row.interview_plan if row.interview_plan else []
            )
            
            created_at = row.created_at
            updated_at = row.updated_at
            
            return InterviewSession(
                session_id=row.session_id,
                title=row.title,
                created_at=created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                updated_at=updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
                metadata=metadata,
                messages=messages
            )

    async def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> Optional[InterviewSession]:
        """更新会话信息"""
        async with async_session() as db:
            if not await self._check_session_access(session_id, user_id):
                return None
            values: Dict[str, Any] = {"updated_at": datetime.now()}
            if title is not None:
                values["title"] = title
            
            if status is not None:
                values["status"] = status
            
            if metadata_updates:
                for key, value in metadata_updates.items():
                    if key in ['question_count', 'max_questions', 'resume_filename', 'job_description', 'pinned']:
                        values[key] = bool(value) if key == 'pinned' else value
            if values:
                stmt = update(SessionModel).where(SessionModel.session_id == session_id).values(**values)
                await db.execute(stmt)
                await db.commit()
                logger.info(f"更新会话: {session_id}")
            
            return await self.get_session(session_id, user_id=user_id)

    async def list_sessions(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> List[SessionListItem]:
        """获取会话列表"""
        async with async_session() as db:
            stmt = select(
                SessionModel.session_id,
                SessionModel.title,
                SessionModel.created_at,
                SessionModel.updated_at,
                SessionModel.mode,
                SessionModel.status,
                SessionModel.question_count,
                SessionModel.pinned,
                SessionModel.round_index,
                SessionModel.round_type,
                func.count(MessageModel.id).label("message_count"),
            ).outerjoin(MessageModel, MessageModel.session_id == SessionModel.session_id).group_by(SessionModel.session_id)
            if status:
                stmt = stmt.where(SessionModel.status == status)
            
            if mode:
                stmt = stmt.where(SessionModel.mode == mode)
            
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            
            stmt = stmt.order_by(SessionModel.pinned.desc(), SessionModel.updated_at.desc()).limit(limit).offset(offset)
            rows = (await db.execute(stmt)).all()
            
            sessions = []
            for row in rows:
                created_at = row.created_at
                updated_at = row.updated_at
                
                sessions.append(SessionListItem(
                    session_id=row.session_id,
                    title=row.title,
                    created_at=created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                    updated_at=updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
                    mode=row.mode,
                    status=row.status,
                    message_count=row.message_count,
                    question_count=row.question_count,
                    pinned=bool(row.pinned),
                    round_index=row.round_index or 1,
                    round_type=row.round_type or 'tech_initial'
                ))
            
            return sessions

    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """删除会话"""
        async with async_session() as db:
            if not await self._check_session_access(session_id, user_id):
                return False
            
            try:
                await db.execute(update(SessionModel).where(SessionModel.parent_session_id == session_id).values(parent_session_id=None))
                await db.execute(delete(MessageModel).where(MessageModel.session_id == session_id))
                await db.execute(delete(SessionModel).where(SessionModel.session_id == session_id))
                
                try:
                    await db.exec_driver_sql('DELETE FROM checkpoints WHERE thread_id = $1', (session_id,))
                    await db.exec_driver_sql('DELETE FROM writes WHERE thread_id = $1', (session_id,))
                except:
                    pass
                await db.commit()
                
                logger.info(f"✓ 成功删除会话及所有关联数据: {session_id}")
                return True
            except Exception as e:
                logger.error(f"✗ 删除会话失败: {session_id}, 错误: {e}")
                return False

    async def get_session_count(self, status: Optional[str] = None, mode: Optional[str] = None, user_id: Optional[str] = None) -> int:
        """获取会话总数"""
        async with async_session() as db:
            stmt = select(func.count()).select_from(SessionModel)
            if status:
                stmt = stmt.where(SessionModel.status == status)
            if mode:
                stmt = stmt.where(SessionModel.mode == mode)
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            return (await db.execute(stmt)).scalar_one()
