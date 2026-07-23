import logging
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.schemas.session import InterviewSession
from sqlalchemy import select, update, delete, func, text
from app.db.models import async_session, SessionModel, MessageModel
from .base import BaseService
from .session_mgmt import SessionManagementService
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type

logger = logging.getLogger(__name__)

class SessionAdvancedService(BaseService):
    """高级会话服务：负责克隆、下一轮面试、回退等"""

    def __init__(self, mgmt_service: SessionManagementService):
        """初始化当前对象实例。

        Args:
            mgmt_service: mgmt 服务实例。
        """
        self.mgmt = mgmt_service

    async def create_next_round(
        self,
        parent_session_id: str,
        max_questions: int | None = None,
        round_type: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> InterviewSession:
        """从已完成的面试创建下一轮面试

        自动从父会话继承 user_id，确保多轮面试的用户隔离。
        """
        parent = await self.mgmt.get_session(parent_session_id, include_resume_content=True, user_id=user_id)

        if not parent:
            raise ValueError(f"父会话不存在: {parent_session_id}")

        if parent.metadata.status != "completed":
            raise ValueError(f"只能从已完成的面试创建下一轮（当前状态: {parent.metadata.status}）")

        new_round_index = parent.metadata.round_index + 1
        new_round_type = resolve_round_type(round_type, round_index=new_round_index)
        resolved_max_questions = resolve_max_questions(new_round_type, max_questions, round_index=new_round_index)

        series_id = parent.metadata.series_id
        if not series_id:
            series_id = str(uuid.uuid4())
            async with async_session() as db:
                await db.execute(update(SessionModel).where(SessionModel.session_id == parent_session_id).values(series_id=series_id))
                await db.commit()

        new_session_id = str(uuid.uuid4())
        jd = parent.metadata.job_description or ""
        jd_summary = jd[:15] + "..." if len(jd) > 15 else jd
        title = f"{jd_summary} - 第{new_round_index}轮"

        # 获取父会话的 user_id，确保子会话归属同一用户
        parent_user_id = None
        async with async_session() as db:
            row = (await db.execute(
                select(SessionModel.user_id).where(SessionModel.session_id == parent_session_id)
            )).scalar_one_or_none()
            parent_user_id = row

        effective_user_id = user_id or parent_user_id or "default_user"

        now = datetime.now()
        async with async_session() as db:
            db.add(SessionModel(
                session_id=new_session_id, user_id=effective_user_id, title=title, created_at=now, updated_at=now,
                mode=parent.metadata.mode, resume_filename=parent.metadata.resume_filename, resume_content=parent.metadata.resume_content,
                job_description=parent.metadata.job_description, company_info=parent.metadata.company_info,
                question_count=0, max_questions=resolved_max_questions, status='active', pinned=False,
                series_id=series_id, round_index=new_round_index, round_type=new_round_type, parent_session_id=parent_session_id
            ))
            await db.commit()

        logger.info(f"创建下一轮面试: {new_session_id} (第{new_round_index}轮, 类型: {new_round_type}, user_id={effective_user_id})")
        return await self.mgmt.get_session(new_session_id)

    async def clone_session_for_voice(
        self,
        source_session_id: str,
        user_id: Optional[str] = None,
        max_questions: Optional[int] = None
    ) -> InterviewSession:
        """克隆会话用于语音面试

        自动从源会话继承 user_id，确保用户隔离。
        """
        source = await self.mgmt.get_session(source_session_id, include_resume_content=True, user_id=user_id)
        if not source:
            raise ValueError(f"源会话不存在: {source_session_id}")

        async with async_session() as db:
            plan = (await db.execute(select(SessionModel.interview_plan).where(SessionModel.session_id == source_session_id))).scalar_one_or_none()

        new_session_id = str(uuid.uuid4())
        title = f"{source.title} (语音版)"
        now = datetime.now()

        # 获取源会话的 user_id，确保克隆会话归属同一用户
        source_user_id = None
        async with async_session() as db:
            row = (await db.execute(
                select(SessionModel.user_id).where(SessionModel.session_id == source_session_id)
            )).scalar_one_or_none()
            source_user_id = row

        effective_user_id = user_id or source_user_id or "default_user"

        async with async_session() as db:
            db.add(SessionModel(
                session_id=new_session_id, user_id=effective_user_id, title=title, created_at=now, updated_at=now, mode='voice',
                resume_filename=source.metadata.resume_filename, resume_content=source.metadata.resume_content,
                job_description=source.metadata.job_description, company_info=source.metadata.company_info,
                question_count=source.metadata.question_count, max_questions=max_questions or source.metadata.max_questions, status='active', pinned=False,
                series_id=source.metadata.series_id, round_index=source.metadata.round_index, round_type=source.metadata.round_type,
                parent_session_id=source_session_id, interview_plan=plan
            ))
            messages = (await db.execute(select(MessageModel).where(MessageModel.session_id == source_session_id).order_by(MessageModel.timestamp.asc()))).scalars().all()
            for msg in messages:
                db.add(MessageModel(session_id=new_session_id, role=msg.role, content=msg.content, timestamp=msg.timestamp, question_index=msg.question_index, audio_url=msg.audio_url))
            await db.commit()

        logger.info(f"克隆语音会话(含消息): {source_session_id} -> {new_session_id}, 共 {len(messages)} 条消息 (user_id={effective_user_id})")
        return await self.mgmt.get_session(new_session_id)

    async def rollback_session(self, session_id: str, index: int, user_id: Optional[str] = None) -> bool:
        """回退会话到指定索引"""
        async with async_session() as db:
            try:
                if not await self._check_session_access(session_id, user_id):
                    return False

                if index == 0:
                    await db.execute(delete(MessageModel).where(MessageModel.session_id == session_id))
                    await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(question_count=0, updated_at=datetime.now()))
                else:
                    target_row = (await db.execute(select(MessageModel.timestamp).where(MessageModel.session_id == session_id).order_by(MessageModel.timestamp.asc()).offset(index).limit(1))).scalar_one_or_none()

                    if not target_row:
                        return False

                    target_timestamp = target_row
                    await db.execute(delete(MessageModel).where(MessageModel.session_id == session_id, MessageModel.timestamp >= target_timestamp))
                    await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(updated_at=datetime.now()))

                    max_answered_index = (await db.execute(
                        select(func.max(MessageModel.question_index)).where(
                            MessageModel.session_id == session_id,
                            MessageModel.role == 'user'
                        )
                    )).scalar_one()
                    new_count = (max_answered_index + 1) if max_answered_index is not None else 0
                    await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(question_count=new_count))

                await self._clear_checkpoints(db, session_id)
                await db.commit()

                return True
            except Exception as e:
                logger.error(f"回退会话失败: {e}")
                return False

    async def _clear_checkpoints(self, db, session_id: str) -> None:
        """清理 LangGraph checkpoint，避免 rollback 后继续使用旧图状态。"""
        checkpoint_tables = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
        for table_name in checkpoint_tables:
            try:
                exists = (await db.execute(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": table_name},
                )).scalar_one_or_none()
                if exists:
                    await db.execute(text(f"DELETE FROM {table_name} WHERE thread_id = :thread_id"), {"thread_id": session_id})
            except Exception as e:
                # 不同环境可能使用 MemorySaver 或表结构尚未初始化，忽略即可。
                logger.debug(f"清理 checkpoint 表 {table_name} 失败或不存在: {e}")
