"""
简历工具持久化服务
负责简历优化/分析结果的存储和管理
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import delete, select

from app.models import async_session
from app.models.resume import ResumeResultModel

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
        session_ids: List[str] = [],
        include_profile: bool = False
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
        async with async_session() as db:
            try:
                db_obj = ResumeResultModel(
                    user_id=user_id,
                    result_type=result_type,
                    resume_content=resume_content,
                    job_description=job_description,
                    session_ids=session_ids or None,
                    include_profile=include_profile,
                    result_data=result_data,
                    created_at=datetime.now(),
                )
                db.add(db_obj)
                await db.commit()
                await db.refresh(db_obj)
                result_id = db_obj.id
                
                logger.info(f"保存简历{result_type}结果: ID={result_id}, user={user_id}")
                return result_id
                
            except Exception as e:
                logger.error(f"保存简历结果失败: {e}")
                raise
    
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
    
    async def list_results(
        self,
        user_id: str,
        result_type: Optional[str] = None,
        limit: int = 20
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
            stmt = stmt.order_by(ResumeResultModel.created_at.desc()).limit(limit)
            rows = await db.execute(stmt)
            return [self._row_to_dict(row) for row in rows.scalars().all()]
    
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


# 全局单例
_resume_repo = None


def get_resume_repo() -> ResumeRepo:
    """获取 ResumeRepo 单例"""
    global _resume_repo
    if _resume_repo is None:
        _resume_repo = ResumeRepo()
    return _resume_repo
