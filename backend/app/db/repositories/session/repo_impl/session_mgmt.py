import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select, update

from app.clock import utc_now
from app.db.models import (
    ArtifactModel,
    InterviewQuestionAttemptModel,
    MessageModel,
    SessionModel,
    async_session,
)
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.domain.interview_session_titles import build_interview_session_title
from app.schemas.interview.session import (
    InterviewSession,
    MessageItem,
    SessionListItem,
    SessionMetadata,
)

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
        source_job_id: Optional[int] = None,
        job_context_snapshot: Optional[Dict[str, Any]] = None,
        max_questions: int | None = None,
        round_type: str = "tech_initial",
        user_id: str = "default_user"
    ) -> InterviewSession:
        """创建新会话

        Args:
            session_id: 面试会话 ID。
            mode: 运行模式。
            title: 标题文本。
            resume_filename: 传入的 resume_filename 值。
            resume_content: 简历正文内容。
            job_description: 目标岗位 JD。
            company_info: 公司信息。
            source_job_id: 来源岗位 ID。
            job_context_snapshot: 传入的 job_context_snapshot 值。
            max_questions: 计划题目数。
            round_type: 轮次类型。
            user_id: 用户 ID，所有者范围限定。
        """
        round_type = resolve_round_type(round_type)
        max_questions = resolve_max_questions(round_type, max_questions)
        now = utc_now()
        if title is None:
            title = build_interview_session_title(
                started_at=now,
                round_type=round_type,
                max_questions=max_questions,
                round_index=1,
            )

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
                    source_job_id=source_job_id,
                    job_context_snapshot=job_context_snapshot,
                    question_count=0,
                    max_questions=max_questions,
                    status='active',
                    round_type=round_type,
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
        """获取会话详情

        Args:
            session_id: 面试会话 ID。
            include_resume_content: 传入的 include_resume_content 值。
            user_id: 用户 ID，所有者范围限定。
        """
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
                source_job_id=row.source_job_id,
                job_context_snapshot=row.job_context_snapshot,
                question_count=row.question_count,
                max_questions=row.max_questions,
                status=row.status,
                pinned=bool(row.pinned),
                series_id=row.series_id,
                round_index=row.round_index or 1,
                round_type=row.round_type,
                report_source_version=getattr(row, "report_source_version", None),
                stable_context_version=getattr(row, "stable_context_version", None),
                stable_context_fingerprint=getattr(row, "stable_context_fingerprint", None),
                round_strategy_version=getattr(row, "round_strategy_version", None),
                turn_state_version=getattr(row, "turn_state_version", None),
                turn_state=getattr(row, "turn_state", None),
                turn_checkpoint_refs=getattr(row, "turn_checkpoint_refs", None) or [],
                parent_session_id=row.parent_session_id,
                interview_plan=row.interview_plan if row.interview_plan else [],
                company_profile=row.company_profile
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

    async def get_interview_stable_context(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the owner-scoped stable prompt snapshot for one interview session.

        The snapshot is only used to reconstruct the model prefix.  It is not
        exposed through the session-detail response and must never be copied to
        AgentRun payloads, checkpoints, logs, or model-event metadata.
        """
        async with async_session() as db:
            stmt = select(SessionModel.stable_context).where(
                SessionModel.session_id == session_id
            )
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            value = (await db.execute(stmt)).scalar_one_or_none()
            return dict(value) if isinstance(value, dict) else None

    async def commit_interview_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        user_content: str,
        assistant_content: str,
        user_question_index: int,
        assistant_question_index: int,
        question_count: int,
        turn_state: Dict[str, Any],
        expected_turn_state_version: int,
        run_id: Optional[str] = None,
        audio_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically persist one completed turn and its recoverable state.

        Replaying the same AgentRun is idempotent: a committed ``run_id`` is
        detected while the session row is locked, so retries cannot append the
        same answer or consume state/follow-up budget twice.
        """
        async with async_session() as db:
            async with db.begin():
                stmt = select(SessionModel).where(
                    SessionModel.session_id == session_id,
                    SessionModel.user_id == user_id,
                ).with_for_update()
                row = (await db.execute(stmt)).scalar_one_or_none()
                if row is None:
                    raise ValueError("会话不存在或无权访问")

                checkpoint_refs = list(row.turn_checkpoint_refs or [])
                if run_id and any(
                    isinstance(item, dict)
                    and item.get("kind") == "turn_commit"
                    and item.get("run_id") == run_id
                    for item in checkpoint_refs
                ):
                    return {"committed": False, "idempotent": True}

                persisted_state = dict(row.turn_state or {})
                persisted_version = int(persisted_state.get("state_version") or 0)
                if persisted_version != int(expected_turn_state_version):
                    raise ValueError("面试回合状态已更新，请使用最新状态重试")

                now = utc_now()
                user_message = MessageModel(
                    session_id=session_id,
                    role="user",
                    content=user_content,
                    question_index=max(0, int(user_question_index)),
                    timestamp=now,
                    audio_url=audio_url,
                )
                assistant_message = MessageModel(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    question_index=max(0, int(assistant_question_index)),
                    timestamp=now,
                )
                db.add_all([user_message, assistant_message])
                await db.flush()

                committed_state = dict(turn_state)
                turn_refs = [
                    f"message:{user_message.id}",
                    f"message:{assistant_message.id}",
                ]
                for field in (
                    "covered_dimensions",
                    "evidence_summaries",
                    "unresolved_gaps",
                    "claims_to_verify",
                ):
                    updated_items = []
                    for item in committed_state.get(field) or []:
                        if not isinstance(item, dict):
                            updated_items.append(item)
                            continue
                        updated_item = dict(item)
                        source_refs = list(updated_item.get("source_refs") or [])
                        if "pending:current_turn" in source_refs:
                            updated_item["source_refs"] = turn_refs
                        updated_items.append(updated_item)
                    committed_state[field] = updated_items
                committed_state["source_message_refs"] = turn_refs
                committed_state["source_message_version"] = (
                    int(persisted_state.get("source_message_version") or 0) + 2
                )
                if not committed_state.get("stable_prefix_fingerprint"):
                    committed_state["stable_prefix_fingerprint"] = (
                        row.stable_context_fingerprint or ""
                    )
                checkpoint_refs.append({
                    "kind": "turn_commit",
                    "run_id": run_id or "voice",
                    "state_version": committed_state.get("state_version"),
                    "stable_prefix_fingerprint": committed_state.get(
                        "stable_prefix_fingerprint", ""
                    ),
                })
                row.question_count = max(0, int(question_count))
                row.turn_state = committed_state
                row.turn_state_version = str(
                    committed_state.get("schema_version") or ""
                ) or None
                row.turn_checkpoint_refs = checkpoint_refs[-20:]
                row.updated_at = now

            return {
                "committed": True,
                "idempotent": False,
                "turn_state": committed_state,
                "question_count": row.question_count,
            }

    async def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> Optional[InterviewSession]:
        """更新会话信息

        Args:
            session_id: 面试会话 ID。
            title: 标题文本。
            status: 状态字符串。
            metadata_updates: 传入的 metadata_updates 值。
            user_id: 用户 ID，所有者范围限定。
        """
        async with async_session() as db:
            if not await self._check_session_access(session_id, user_id):
                return None
            values: Dict[str, Any] = {"updated_at": utc_now()}
            if title is not None:
                values["title"] = title

            if status is not None:
                values["status"] = status

            if metadata_updates:
                for key, value in metadata_updates.items():
                    if key in [
                        'question_count', 'max_questions', 'resume_filename', 'job_description', 'pinned',
                        'round_type', 'report_source_version', 'stable_context_version',
                        'stable_context',
                        'stable_context_fingerprint', 'round_strategy_version', 'turn_state_version',
                        'turn_state', 'turn_checkpoint_refs',
                    ]:
                        if key == 'pinned':
                            values[key] = bool(value)
                        else:
                            values[key] = value
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
        """获取会话列表

        Args:
            status: 状态字符串。
            mode: 运行模式。
            limit: 返回数量上限。
            offset: 偏移量。
            user_id: 用户 ID，所有者范围限定。
        """
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
                SessionModel.series_id,
                SessionModel.parent_session_id,
                SessionModel.company_info,
                SessionModel.max_questions,
                SessionModel.company_profile,
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
                    round_type=row.round_type or 'tech_initial',
                    series_id=row.series_id,
                    parent_session_id=row.parent_session_id,
                    company_info=row.company_info,
                    max_questions=row.max_questions or 10,
                    has_company_profile=bool(row.company_profile),
                ))

            return sessions

    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """删除会话

        Args:
            session_id: 面试会话 ID。
            user_id: 用户 ID，所有者范围限定。
        """
        async with async_session() as db:
            if not await self._check_session_access(session_id, user_id):
                return False

            try:
                session_row = await db.scalar(
                    select(SessionModel).where(
                        SessionModel.session_id == session_id,
                        SessionModel.user_id == user_id,
                    )
                )
                if session_row is None:
                    return False

                # Some session-scoped tables deliberately have no foreign key so that
                # historic imports remain compatible. Delete those rows explicitly.
                await db.execute(
                    delete(InterviewQuestionAttemptModel).where(
                        InterviewQuestionAttemptModel.session_id == session_id,
                        InterviewQuestionAttemptModel.user_id == user_id,
                    )
                )
                await db.execute(
                    delete(ArtifactModel).where(
                        ArtifactModel.user_id == user_id,
                        ArtifactModel.source_type == "interview_report",
                        ArtifactModel.source_id == session_id,
                    )
                )
                # A company profile is stored on round three. If any source round is
                # removed, invalidate that aggregate so it cannot claim three-round coverage.
                if session_row.series_id:
                    await db.execute(
                        update(SessionModel)
                        .where(
                            SessionModel.series_id == session_row.series_id,
                            SessionModel.user_id == user_id,
                            SessionModel.session_id != session_id,
                        )
                        .values(company_profile=None)
                    )
                await db.execute(update(SessionModel).where(SessionModel.parent_session_id == session_id).values(parent_session_id=None))
                await db.execute(delete(MessageModel).where(MessageModel.session_id == session_id))
                await db.execute(delete(SessionModel).where(SessionModel.session_id == session_id, SessionModel.user_id == user_id))

                try:
                    await db.exec_driver_sql('DELETE FROM checkpoints WHERE thread_id = $1', (session_id,))
                    await db.exec_driver_sql('DELETE FROM writes WHERE thread_id = $1', (session_id,))
                except Exception as exc:
                    logger.debug("清理旧会话 checkpoint 失败: %s", type(exc).__name__)
                await db.commit()

                logger.info(f"✓ 成功删除会话及所有关联数据: {session_id}")
                return True
            except Exception as e:
                logger.error(f"✗ 删除会话失败: {session_id}, 错误: {e}")
                return False

    async def get_session_count(self, status: Optional[str] = None, mode: Optional[str] = None, user_id: Optional[str] = None) -> int:
        """获取会话总数

        Args:
            status: 状态字符串。
            mode: 运行模式。
            user_id: 用户 ID，所有者范围限定。
        """
        async with async_session() as db:
            stmt = select(func.count()).select_from(SessionModel)
            if status:
                stmt = stmt.where(SessionModel.status == status)
            if mode:
                stmt = stmt.where(SessionModel.mode == mode)
            if user_id:
                stmt = stmt.where(SessionModel.user_id == user_id)
            return (await db.execute(stmt)).scalar_one()
