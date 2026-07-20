"""
简历生成服务
管理生成的简历的存储和内存中的会话状态
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db.models import async_session
from app.infrastructure.db.models.resume import GeneratedResumeModel

logger = logging.getLogger(__name__)


# ============================================================================
# 持久化生成会话状态
# ============================================================================

@dataclass
class GenerationSession:
    session_id: str
    user_id: str
    resume_content: str
    job_description: str
    optimization_result: dict
    template_style: str = "professional"
    questions: List[str] = field(default_factory=list)
    user_answers: Dict[str, str] = field(default_factory=dict)
    review_result: Optional[dict] = None
    iteration_count: int = 0
    draft_content: str = ""
    final_markdown: str = ""
    generated_resume_id: Optional[int] = None
    agent_run_id: Optional[str] = None
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class SessionStore:
    """PostgreSQL 生成会话存储；支持重启恢复和多进程共享。"""

    def __init__(self, ttl_hours: int | None = None):
        import os

        self._ttl = timedelta(hours=ttl_hours or max(1, int(os.getenv("RESUME_GENERATION_SESSION_TTL_HOURS", "24"))))

    @staticmethod
    def _to_session(row) -> GenerationSession:
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
        from app.infrastructure.db.models.resume import ResumeGenerationSessionModel

        now = datetime.now()
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

    async def get(self, session_id: str, user_id: Optional[str] = None) -> Optional[GenerationSession]:
        from app.infrastructure.db.models.resume import ResumeGenerationSessionModel

        async with async_session() as db:
            stmt = select(ResumeGenerationSessionModel).where(ResumeGenerationSessionModel.id == session_id)
            if user_id is not None:
                stmt = stmt.where(ResumeGenerationSessionModel.user_id == user_id)
            row = await db.scalar(stmt)
            if not row:
                return None
            if datetime.now() - row.updated_at > self._ttl:
                await db.delete(row)
                await db.commit()
                return None
            return self._to_session(row)

    async def update(self, session_id: str, user_id: Optional[str] = None, **kwargs) -> Optional[GenerationSession]:
        from app.infrastructure.db.models.resume import ResumeGenerationSessionModel

        allowed = {
            "questions", "user_answers", "review_result", "iteration_count", "draft_content",
            "final_markdown", "generated_resume_id", "status",
        }
        values = {key: value for key, value in kwargs.items() if key in allowed}
        values["updated_at"] = datetime.now()
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

    async def delete(self, session_id: str, user_id: Optional[str] = None) -> bool:
        from app.infrastructure.db.models.resume import ResumeGenerationSessionModel

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
        logger.info("ResumeGenerationService 初始化")
    
    async def save_generated_resume(
        self,
        user_id: str,
        title: str,
        content: str,
        job_description: Optional[str] = None,
        optimization_result_id: Optional[int] = None,
        generation_session_id: Optional[str] = None,
        agent_run_id: Optional[str] = None,
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
                    created_at=datetime.now(),
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
    
    async def get_generated_resume(self, resume_id: int, user_id: str) -> Optional[Dict[str, Any]]:
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
    ) -> List[Dict[str, Any]]:
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
                
            except Exception as e:
                logger.error(f"删除生成的简历失败: {e}")
                return False
    
    async def update_generated_resume(
        self,
        resume_id: int,
        user_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None
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
                
            except Exception as e:
                logger.error(f"更新生成的简历失败: {e}")
                return False

    def _row_to_dict(self, row: GeneratedResumeModel) -> Dict[str, Any]:
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
