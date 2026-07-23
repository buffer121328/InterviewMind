"""
岗位投递记录持久化服务
负责投递记录的存储、查询、更新和删除
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import async_session
from app.db.models.application import JobApplicationModel, ApplicationEventModel
from app.schemas.job_application import (
    ApplicationCreateRequest,
    ApplicationUpdateRequest,
    ApplicationListItem,
    ApplicationDetail,
    ApplicationEventRow,
)

logger = logging.getLogger(__name__)


class JobApplicationRepo:
    """岗位投递记录服务类"""

    def __init__(self):
        """初始化投递记录服务"""
        logger.info("JobApplicationRepo 初始化")

    async def create_application(
        self,
        user_id: str,
        request: ApplicationCreateRequest,
        session: AsyncSession | None = None,
    ) -> ApplicationDetail:
        """创建投递记录并返回详情；传入 session 时由外层 UnitOfWork 统一提交。"""
        now = datetime.now()

        async def _create(db: AsyncSession, *, owns_session: bool) -> ApplicationDetail:
            """创建 当前对象。

            Args:
                db: 数据库会话。
                owns_session: 调用方传入的 `owns_session` 参数。
            """
            db_obj = JobApplicationModel(
                user_id=user_id,
                company_name=request.company_name,
                job_title=request.job_title,
                job_description=request.job_description,
                channel=request.channel,
                generated_resume_id=request.generated_resume_id,
                latest_status=request.latest_status or "saved",
                priority=request.priority or "medium",
                notes=request.notes,
                created_at=now,
                updated_at=now,
            )
            db.add(db_obj)
            await db.flush()
            if owns_session:
                await db.commit()
                await db.refresh(db_obj)

            logger.info(f"创建投递记录: ID={db_obj.id}, user={user_id}")
            return self._row_to_detail(db_obj)

        if session is not None:
            return await _create(session, owns_session=False)
        async with async_session() as db:
            return await _create(db, owns_session=True)

    async def list_applications(
        self,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ApplicationListItem]:
        """获取投递记录列表"""
        async with async_session() as db:
            stmt = select(JobApplicationModel).where(JobApplicationModel.user_id == user_id)
            if status:
                stmt = stmt.where(JobApplicationModel.latest_status == status)
            stmt = stmt.order_by(JobApplicationModel.updated_at.desc()).limit(limit).offset(offset)
            result = await db.execute(stmt)
            return [self._row_to_list_item(row) for row in result.scalars().all()]

    async def get_application(
        self,
        application_id: int,
        user_id: str,
    ) -> Optional[ApplicationDetail]:
        """获取单个投递记录详情"""
        async with async_session() as db:
            stmt = (
                select(JobApplicationModel)
                .options(selectinload(JobApplicationModel.events))
                .where(JobApplicationModel.id == application_id, JobApplicationModel.user_id == user_id)
            )
            result = await db.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return None
            return self._row_to_detail(obj)

    async def update_application(
        self,
        application_id: int,
        user_id: str,
        request: ApplicationUpdateRequest,
    ) -> Optional[ApplicationDetail]:
        """更新投递记录并返回详情"""
        async with async_session() as db:
            stmt = select(JobApplicationModel).where(
                JobApplicationModel.id == application_id,
                JobApplicationModel.user_id == user_id,
            )
            result = await db.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return None

            fields = [
                ("company_name", request.company_name),
                ("job_title", request.job_title),
                ("job_description", request.job_description),
                ("channel", request.channel),
                ("generated_resume_id", request.generated_resume_id),
                ("latest_status", request.latest_status),
                ("priority", request.priority),
                ("notes", request.notes),
            ]
            changed = False
            for field_name, value in fields:
                if value is not None:
                    setattr(obj, field_name, value)
                    changed = True

            if not changed:
                return await self.get_application(application_id, user_id)

            obj.updated_at = datetime.now()
            await db.commit()
            await db.refresh(obj)
            return await self.get_application(application_id, user_id)

    async def delete_application(self, application_id: int, user_id: str) -> bool:
        """删除投递记录"""
        async with async_session() as db:
            stmt = select(JobApplicationModel).where(
                JobApplicationModel.id == application_id,
                JobApplicationModel.user_id == user_id,
            )
            result = await db.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return False

            await db.delete(obj)
            await db.commit()
            logger.info(f"删除投递记录: ID={application_id}")
            return True

    async def get_application_count(self, user_id: str, status: Optional[str] = None) -> int:
        """获取投递记录数量"""
        async with async_session() as db:
            stmt = select(func.count(JobApplicationModel.id)).where(JobApplicationModel.user_id == user_id)
            if status:
                stmt = stmt.where(JobApplicationModel.latest_status == status)
            result = await db.execute(stmt)
            return int(result.scalar_one() or 0)

    def _row_to_list_item(self, row: JobApplicationModel) -> ApplicationListItem:
        """将数据库行转换为列表项"""
        return ApplicationListItem(
            id=row.id,
            company_name=row.company_name,
            job_title=row.job_title,
            channel=row.channel,
            generated_resume_id=row.generated_resume_id,
            latest_status=row.latest_status,
            priority=row.priority,
            notes=row.notes,
            created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            updated_at=row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
        )

    def _row_to_detail(self, row: JobApplicationModel) -> ApplicationDetail:
        """将数据库行转换为详情对象"""
        return ApplicationDetail(
            id=row.id,
            user_id=row.user_id,
            company_name=row.company_name,
            job_title=row.job_title,
            job_description=row.job_description,
            channel=row.channel,
            generated_resume_id=row.generated_resume_id,
            latest_status=row.latest_status,
            priority=row.priority,
            notes=row.notes,
            created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
            updated_at=row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
            events=[self._event_row_to_model(event) for event in getattr(row, "events", [])],
        )

    def _event_row_to_model(self, row: ApplicationEventModel) -> ApplicationEventRow:
        """将事件数据库行转换为模型"""
        return ApplicationEventRow(
            id=row.id,
            application_id=row.application_id,
            event_type=row.event_type,
            event_time=row.event_time.isoformat() if isinstance(row.event_time, datetime) else row.event_time,
            event_data=row.event_data,
            created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
        )


job_application_repo = JobApplicationRepo()
