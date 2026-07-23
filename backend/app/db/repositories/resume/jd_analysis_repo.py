"""
JD 匹配分析持久化服务
负责 JD 分析结果的存储和管理
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import async_session
from app.db.models.jd import JdAnalysisResultModel

logger = logging.getLogger(__name__)


class JDAnalysisRepo:
    """JD 匹配分析服务类 - 管理 JD 分析结果"""

    def __init__(self):
        """初始化当前对象实例。"""
        logger.info("JDAnalysisService 初始化")

    async def save_result(
        self,
        user_id: str,
        resume_source_type: str,
        resume_content_snapshot: str,
        job_description: str,
        analysis_result: dict,
        resume_source_id: Optional[int] = None,
        session: AsyncSession | None = None,
    ) -> int:
        """
        保存 JD 匹配分析结果

        Args:
            user_id: 用户ID
            resume_source_type: 简历来源类型
            resume_content_snapshot: 分析时的简历文本快照
            job_description: 目标职位描述
            analysis_result: 完整分析结果 JSON
            resume_source_id: 来源对象 ID

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
                        resume_source_type=resume_source_type,
                        resume_content_snapshot=resume_content_snapshot,
                        job_description=job_description,
                        analysis_result=analysis_result,
                        resume_source_id=resume_source_id,
                        owns_session=True,
                    )
            assert db is not None
            return await self._save_result_with_session(
                db,
                user_id=user_id,
                resume_source_type=resume_source_type,
                resume_content_snapshot=resume_content_snapshot,
                job_description=job_description,
                analysis_result=analysis_result,
                resume_source_id=resume_source_id,
                owns_session=False,
            )
        except Exception as e:
            logger.error(f"保存 JD 分析结果失败: {e}")
            raise

    async def _save_result_with_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        resume_source_type: str,
        resume_content_snapshot: str,
        job_description: str,
        analysis_result: dict,
        resume_source_id: Optional[int] = None,
        owns_session: bool,
    ) -> int:
        """保存 `result with session`。

        Args:
            db: 数据库会话。
            user_id: 当前用户标识。
            resume_source_type: 调用方传入的 `resume_source_type` 参数。
            resume_content_snapshot: 调用方传入的 `resume_content_snapshot` 参数。
            job_description: 调用方传入的 `job_description` 参数。
            analysis_result: 调用方传入的 `analysis_result` 参数。
            resume_source_id: resume source 标识。
            owns_session: 调用方传入的 `owns_session` 参数。
        """
        now = datetime.now()
        db_obj = JdAnalysisResultModel(
            user_id=user_id,
            resume_source_type=resume_source_type,
            resume_source_id=resume_source_id,
            resume_content_snapshot=resume_content_snapshot,
            job_description=job_description,
            analysis_result=analysis_result,
            created_at=now,
            updated_at=now,
        )
        db.add(db_obj)
        await db.flush()
        result_id = db_obj.id
        if owns_session:
            await db.commit()
            await db.refresh(db_obj)
            result_id = db_obj.id
        logger.info(f"保存 JD 分析结果: ID={result_id}, user={user_id}")
        return result_id

    async def get_result(self, analysis_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个分析结果

        Args:
            analysis_id: 结果ID
            user_id: 用户ID（用于权限校验）

        Returns:
            结果数据字典，如果不存在或无权限则返回 None
        """
        async with async_session() as db:
            result = await db.execute(select(JdAnalysisResultModel).where(
                JdAnalysisResultModel.id == analysis_id,
                JdAnalysisResultModel.user_id == user_id,
            ))
            obj = result.scalar_one_or_none()

            if not obj:
                return None

            return self._row_to_dict(obj)

    async def list_results(
        self,
        user_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取用户的 JD 分析历史列表

        Args:
            user_id: 用户ID
            limit: 最大返回数量

        Returns:
            结果列表
        """
        async with async_session() as db:
            result = await db.execute(
                select(JdAnalysisResultModel)
                .where(JdAnalysisResultModel.user_id == user_id)
                .order_by(JdAnalysisResultModel.created_at.desc())
                .limit(limit)
            )
            return [self._row_to_dict(row) for row in result.scalars().all()]

    async def delete_result(self, analysis_id: int, user_id: str) -> bool:
        """
        删除分析结果

        Args:
            analysis_id: 结果ID
            user_id: 用户ID（用于权限校验）

        Returns:
            是否删除成功
        """
        async with async_session() as db:
            try:
                result = await db.execute(delete(JdAnalysisResultModel).where(
                    JdAnalysisResultModel.id == analysis_id,
                    JdAnalysisResultModel.user_id == user_id,
                ))
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"删除 JD 分析结果: ID={analysis_id}")
                return deleted

            except Exception as e:
                logger.error(f"删除 JD 分析结果失败: {e}")
                return False

    def _row_to_dict(self, row: JdAnalysisResultModel) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row.id,
            'user_id': row.user_id,
            'resume_source_type': row.resume_source_type,
            'resume_source_id': row.resume_source_id,
            'resume_content_snapshot': row.resume_content_snapshot,
            'job_description': row.job_description,
            'analysis_result': row.analysis_result,
            'created_at': row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            'updated_at': row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at
        }


# 全局单例
_jd_analysis_repo = None


def get_jd_analysis_repo() -> JDAnalysisRepo:
    """获取 JDAnalysisService 单例"""
    global _jd_analysis_repo
    if _jd_analysis_repo is None:
        _jd_analysis_repo = JDAnalysisRepo()
    return _jd_analysis_repo
