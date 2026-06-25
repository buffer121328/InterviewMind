"""
候选人素材库持久化服务
负责候选人素材的存储和管理
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import delete, func, select, String

from app.models import async_session
from app.models.resume import CandidateMaterialModel

logger = logging.getLogger(__name__)


class CandidateMaterialRepo:
    """候选人素材服务类 - 管理候选人素材库"""
    
    def __init__(self):
        """初始化素材服务"""
        logger.info("CandidateMaterialService 初始化")
    
    async def create_material(
        self,
        user_id: str,
        material_type: str,
        title: str,
        content: str,
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        source_type: str = 'manual',
        source_resume_id: Optional[int] = None,
        importance_score: float = 0.5,
        confidence_score: float = 0.5,
        is_verified: bool = False
    ) -> int:
        """
        创建素材
        
        Args:
            user_id: 用户ID
            material_type: 素材类型 (tech_stack, project, internship, work_experience, education, certificate, highlight)
            title: 素材标题
            content: 素材内容
            structured_data: 结构化数据
            tags: 标签列表
            source_type: 来源类型 (manual, import, ai_extract)
            source_resume_id: 来源简历ID（如果是从简历导入）
            importance_score: 重要性评分 (0-1)
            confidence_score: 可信度评分 (0-1)
            is_verified: 是否已验证
            
        Returns:
            int: 素材ID
        """
        async with async_session() as db:
            try:
                now = datetime.now()
                db_obj = CandidateMaterialModel(
                    user_id=user_id,
                    material_type=material_type,
                    title=title,
                    content=content,
                    structured_data=structured_data or {},
                    tags=tags or [],
                    source_type=source_type,
                    source_resume_id=source_resume_id,
                    importance_score=importance_score,
                    confidence_score=confidence_score,
                    is_verified=is_verified,
                    created_at=now,
                    updated_at=now,
                )
                db.add(db_obj)
                await db.commit()
                await db.refresh(db_obj)
                material_id = db_obj.id
                
                logger.info(f"创建素材: ID={material_id}, type={material_type}, user={user_id}")
                return material_id
                
            except Exception as e:
                logger.error(f"创建素材失败: {e}")
                raise
    
    async def get_material(self, material_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个素材
        
        Args:
            material_id: 素材ID
            user_id: 用户ID（用于权限校验）
            
        Returns:
            素材数据字典，如果不存在或无权限则返回 None
        """
        async with async_session() as db:
            stmt = select(CandidateMaterialModel).where(
                CandidateMaterialModel.id == material_id,
                CandidateMaterialModel.user_id == user_id,
            )
            result = await db.execute(stmt)
            obj = result.scalar_one_or_none()

            if not obj:
                return None
            
            return self._row_to_dict(obj)
    
    async def list_materials(
        self,
        user_id: str,
        material_type: Optional[str] = None,
        is_verified: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        获取用户的素材列表
        
        Args:
            user_id: 用户ID
            material_type: 素材类型过滤（可选）
            is_verified: 是否已验证过滤（可选）
            limit: 最大返回数量
            offset: 偏移量
            
        Returns:
            素材列表
        """
        async with async_session() as db:
            stmt = select(CandidateMaterialModel).where(CandidateMaterialModel.user_id == user_id)
            if material_type:
                stmt = stmt.where(CandidateMaterialModel.material_type == material_type)
            if is_verified is not None:
                stmt = stmt.where(CandidateMaterialModel.is_verified == is_verified)
            stmt = stmt.order_by(CandidateMaterialModel.created_at.desc()).limit(limit).offset(offset)
            rows = await db.execute(stmt)
            return [self._row_to_dict(row) for row in rows.scalars().all()]
    
    async def update_material(
        self,
        material_id: int,
        user_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        structured_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        importance_score: Optional[float] = None,
        confidence_score: Optional[float] = None,
        is_verified: Optional[bool] = None
    ) -> bool:
        """
        更新素材
        
        Args:
            material_id: 素材ID
            user_id: 用户ID（用于权限校验）
            title: 新标题（可选）
            content: 新内容（可选）
            structured_data: 新结构化数据（可选）
            tags: 新标签（可选）
            importance_score: 新重要性评分（可选）
            confidence_score: 新可信度评分（可选）
            is_verified: 新验证状态（可选）
            
        Returns:
            是否更新成功
        """
        async with async_session() as db:
            try:
                result = await db.execute(select(CandidateMaterialModel).where(
                    CandidateMaterialModel.id == material_id,
                    CandidateMaterialModel.user_id == user_id,
                ))
                obj = result.scalar_one_or_none()
                if not obj:
                    return False

                if title is not None:
                    obj.title = title
                if content is not None:
                    obj.content = content
                if structured_data is not None:
                    obj.structured_data = structured_data
                if tags is not None:
                    obj.tags = tags
                if importance_score is not None:
                    obj.importance_score = importance_score
                if confidence_score is not None:
                    obj.confidence_score = confidence_score
                if is_verified is not None:
                    obj.is_verified = is_verified
                obj.updated_at = datetime.now()

                await db.commit()
                updated = True
                if updated:
                    logger.info(f"更新素材: ID={material_id}")
                return updated
                
            except Exception as e:
                logger.error(f"更新素材失败: {e}")
                return False
    
    async def delete_material(self, material_id: int, user_id: str) -> bool:
        """
        删除素材
        
        Args:
            material_id: 素材ID
            user_id: 用户ID（用于权限校验）
            
        Returns:
            是否删除成功
        """
        async with async_session() as db:
            try:
                result = await db.execute(delete(CandidateMaterialModel).where(
                    CandidateMaterialModel.id == material_id,
                    CandidateMaterialModel.user_id == user_id,
                ))
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"删除素材: ID={material_id}")
                return deleted
                
            except Exception as e:
                logger.error(f"删除素材失败: {e}")
                return False
    
    async def get_materials_by_ids(
        self,
        material_ids: List[int],
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        根据ID列表获取素材
        
        Args:
            material_ids: 素材ID列表
            user_id: 用户ID（用于权限校验）
            
        Returns:
            素材列表
        """
        if not material_ids:
            return []
        
        async with async_session() as db:
            stmt = select(CandidateMaterialModel).where(
                CandidateMaterialModel.id.in_(material_ids),
                CandidateMaterialModel.user_id == user_id,
            ).order_by(CandidateMaterialModel.created_at.desc())
            rows = await db.execute(stmt)
            return [self._row_to_dict(row) for row in rows.scalars().all()]
    
    async def search_materials(
        self,
        user_id: str,
        keyword: str,
        material_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        搜索素材
        
        Args:
            user_id: 用户ID
            keyword: 搜索关键词
            material_type: 素材类型过滤（可选）
            limit: 最大返回数量
            
        Returns:
            匹配的素材列表
        """
        async with async_session() as db:
            stmt = select(CandidateMaterialModel).where(
                CandidateMaterialModel.user_id == user_id,
                (CandidateMaterialModel.title.ilike(f'%{keyword}%')) |
                (CandidateMaterialModel.content.ilike(f'%{keyword}%')) |
                (CandidateMaterialModel.tags.cast(String).ilike(f'%{keyword}%')),
            )
            if material_type:
                stmt = stmt.where(CandidateMaterialModel.material_type == material_type)
            stmt = stmt.order_by(CandidateMaterialModel.created_at.desc()).limit(limit)
            rows = await db.execute(stmt)
            return [self._row_to_dict(row) for row in rows.scalars().all()]
    
    async def get_material_count(
        self,
        user_id: str,
        material_type: Optional[str] = None
    ) -> int:
        """
        获取素材数量
        
        Args:
            user_id: 用户ID
            material_type: 素材类型过滤（可选）
            
        Returns:
            素材数量
        """
        async with async_session() as db:
            stmt = select(func.count()).select_from(CandidateMaterialModel).where(CandidateMaterialModel.user_id == user_id)
            if material_type:
                stmt = stmt.where(CandidateMaterialModel.material_type == material_type)
            result = await db.execute(stmt)
            return result.scalar_one()
    
    def _row_to_dict(self, row: CandidateMaterialModel) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row.id,
            'user_id': row.user_id,
            'material_type': row.material_type,
            'title': row.title,
            'content': row.content,
            'structured_data': row.structured_data or {},
            'tags': row.tags or [],
            'source_type': row.source_type,
            'source_resume_id': row.source_resume_id,
            'importance_score': row.importance_score,
            'confidence_score': row.confidence_score,
            'is_verified': row.is_verified,
            'created_at': row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            'updated_at': row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at
        }


# 全局单例
_candidate_material_repo = None


def get_candidate_material_repo() -> CandidateMaterialRepo:
    """获取 CandidateMaterialService 单例"""
    global _candidate_material_repo
    if _candidate_material_repo is None:
        _candidate_material_repo = CandidateMaterialRepo()
    return _candidate_material_repo
