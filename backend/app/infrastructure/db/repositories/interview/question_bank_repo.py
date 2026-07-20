"""
题库持久化服务
负责题库条目的 CRUD 和检索
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select, update, delete, text

from app.infrastructure.db.models import async_session
from app.infrastructure.db.models.interview import QuestionBankItemModel, QuestionBankImportModel

logger = logging.getLogger(__name__)


class QuestionBankRepo:
    """题库服务类"""
    
    def __init__(self):
        logger.info("QuestionBankService 初始化")
    
    async def create_item(
        self,
        user_id: str,
        question_text: str,
        reference_answer: Optional[str] = None,
        tags: Optional[List[str]] = None,
        difficulty: str = "medium",
        target_skill: Optional[str] = None,
        question_type: str = "tech",
        source_type: str = "manual",
        source_id: Optional[str] = None,
        origin_session_id: Optional[str] = None
    ) -> int:
        """创建题库条目"""
        async with async_session() as db:
            now = datetime.now()
            obj = QuestionBankItemModel(
                user_id=user_id,
                source_type=source_type,
                source_id=source_id,
                origin_session_id=origin_session_id,
                question_text=question_text,
                reference_answer=reference_answer,
                tags=tags or [],
                difficulty=difficulty,
                target_skill=target_skill,
                question_type=question_type,
                is_verified=False,
                usage_count=0,
                created_at=now,
                updated_at=now,
            )
            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            logger.info(f"创建题库条目: ID={obj.id}, user={user_id}")
            return obj.id
    
    async def get_item(self, item_id: int, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取题库条目"""
        async with async_session() as db:
            stmt = select(QuestionBankItemModel).where(QuestionBankItemModel.id == item_id)
            if user_id:
                stmt = stmt.where(QuestionBankItemModel.user_id == user_id)
            result = await db.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return None
            return self._row_to_dict(obj)
    
    async def list_items(
        self,
        user_id: str,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        is_verified: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """列出题库条目（支持筛选）"""
        async with async_session() as db:
            stmt = select(QuestionBankItemModel).where(QuestionBankItemModel.user_id == user_id)
            if question_type:
                stmt = stmt.where(QuestionBankItemModel.question_type == question_type)
            if difficulty:
                stmt = stmt.where(QuestionBankItemModel.difficulty == difficulty)
            if is_verified is not None:
                stmt = stmt.where(QuestionBankItemModel.is_verified == is_verified)
            stmt = stmt.order_by(QuestionBankItemModel.created_at.desc()).limit(limit).offset(offset)
            rows = (await db.execute(stmt)).scalars().all()
            return [self._row_to_dict(row) for row in rows]
    
    async def search_items(
        self,
        user_id: str,
        query: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """检索题库条目。

        使用 ILIKE + pg_trgm similarity，兼容中文题目；避免 PostgreSQL english tokenizer 对中文无效。
        """
        async with async_session() as db:
            stmt = text("""
                SELECT *,
                       GREATEST(
                           similarity(question_text, :query),
                           similarity(COALESCE(reference_answer, ''), :query),
                           similarity(COALESCE(tags::text, ''), :query)
                       ) AS rank
                FROM question_bank_items
                WHERE user_id = :user_id
                  AND (
                    question_text ILIKE :pattern
                    OR COALESCE(reference_answer, '') ILIKE :pattern
                    OR COALESCE(tags::text, '') ILIKE :pattern
                    OR similarity(question_text, :query) > 0.1
                  )
                ORDER BY rank DESC
                LIMIT :limit
            """)
            rows = (await db.execute(stmt, {
                "user_id": user_id,
                "query": query,
                "pattern": f"%{query}%",
                "limit": limit,
            })).mappings().all()
            return [self._row_to_dict(row) for row in rows]
    
    async def update_item(
        self,
        item_id: int,
        user_id: str,
        **kwargs
    ) -> bool:
        """更新题库条目"""
        allowed_fields = {
            'question_text', 'reference_answer', 'tags', 'difficulty',
            'target_skill', 'question_type', 'is_verified'
        }
        values = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not values:
            return False
        values['updated_at'] = datetime.now()
        async with async_session() as db:
            stmt = (
                update(QuestionBankItemModel)
                .where(QuestionBankItemModel.id == item_id, QuestionBankItemModel.user_id == user_id)
                .values(**values)
            )
            result = await db.execute(stmt)
            await db.commit()
            return result.rowcount > 0
    
    async def delete_item(self, item_id: int, user_id: str) -> bool:
        """删除题库条目"""
        async with async_session() as db:
            result = await db.execute(
                delete(QuestionBankItemModel).where(
                    QuestionBankItemModel.id == item_id,
                    QuestionBankItemModel.user_id == user_id,
                )
            )
            await db.commit()
            return result.rowcount > 0
    
    async def increment_usage(self, item_id: int) -> None:
        """增加使用次数"""
        async with async_session() as db:
            await db.execute(
                update(QuestionBankItemModel)
                .where(QuestionBankItemModel.id == item_id)
                .values(usage_count=QuestionBankItemModel.usage_count + 1, updated_at=datetime.now())
            )
            await db.commit()

    async def select_for_interview(self, user_id: str, limit: int) -> List[Dict[str, Any]]:
        """优先抽取使用次数较少的题，避免重复轰炸同一用户。"""
        if limit <= 0:
            return []
        async with async_session() as db:
            stmt = (
                select(QuestionBankItemModel)
                .where(QuestionBankItemModel.user_id == user_id)
                .order_by(
                    QuestionBankItemModel.usage_count.asc(),
                    QuestionBankItemModel.is_verified.desc(),
                    QuestionBankItemModel.updated_at.desc(),
                )
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [self._row_to_dict(row) for row in rows]

    async def get_items_by_skill(
        self,
        user_id: str,
        target_skill: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """按技能检索题库条目"""
        async with async_session() as db:
            stmt = (
                select(QuestionBankItemModel)
                .where(QuestionBankItemModel.user_id == user_id, QuestionBankItemModel.target_skill == target_skill)
                .order_by(QuestionBankItemModel.usage_count.desc(), QuestionBankItemModel.created_at.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [self._row_to_dict(row) for row in rows]
    
    async def save_import_record(
        self,
        user_id: str,
        import_source: str,
        file_name: Optional[str],
        total_count: int,
        success_count: int,
        summary: Optional[str]
    ) -> int:
        """保存导入记录"""
        async with async_session() as db:
            now = datetime.now()
            obj = QuestionBankImportModel(
                user_id=user_id,
                import_source=import_source,
                import_status='completed',
                file_name=file_name,
                total_count=total_count,
                success_count=success_count,
                summary=summary,
                created_at=now,
            )
            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            return obj.id
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        if hasattr(row, '_mapping'):
            data = dict(row._mapping)
        else:
            data = {
                'id': row.id,
                'user_id': row.user_id,
                'source_type': getattr(row, 'source_type', None),
                'source_id': getattr(row, 'source_id', None),
                'origin_session_id': getattr(row, 'origin_session_id', None),
                'question_text': getattr(row, 'question_text', None),
                'reference_answer': getattr(row, 'reference_answer', None),
                'tags': getattr(row, 'tags', None),
                'difficulty': getattr(row, 'difficulty', None),
                'target_skill': getattr(row, 'target_skill', None),
                'question_type': getattr(row, 'question_type', None),
                'is_verified': getattr(row, 'is_verified', None),
                'usage_count': getattr(row, 'usage_count', None),
                'created_at': getattr(row, 'created_at', None),
                'updated_at': getattr(row, 'updated_at', None),
            }
        for field in ['created_at', 'updated_at']:
            if field in data and isinstance(data[field], datetime):
                data[field] = data[field].isoformat()
        return data


# 全局单例
_question_bank_repo = None


def get_question_bank_repo() -> QuestionBankRepo:
    """获取 QuestionBankService 单例"""
    global _question_bank_repo
    if _question_bank_repo is None:
        _question_bank_repo = QuestionBankRepo()
    return _question_bank_repo
