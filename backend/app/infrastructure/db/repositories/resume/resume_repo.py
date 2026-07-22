"""
简历工具持久化服务
负责简历优化/分析结果的存储和管理
"""

import logging
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import async_session
from app.infrastructure.db.models.resume import ResumeResultModel

logger = logging.getLogger(__name__)


class ResumeRepo:
    """简历工具服务类 - 管理简历优化/分析结果"""

    def __init__(self):
        """初始化简历服务"""
        logger.info("ResumeRepo 初始化")

    async def save_result(
        self,
        user_id: str,
        result_type: str,
        resume_content: str,
        result_data: dict,
        job_description: Optional[str] = None,
        session_ids: Optional[List[str]] = None,
        include_profile: bool = False,
        agent_run_id: Optional[str] = None,
        session: AsyncSession | None = None,
    ) -> int:
        """
        保存优化/分析结果

        Args:
            user_id: 用户ID
            result_type: 结果类型 ('optimize' 或 'analyze')
            resume_content: 简历内容
            result_data: 结果数据
            job_description: 职位描述（可选）
            session_ids: 关联的面试 session_id 列表
            include_profile: 是否包含综合画像

        Returns:
            int: 结果 ID
        """
        owns_session = session is None
        db = session
        try:
            if owns_session:
                async with async_session() as owned_db:
                    return await self._save_result_with_session(
                        owned_db,
                        user_id=user_id,
                        result_type=result_type,
                        resume_content=resume_content,
                        result_data=result_data,
                        job_description=job_description,
                        session_ids=session_ids,
                        include_profile=include_profile,
                        agent_run_id=agent_run_id,
                        owns_session=True,
                    )
            assert db is not None
            return await self._save_result_with_session(
                db,
                user_id=user_id,
                result_type=result_type,
                resume_content=resume_content,
                result_data=result_data,
                job_description=job_description,
                session_ids=session_ids,
                include_profile=include_profile,
                agent_run_id=agent_run_id,
                owns_session=False,
            )
        except Exception as e:
            logger.error(f"保存简历结果失败: {e}")
            raise

    async def _save_result_with_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        result_type: str,
        resume_content: str,
        result_data: dict,
        job_description: Optional[str] = None,
        session_ids: Optional[List[str]] = None,
        include_profile: bool = False,
        agent_run_id: Optional[str] = None,
        owns_session: bool,
    ) -> int:
        """保存 `result with session`。

        Args:
            db: 数据库会话。
            user_id: 当前用户标识。
            result_type: 调用方传入的 `result_type` 参数。
            resume_content: 调用方传入的 `resume_content` 参数。
            result_data: result 数据。
            job_description: 调用方传入的 `job_description` 参数。
            session_ids: session 标识列表。
            include_profile: 调用方传入的 `include_profile` 参数。
            agent_run_id: Agent 运行标识。
            owns_session: 调用方传入的 `owns_session` 参数。
        """
        if agent_run_id:
            existing = await db.scalar(
                select(ResumeResultModel).where(ResumeResultModel.agent_run_id == agent_run_id)
            )
            if existing:
                return existing.id
        db_obj = ResumeResultModel(
            user_id=user_id,
            result_type=result_type,
            resume_content=resume_content,
            job_description=job_description,
            session_ids=session_ids or None,
            include_profile=include_profile,
            result_data=result_data,
            agent_run_id=agent_run_id,
            created_at=datetime.now(),
        )
        db.add(db_obj)
        await db.flush()
        result_id = db_obj.id
        if owns_session:
            await db.commit()
            await db.refresh(db_obj)
            result_id = db_obj.id
        logger.info(f"保存简历{result_type}结果: ID={result_id}, user={user_id}")
        return result_id

    async def get_result_by_agent_run_id(self, agent_run_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """获取 `result by agent run id`。

        Args:
            agent_run_id: Agent 运行标识。
            user_id: 当前用户标识。
        """
        async with async_session() as db:
            row = await db.scalar(
                select(ResumeResultModel).where(
                    ResumeResultModel.agent_run_id == agent_run_id,
                    ResumeResultModel.user_id == user_id,
                )
            )
            return self._row_to_dict(row) if row else None

    async def get_result(self, result_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个结果

        Args:
            result_id: 结果ID
            user_id: 用户ID（用于权限校验）

        Returns:
            结果数据字典，如果不存在或无权限则返回 None
        """
        async with async_session() as db:
            stmt = select(ResumeResultModel).where(
                ResumeResultModel.id == result_id,
                ResumeResultModel.user_id == user_id,
            )
            row = await db.execute(stmt)
            obj = row.scalar_one_or_none()

            if not obj:
                return None

            return self._row_to_dict(obj)

    async def update_result_data(
        self,
        result_id: int,
        user_id: str,
        mutator: Callable[[dict], dict],
        result_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """在行锁中更新结果 JSON，避免并发人审相互覆盖。"""
        async with async_session() as db:
            stmt = select(ResumeResultModel).where(
                ResumeResultModel.id == result_id,
                ResumeResultModel.user_id == user_id,
            )
            if result_type:
                stmt = stmt.where(ResumeResultModel.result_type == result_type)
            stmt = stmt.with_for_update()
            row = await db.execute(stmt)
            obj = row.scalar_one_or_none()
            if not obj:
                return None
            obj.result_data = mutator(obj.result_data)
            await db.commit()
            await db.refresh(obj)
            return self._row_to_dict(obj)

    async def list_results(
        self,
        user_id: str,
        result_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        include_data: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        获取用户的历史结果列表

        Args:
            user_id: 用户ID
            result_type: 结果类型过滤（可选）
            limit: 最大返回数量

        Returns:
            结果列表
        """
        async with async_session() as db:
            stmt = select(ResumeResultModel).where(ResumeResultModel.user_id == user_id)
            if result_type:
                stmt = stmt.where(ResumeResultModel.result_type == result_type)
            stmt = stmt.order_by(ResumeResultModel.created_at.desc()).limit(limit).offset(offset)
            rows = await db.execute(stmt)
            return [self._row_to_history_item(row, include_data=include_data) for row in rows.scalars().all()]

    async def count_results(self, user_id: str, result_type: Optional[str] = None) -> int:
        """获取用户简历历史总数，用于分页。"""
        async with async_session() as db:
            stmt = select(func.count(ResumeResultModel.id)).where(ResumeResultModel.user_id == user_id)
            if result_type:
                stmt = stmt.where(ResumeResultModel.result_type == result_type)
            return int((await db.scalar(stmt)) or 0)

    async def delete_result(self, result_id: int, user_id: str) -> bool:
        """
        删除结果

        Args:
            result_id: 结果ID
            user_id: 用户ID（用于权限校验）

        Returns:
            是否删除成功
        """
        async with async_session() as db:
            try:
                result = await db.execute(
                    delete(ResumeResultModel).where(
                        ResumeResultModel.id == result_id,
                        ResumeResultModel.user_id == user_id,
                    )
                )
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"删除简历结果: ID={result_id}")
                return deleted

            except Exception as e:
                logger.error(f"删除简历结果失败: {e}")
                return False

    def _row_to_dict(self, row: ResumeResultModel) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row.id,
            'user_id': row.user_id,
            'result_type': row.result_type,
            'resume_content': row.resume_content,
            'job_description': row.job_description,
            'session_ids': row.session_ids or [],
            'include_profile': row.include_profile,
            'result_data': row.result_data,
            'created_at': row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at
        }

    def _row_to_history_item(self, row: ResumeResultModel, *, include_data: bool) -> Dict[str, Any]:
        """列表项按需携带大字段，默认行为仍兼容旧客户端。"""
        item = self._row_to_dict(row)
        item['resume_preview'] = (row.resume_content or '')[:240]
        if not include_data:
            item['resume_content'] = None
            item['result_data'] = None
            item.pop('user_id', None)
        return item


# 全局单例
_resume_repo = None


def get_resume_repo() -> ResumeRepo:
    """获取 ResumeRepo 单例"""
    global _resume_repo
    if _resume_repo is None:
        _resume_repo = ResumeRepo()
    return _resume_repo
