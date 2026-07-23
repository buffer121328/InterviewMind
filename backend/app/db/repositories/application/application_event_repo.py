"""
投递事件流水持久化服务
负责 application_events 表的增删查，以及联动更新投递主表状态
"""

import logging
from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import async_session
from app.db.models.application import ApplicationEventModel, JobApplicationModel
from app.schemas.job_application import EventCreateRequest, ApplicationEventRow

logger = logging.getLogger(__name__)


class ApplicationEventRepo:
    """投递事件流水服务类"""

    def __init__(self):
        """初始化当前对象实例。"""
        logger.info("ApplicationEventRepo 初始化")

    async def add_event(
        self,
        application_id: int,
        request: EventCreateRequest,
        session: AsyncSession | None = None,
    ) -> ApplicationEventRow:
        """新增投递事件，并在必要时更新主表状态；可接入外层 UnitOfWork。"""

        async def _add(db: AsyncSession, *, owns_session: bool) -> ApplicationEventRow:
            """新增 当前对象。

            Args:
                db: 数据库会话。
                owns_session: 调用方传入的 `owns_session` 参数。
            """
            try:
                now = datetime.now()
                event_time = request.event_time or now
                if isinstance(event_time, str):
                    event_time = datetime.fromisoformat(event_time)

                event_obj = ApplicationEventModel(
                    application_id=application_id,
                    event_type=request.event_type,
                    event_time=event_time,
                    event_data=request.event_data or {},
                    created_at=now,
                )
                db.add(event_obj)

                status_types = {
                    'saved', 'applied', 'phone_screen', 'technical', 'behavioral',
                    'final', 'offer', 'rejected', 'accepted'
                }
                if request.event_type in status_types:
                    app_stmt = select(JobApplicationModel).where(JobApplicationModel.id == application_id)
                    app_result = await db.execute(app_stmt)
                    application = app_result.scalar_one_or_none()
                    if application:
                        application.latest_status = 'interview' if request.event_type in {
                            'phone_screen', 'technical', 'behavioral', 'final'
                        } else request.event_type
                        application.updated_at = now

                await db.flush()
                if owns_session:
                    await db.commit()
                    await db.refresh(event_obj)
                logger.info(f"创建投递事件: ID={event_obj.id}, application_id={application_id}, type={request.event_type}")
                return self._row_to_model(event_obj)
            except Exception as e:
                logger.error(f"创建投递事件失败: {e}")
                raise

        if session is not None:
            return await _add(session, owns_session=False)
        async with async_session() as db:
            return await _add(db, owns_session=True)

    async def list_events(self, application_id: int) -> List[ApplicationEventRow]:
        """获取某个投递记录的事件列表"""
        async with async_session() as db:
            stmt = (
                select(ApplicationEventModel)
                .where(ApplicationEventModel.application_id == application_id)
                .order_by(ApplicationEventModel.event_time.desc())
            )
            result = await db.execute(stmt)
            return [self._row_to_model(row) for row in result.scalars().all()]

    async def delete_event(self, event_id: int) -> bool:
        """删除单个事件"""
        async with async_session() as db:
            try:
                stmt = select(ApplicationEventModel).where(ApplicationEventModel.id == event_id)
                result = await db.execute(stmt)
                obj = result.scalar_one_or_none()
                if not obj:
                    return False
                await db.delete(obj)
                await db.commit()
                logger.info(f"删除投递事件: ID={event_id}")
                return True
            except Exception as e:
                logger.error(f"删除投递事件失败: {e}")
                return False

    def _row_to_model(self, row: ApplicationEventModel) -> ApplicationEventRow:
        """将数据库行转换为事件模型"""
        return ApplicationEventRow(
            id=row.id,
            application_id=row.application_id,
            event_type=row.event_type,
            event_time=row.event_time.isoformat() if isinstance(row.event_time, datetime) else row.event_time,
            event_data=row.event_data or {},
            created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
        )


application_event_repo = ApplicationEventRepo()
