"""
简历生成服务
管理生成的简历的存储和内存中的会话状态
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.clock import utc_now
from app.db.models import async_session
from app.db.models.resume import GeneratedResumeModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger(__name__)


# ============================================================================
# 持久化生成会话状态
# ============================================================================

@dataclass
class GenerationSession:
    """可恢复的简历生成会话数据对象，保存用户 owner、草稿、问答、状态和关联 AgentRun；由 SessionStore 负责 TTL、事务和跨进程持久化，不在对象本身执行模型调用。"""
    session_id: str
    user_id: str
    resume_content: str
    job_description: str
    optimization_result: dict
    template_style: str = "professional"
    questions: list[str] = field(default_factory=list)
    user_answers: dict[str, str] = field(default_factory=dict)
    review_result: dict | None = None
    iteration_count: int = 0
    draft_content: str = ""
    final_markdown: str = ""
    generated_resume_id: int | None = None
    agent_run_id: str | None = None
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class SessionStore:
    """PostgreSQL 生成会话存储；支持重启恢复和多进程共享。"""

    def __init__(self, ttl_hours: int | None = None):
        """初始化 `SessionStore` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            ttl_hours: 经过类型边界校验的 `ttl_hours`；其格式和可选值由参数类型及调用流程约束。
        """
        import os

        self._ttl = timedelta(hours=ttl_hours or max(1, int(os.getenv("RESUME_GENERATION_SESSION_TTL_HOURS", "24"))))

    @staticmethod
    def _to_session(row) -> GenerationSession:
        """把数据库行或兼容对象转换为内部结构，统一缺失字段和默认值，避免持久化层差异向上层扩散。

        Args:
            row: 经过类型边界校验的 `row`；其格式和可选值由参数类型及调用流程约束。
        """
        return GenerationSession(
            session_id=row.id,
            user_id=row.user_id,
            resume_content=row.resume_content,
            job_description=row.job_description,
            optimization_result=row.optimization_result or {},
            template_style=row.template_style,
            questions=row.questions or [],
            user_answers=row.user_answers or {},
            review_result=row.review_result,
            iteration_count=row.iteration_count,
            draft_content=row.draft_content or "",
            final_markdown=row.final_markdown or "",
            generated_resume_id=row.generated_resume_id,
            agent_run_id=row.agent_run_id,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create(self, session_id: str, **kwargs) -> GenerationSession:
        """创建当前服务声明的资源或运行对象；由所属仓储/注册表负责校验重复、owner 和持久化边界。

        Args:
            session_id: 会话标识。
            **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
        """
        from app.db.models.resume import ResumeGenerationSessionModel

        now = utc_now()
        row = ResumeGenerationSessionModel(
            id=session_id,
            created_at=now,
            updated_at=now,
            questions=[],
            user_answers={},
            status="pending",
            **kwargs,
        )
        async with async_session() as db:
            await db.execute(
                delete(ResumeGenerationSessionModel).where(
                    ResumeGenerationSessionModel.updated_at < now - self._ttl
                )
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return self._to_session(row)

    async def get(self, session_id: str, user_id: str | None = None) -> GenerationSession | None:
        """读取 get，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        from app.db.models.resume import ResumeGenerationSessionModel

        async with async_session() as db:
            stmt = select(ResumeGenerationSessionModel).where(ResumeGenerationSessionModel.id == session_id)
            if user_id is not None:
                stmt = stmt.where(ResumeGenerationSessionModel.user_id == user_id)
            row = await db.scalar(stmt)
            if not row:
                return None
            if utc_now() - row.updated_at > self._ttl:
                await db.delete(row)
                await db.commit()
                return None
            return self._to_session(row)

    async def claim_continuation(
        self,
        session_id: str,
        *,
        user_id: str,
        answers: dict[str, str],
        continuation_key: str,
    ) -> GenerationSession:
        """原子接受一次完整补充答案，阻止不同答案并发启动多个生成。

        只保存 continuation digest，不把答案原文复制到运行 payload 或观测事件。
        相同 digest 的重试返回已领取 session，后续由 SessionDriver 复用或拒绝
        已存在的 AgentRun。
        """
        from app.db.models.resume import ResumeGenerationSessionModel

        async with async_session() as db:
            stmt = (
                select(ResumeGenerationSessionModel)
                .where(
                    ResumeGenerationSessionModel.id == session_id,
                    ResumeGenerationSessionModel.user_id == user_id,
                )
                .with_for_update()
            )
            row = await db.scalar(stmt)
            if not row:
                raise ValueError("会话不存在或已过期")
            if utc_now() - row.updated_at > self._ttl:
                await db.delete(row)
                await db.commit()
                raise ValueError("会话不存在或已过期")

            review_result = dict(row.review_result or {})
            existing_key = review_result.get("_continuation_key")
            if row.status == "completed" and row.generated_resume_id:
                if existing_key == continuation_key:
                    return self._to_session(row)
                raise ValueError("该会话当前不接受补充回答")

            if row.status != "awaiting_input":
                if existing_key == continuation_key:
                    return self._to_session(row)
                raise ValueError("该会话当前不接受补充回答")

            expected = set(row.questions or [])
            submitted = {
                question
                for question, answer in answers.items()
                if isinstance(answer, str) and answer.strip()
            }
            if submitted != expected or set(answers) != expected:
                raise ValueError("请完整回答服务端返回的全部补充问题")

            review_result["_continuation_key"] = continuation_key
            row.user_answers = answers
            row.review_result = review_result
            row.status = "draft_generation"
            row.updated_at = utc_now()
            await db.commit()
            await db.refresh(row)
            return self._to_session(row)

    async def bind_continuation_run(
        self,
        session_id: str,
        *,
        user_id: str,
        continuation_key: str,
        agent_run_id: str,
    ) -> GenerationSession:
        """把已创建的受治理运行原子绑定到同一 continuation。

        调用方只能绑定 `claim_continuation` 已接受的同一 digest。重复请求可
        复用相同 run id；不同 run id 或不同 continuation 一律拒绝，避免并发
        重试把 checkpoint 和最终简历关联到另一运行。
        """
        from app.db.models.resume import ResumeGenerationSessionModel

        async with async_session() as db:
            stmt = (
                select(ResumeGenerationSessionModel)
                .where(
                    ResumeGenerationSessionModel.id == session_id,
                    ResumeGenerationSessionModel.user_id == user_id,
                )
                .with_for_update()
            )
            row = await db.scalar(stmt)
            if not row:
                raise ValueError("会话不存在或已过期")
            if utc_now() - row.updated_at > self._ttl:
                await db.delete(row)
                await db.commit()
                raise ValueError("会话不存在或已过期")

            review_result = dict(row.review_result or {})
            if review_result.get("_continuation_key") != continuation_key:
                raise ValueError("该会话当前不接受补充回答")
            if row.status not in {
                "draft_generation",
                "generating",
                "saving_result",
                "completed",
            }:
                raise ValueError("该会话当前不接受补充回答")
            if row.agent_run_id and row.agent_run_id != agent_run_id:
                raise ValueError("该会话已关联另一生成任务")
            if row.agent_run_id == agent_run_id:
                return self._to_session(row)

            row.agent_run_id = agent_run_id
            row.updated_at = utc_now()
            await db.commit()
            await db.refresh(row)
            return self._to_session(row)

    async def update(self, session_id: str, user_id: str | None = None, **kwargs) -> GenerationSession | None:
        """在会话 owner 校验和事务边界内更新生成结果；仅写入允许字段，不改变已完成记录的不可变审计信息。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
            **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
        """
        from app.db.models.resume import ResumeGenerationSessionModel

        allowed = {
            "questions", "user_answers", "review_result", "iteration_count", "draft_content",
            "final_markdown", "generated_resume_id", "agent_run_id", "status",
        }
        values = {key: value for key, value in kwargs.items() if key in allowed}
        values["updated_at"] = utc_now()
        async with async_session() as db:
            stmt = select(ResumeGenerationSessionModel).where(ResumeGenerationSessionModel.id == session_id).with_for_update()
            if user_id is not None:
                stmt = stmt.where(ResumeGenerationSessionModel.user_id == user_id)
            row = await db.scalar(stmt)
            if not row:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            await db.commit()
            await db.refresh(row)
            return self._to_session(row)

    async def delete(self, session_id: str, user_id: str | None = None) -> bool:
        """在会话 owner 校验下删除生成结果，并保持资源不存在时的幂等语义。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        from app.db.models.resume import ResumeGenerationSessionModel

        async with async_session() as db:
            stmt = select(ResumeGenerationSessionModel).where(ResumeGenerationSessionModel.id == session_id).with_for_update()
            if user_id is not None:
                stmt = stmt.where(ResumeGenerationSessionModel.user_id == user_id)
            row = await db.scalar(stmt)
            if not row:
                return False
            await db.delete(row)
            await db.commit()
            return True


session_store = SessionStore()


# ============================================================================
# 数据库持久化服务
# ============================================================================

class ResumeGenerationRepo:
    """简历生成服务 - 管理生成的简历持久化"""

    def __init__(self):
        """初始化 `ResumeGenerationRepo` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        logger.info("ResumeGenerationService 初始化")

    async def save_generated_resume(
        self,
        user_id: str,
        title: str,
        content: str,
        job_description: str | None = None,
        optimization_result_id: int | None = None,
        generation_session_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> int:
        """
        保存生成的简历

        Returns:
            int: 简历 ID
        """
        async with async_session() as db:
            try:
                if generation_session_id or agent_run_id:
                    stmt = select(GeneratedResumeModel)
                    if agent_run_id:
                        stmt = stmt.where(GeneratedResumeModel.agent_run_id == agent_run_id)
                    else:
                        stmt = stmt.where(GeneratedResumeModel.generation_session_id == generation_session_id)
                    existing = await db.scalar(stmt)
                    if existing:
                        return existing.id
                db_obj = GeneratedResumeModel(
                    user_id=user_id,
                    title=title,
                    optimization_result_id=optimization_result_id,
                    job_description=job_description,
                    content=content,
                    generation_session_id=generation_session_id,
                    agent_run_id=agent_run_id,
                    created_at=utc_now(),
                )
                db.add(db_obj)
                await db.commit()
                await db.refresh(db_obj)
                resume_id = db_obj.id

                logger.info(f"保存生成的简历: ID={resume_id}, title={title}")
                return resume_id

            except IntegrityError:
                await db.rollback()
                stmt = select(GeneratedResumeModel)
                if agent_run_id:
                    stmt = stmt.where(GeneratedResumeModel.agent_run_id == agent_run_id)
                elif generation_session_id:
                    stmt = stmt.where(GeneratedResumeModel.generation_session_id == generation_session_id)
                else:
                    raise
                existing = await db.scalar(stmt)
                if existing:
                    return existing.id
                raise
            except Exception as e:
                logger.error(f"保存生成的简历失败: {e}")
                raise

    async def get_generated_resume(self, resume_id: int, user_id: str) -> dict[str, Any] | None:
        """获取单个生成的简历"""
        async with async_session() as db:
            stmt = select(GeneratedResumeModel).where(
                GeneratedResumeModel.id == resume_id,
                GeneratedResumeModel.user_id == user_id,
            )
            result = await db.execute(stmt)
            obj = result.scalar_one_or_none()

            if not obj:
                return None

            return self._row_to_dict(obj)

    async def list_generated_resumes(
        self,
        user_id: str,
        limit: int = 20
    ) -> list[dict[str, Any]]:
        """获取用户生成的简历列表"""
        async with async_session() as db:
            stmt = select(GeneratedResumeModel).where(GeneratedResumeModel.user_id == user_id).order_by(GeneratedResumeModel.created_at.desc()).limit(limit)
            result = await db.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars().all()]

    async def delete_generated_resume(self, resume_id: int, user_id: str) -> bool:
        """删除生成的简历"""
        async with async_session() as db:
            try:
                result = await db.execute(
                    delete(GeneratedResumeModel).where(
                        GeneratedResumeModel.id == resume_id,
                        GeneratedResumeModel.user_id == user_id,
                    )
                )
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"删除生成的简历: ID={resume_id}")
                return deleted

            except SQLAlchemyError as exc:
                logger.error(f"删除生成的简历失败: {exc}")
                return False

    async def update_generated_resume(
        self,
        resume_id: int,
        user_id: str,
        content: str | None = None,
        title: str | None = None
    ) -> bool:
        """更新生成的简历"""
        if not content and not title:
            return False

        async with async_session() as db:
            try:
                stmt = select(GeneratedResumeModel).where(
                    GeneratedResumeModel.id == resume_id,
                    GeneratedResumeModel.user_id == user_id,
                )
                result = await db.execute(stmt)
                obj = result.scalar_one_or_none()
                if not obj:
                    return False

                if content is not None:
                    obj.content = content
                if title is not None:
                    obj.title = title

                await db.commit()
                updated = True
                if updated:
                    logger.info(f"更新生成的简历: ID={resume_id}")
                return updated

            except SQLAlchemyError as exc:
                logger.error(f"更新生成的简历失败: {exc}")
                return False

    def _row_to_dict(self, row: GeneratedResumeModel) -> dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row.id,
            'user_id': row.user_id,
            'title': row.title,
            'optimization_result_id': row.optimization_result_id,
            'job_description': row.job_description,
            'content': row.content,
            'created_at': row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at
        }


# 全局单例
_generation_repo = None


def get_generation_repo() -> ResumeGenerationRepo:
    """获取 ResumeGenerationService 单例"""
    global _generation_repo
    if _generation_repo is None:
        _generation_repo = ResumeGenerationRepo()
    return _generation_repo
