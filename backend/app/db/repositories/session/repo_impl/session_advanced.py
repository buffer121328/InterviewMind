import logging
import uuid
from typing import Optional

from sqlalchemy import delete, func, select, text, update

from app.clock import utc_now
from app.db.models import MessageModel, SessionModel, async_session
from app.domain.interview_rounds import (
    resolve_max_questions,
    resolve_round_type,
    validate_next_round_index,
)
from app.domain.interview_session_titles import build_interview_session_title
from app.schemas.interview.session import InterviewSession

from .base import BaseService
from .session_mgmt import SessionManagementService

logger = logging.getLogger(__name__)

class SessionAdvancedService(BaseService):
    """高级会话服务：负责克隆、下一轮面试、回退等"""

    def __init__(self, mgmt_service: SessionManagementService):
        """初始化 `SessionAdvancedService` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

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
        """从已完成的 owner 会话创建唯一的下一轮面试。

        锁定父会话后检查是否已有同轮次子会话，避免重复点击或并发请求
        让同一系列出现多个第二轮/第三轮。第四轮、未完成父会话和重复创建
        均通过 ``ValueError`` 返回稳定业务错误，且不会写入新会话。

        Args:
            parent_session_id: parent_session 的 ID。
            max_questions: 计划题目数。
            round_type: 轮次类型。
            user_id: 用户 ID，所有者范围限定。
        """
        parent = await self.mgmt.get_session(parent_session_id, include_resume_content=True, user_id=user_id)

        if not parent:
            raise ValueError(f"父会话不存在: {parent_session_id}")

        if parent.metadata.status != "completed":
            raise ValueError(f"只能从已完成的面试创建下一轮（当前状态: {parent.metadata.status}）")

        new_round_index = validate_next_round_index(parent.metadata.round_index + 1)
        new_round_type = resolve_round_type(round_type, round_index=new_round_index)
        resolved_max_questions = resolve_max_questions(new_round_type, max_questions, round_index=new_round_index)

        new_session_id = str(uuid.uuid4())
        now = utc_now()
        title = build_interview_session_title(
            started_at=now,
            round_type=new_round_type,
            max_questions=resolved_max_questions,
            round_index=new_round_index,
        )

        # 父行锁把“检查已有子轮次”和“创建子轮次”串行化，避免并发重复分叉。
        async with async_session() as db:
            parent_row = (
                await db.execute(
                    select(SessionModel.user_id, SessionModel.series_id)
                    .where(SessionModel.session_id == parent_session_id)
                    .with_for_update()
                )
            ).one_or_none()
            if parent_row is None:
                raise ValueError(f"父会话不存在: {parent_session_id}")

            parent_user_id, persisted_series_id = parent_row
            effective_user_id = user_id or parent_user_id or "default_user"
            existing_child_id = (
                await db.execute(
                    select(SessionModel.session_id)
                    .where(
                        SessionModel.parent_session_id == parent_session_id,
                        SessionModel.user_id == effective_user_id,
                        SessionModel.round_index == new_round_index,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_child_id:
                raise ValueError("该轮已创建下一轮面试，请继续已有会话")

            series_id = persisted_series_id or parent.metadata.series_id or str(uuid.uuid4())
            if persisted_series_id != series_id:
                await db.execute(
                    update(SessionModel)
                    .where(SessionModel.session_id == parent_session_id)
                    .values(series_id=series_id)
                )

            db.add(SessionModel(
                session_id=new_session_id, user_id=effective_user_id, title=title, created_at=now, updated_at=now,
                mode=parent.metadata.mode, resume_filename=parent.metadata.resume_filename, resume_content=parent.metadata.resume_content,
                job_description=parent.metadata.job_description, company_info=parent.metadata.company_info,
                source_job_id=parent.metadata.source_job_id, job_context_snapshot=parent.metadata.job_context_snapshot.model_dump() if parent.metadata.job_context_snapshot else None,
                question_count=0, max_questions=resolved_max_questions, status='active', pinned=False,
                series_id=series_id, round_index=new_round_index, round_type=new_round_type,
                report_source_version=parent.metadata.report_source_version,
                round_strategy_version=parent.metadata.round_strategy_version,
                parent_session_id=parent_session_id
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

        Args:
            source_session_id: source_session 的 ID。
            user_id: 用户 ID，所有者范围限定。
            max_questions: 计划题目数。
        """
        source = await self.mgmt.get_session(source_session_id, include_resume_content=True, user_id=user_id)
        if not source:
            raise ValueError(f"源会话不存在: {source_session_id}")

        async with async_session() as db:
            plan = (await db.execute(select(SessionModel.interview_plan).where(SessionModel.session_id == source_session_id))).scalar_one_or_none()

        new_session_id = str(uuid.uuid4())
        now = utc_now()
        title = build_interview_session_title(
            started_at=now,
            round_type=source.metadata.round_type,
            max_questions=max_questions or source.metadata.max_questions,
            round_index=source.metadata.round_index,
        )

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
                source_job_id=source.metadata.source_job_id, job_context_snapshot=source.metadata.job_context_snapshot.model_dump() if source.metadata.job_context_snapshot else None,
                question_count=source.metadata.question_count, max_questions=max_questions or source.metadata.max_questions, status='active', pinned=False,
                series_id=source.metadata.series_id, round_index=source.metadata.round_index, round_type=source.metadata.round_type,
                report_source_version=source.metadata.report_source_version,
                round_strategy_version=source.metadata.round_strategy_version,
                stable_context_version=source.metadata.stable_context_version,
                stable_context_fingerprint=source.metadata.stable_context_fingerprint,
                parent_session_id=source_session_id, interview_plan=plan
            ))
            messages = (await db.execute(select(MessageModel).where(MessageModel.session_id == source_session_id).order_by(MessageModel.timestamp.asc()))).scalars().all()
            for msg in messages:
                db.add(MessageModel(session_id=new_session_id, role=msg.role, content=msg.content, timestamp=msg.timestamp, question_index=msg.question_index, audio_url=msg.audio_url))
            await db.commit()

        logger.info(f"克隆语音会话(含消息): {source_session_id} -> {new_session_id}, 共 {len(messages)} 条消息 (user_id={effective_user_id})")
        return await self.mgmt.get_session(new_session_id)

    async def rollback_session(self, session_id: str, index: int, user_id: Optional[str] = None) -> bool:
        """回退会话到指定索引

        Args:
            session_id: 面试会话 ID。
            index: 索引位置。
            user_id: 用户 ID，所有者范围限定。
        """
        async with async_session() as db:
            try:
                if not await self._check_session_access(session_id, user_id):
                    return False

                if index == 0:
                    await db.execute(delete(MessageModel).where(MessageModel.session_id == session_id))
                    await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(question_count=0, updated_at=utc_now()))
                else:
                    target_row = (await db.execute(select(MessageModel.timestamp).where(MessageModel.session_id == session_id).order_by(MessageModel.timestamp.asc()).offset(index).limit(1))).scalar_one_or_none()

                    if not target_row:
                        return False

                    target_timestamp = target_row
                    await db.execute(delete(MessageModel).where(MessageModel.session_id == session_id, MessageModel.timestamp >= target_timestamp))
                    await db.execute(update(SessionModel).where(SessionModel.session_id == session_id).values(updated_at=utc_now()))

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
        """清理 LangGraph checkpoint，避免 rollback 后继续使用旧图状态。

        Args:
            db: 数据库会话。
            session_id: 面试会话 ID。
        """
        checkpoint_deletes = (
            ("checkpoint_writes", text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id")),
            ("checkpoint_blobs", text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id")),
            ("checkpoints", text("DELETE FROM checkpoints WHERE thread_id = :thread_id")),
        )
        for table_name, delete_stmt in checkpoint_deletes:
            try:
                exists = (await db.execute(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": table_name},
                )).scalar_one_or_none()
                if exists:
                    await db.execute(delete_stmt, {"thread_id": session_id})
            except Exception as e:
                # 不同环境可能使用 MemorySaver 或表结构尚未初始化，忽略即可。
                logger.debug(f"清理 checkpoint 表 {table_name} 失败或不存在: {e}")
