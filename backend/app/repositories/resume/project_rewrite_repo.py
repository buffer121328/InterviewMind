"""
项目经历重写助手持久化服务
负责项目经历重写记录的存储和管理
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import delete, select

from app.models import async_session
from app.models.resume import ProjectRewriteRecordModel

logger = logging.getLogger(__name__)


class ProjectRewriteRepo:
    """项目经历重写服务类 - 管理重写记录"""
    
    def __init__(self):
        """初始化重写服务"""
        logger.info("ProjectRewriteService 初始化")
    
    async def save_rewrite(
        self,
        user_id: str,
        material_id: Optional[int],
        project_title: str,
        original_content: str,
        rewrite_mode: str,
        job_description: Optional[str],
        result_data: Dict[str, Any]
    ) -> int:
        """保存重写记录"""
        async with async_session() as db:
            try:
                db_obj = ProjectRewriteRecordModel(
                    user_id=user_id,
                    material_id=material_id,
                    project_title=project_title,
                    original_content=original_content,
                    rewrite_mode=rewrite_mode,
                    job_description=job_description,
                    result_data=result_data or {},
                    created_at=datetime.now(),
                )
                db.add(db_obj)
                await db.commit()
                await db.refresh(db_obj)
                rewrite_id = db_obj.id
                logger.info(f"创建项目重写记录: ID={rewrite_id}, mode={rewrite_mode}, user={user_id}")
                return rewrite_id
            except Exception as e:
                logger.error(f"创建项目重写记录失败: {e}")
                raise
    
    async def get_rewrite(self, rewrite_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        """获取单个重写记录"""
        async with async_session() as db:
            result = await db.execute(select(ProjectRewriteRecordModel).where(
                ProjectRewriteRecordModel.id == rewrite_id,
                ProjectRewriteRecordModel.user_id == user_id,
            ))
            row = result.scalar_one_or_none()

            if not row:
                return None

            return self._row_to_dict(row)
    
    async def list_rewrites(
        self,
        user_id: str,
        rewrite_mode: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取用户的重写历史列表"""
        async with async_session() as db:
            stmt = select(ProjectRewriteRecordModel).where(ProjectRewriteRecordModel.user_id == user_id)
            if rewrite_mode:
                stmt = stmt.where(ProjectRewriteRecordModel.rewrite_mode == rewrite_mode)
            stmt = stmt.order_by(ProjectRewriteRecordModel.created_at.desc()).limit(limit).offset(offset)
            rows = await db.execute(stmt)
            return [self._row_to_dict(row) for row in rows.scalars().all()]
    
    async def delete_rewrite(self, rewrite_id: int, user_id: str) -> bool:
        """删除重写记录"""
        async with async_session() as db:
            try:
                result = await db.execute(delete(ProjectRewriteRecordModel).where(
                    ProjectRewriteRecordModel.id == rewrite_id,
                    ProjectRewriteRecordModel.user_id == user_id,
                ))
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"删除项目重写记录: ID={rewrite_id}")
                return deleted
            except Exception as e:
                logger.error(f"删除项目重写记录失败: {e}")
                return False
    
    async def get_rewrites_by_material(self, material_id: int, user_id: str) -> List[Dict[str, Any]]:
        """获取指定素材的重写记录"""
        async with async_session() as db:
            rows = await db.execute(select(ProjectRewriteRecordModel).where(
                ProjectRewriteRecordModel.material_id == material_id,
                ProjectRewriteRecordModel.user_id == user_id,
            ).order_by(ProjectRewriteRecordModel.created_at.desc()))
            return [self._row_to_dict(row) for row in rows.scalars().all()]
    
    def _row_to_dict(self, row: ProjectRewriteRecordModel) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row.id,
            'user_id': row.user_id,
            'material_id': row.material_id,
            'project_title': row.project_title,
            'original_content': row.original_content,
            'rewrite_mode': row.rewrite_mode,
            'job_description': row.job_description,
            'result_data': row.result_data or {},
            'created_at': row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at
        }


# 全局单例
_project_rewrite_repo = None


def get_project_rewrite_repo() -> ProjectRewriteRepo:
    """获取 ProjectRewriteService 单例"""
    global _project_rewrite_repo
    if _project_rewrite_repo is None:
        _project_rewrite_repo = ProjectRewriteRepo()
    return _project_rewrite_repo
