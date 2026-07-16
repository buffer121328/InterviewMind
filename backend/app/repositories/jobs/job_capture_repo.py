"""
岗位采集仓储 — Captured Jobs CRUD
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy import select, delete, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.base import async_session
from app.models.job_capture import CapturedJobModel

logger = logging.getLogger(__name__)


class JobCaptureRepo:
    """岗位采集仓储"""

    async def save_job(
        self,
        user_id: str,
        job_data: Dict[str, Any],
    ) -> int:
        """
        保存岗位采集记录。
        
        Returns:
            新记录的 ID
        """
        async with async_session() as db:
            row = CapturedJobModel(
                user_id=user_id,
                platform=job_data.get("platform", "boss"),
                external_job_id=job_data.get("external_job_id"),
                source_url=job_data.get("source_url", ""),
                source_text=job_data.get("source_text", ""),
                company_name=job_data.get("company_name", ""),
                job_title=job_data.get("job_title", ""),
                job_description=job_data.get("job_description", ""),
                salary_text=job_data.get("salary_text", ""),
                salary_min=job_data.get("salary_min"),
                salary_max=job_data.get("salary_max"),
                city=job_data.get("city", ""),
                tags=job_data.get("tags", []),
                source_hash=job_data.get("source_hash", ""),
                status=job_data.get("status", "pending"),
                captured_at=datetime.now() if not job_data.get("captured_at") else None,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row.id

    async def get_job(
        self,
        job_id: int,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """获取单个岗位"""
        async with async_session() as db:
            result = await db.execute(
                select(CapturedJobModel).where(
                    and_(
                        CapturedJobModel.id == job_id,
                        CapturedJobModel.user_id == user_id,
                    )
                )
            )
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def list_jobs(
        self,
        user_id: str,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列表查询"""
        async with async_session() as db:
            stmt = select(CapturedJobModel).where(
                CapturedJobModel.user_id == user_id
            )

            if platform:
                stmt = stmt.where(CapturedJobModel.platform == platform)
            if status:
                stmt = stmt.where(CapturedJobModel.status == status)

            stmt = stmt.order_by(CapturedJobModel.captured_at.desc())
            stmt = stmt.offset(offset).limit(limit)

            result = await db.execute(stmt)
            rows = result.scalars().all()
            return [row.to_dict() for row in rows]

    async def delete_job(
        self,
        job_id: int,
        user_id: str,
    ) -> bool:
        """删除岗位"""
        async with async_session() as db:
            result = await db.execute(
                delete(CapturedJobModel).where(
                    and_(
                        CapturedJobModel.id == job_id,
                        CapturedJobModel.user_id == user_id,
                    )
                )
            )
            await db.commit()
            return result.rowcount > 0

    async def find_by_hash(
        self,
        source_hash: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """通过 source_hash 查找（去重）"""
        async with async_session() as db:
            result = await db.execute(
                select(CapturedJobModel).where(
                    and_(
                        CapturedJobModel.source_hash == source_hash,
                        CapturedJobModel.user_id == user_id,
                    )
                )
            )
            row = result.scalar_one_or_none()
            return row.to_dict() if row else None

    async def get_job_count(
        self,
        user_id: str,
        platform: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """获取岗位数量"""
        async with async_session() as db:
            stmt = select(func.count(CapturedJobModel.id)).where(
                CapturedJobModel.user_id == user_id
            )
            if platform:
                stmt = stmt.where(CapturedJobModel.platform == platform)
            if status:
                stmt = stmt.where(CapturedJobModel.status == status)

            result = await db.execute(stmt)
            return result.scalar() or 0

    async def update_status(
        self,
        job_id: int,
        user_id: str,
        status: str,
        session: AsyncSession | None = None,
    ) -> bool:
        """更新岗位状态；传入 session 时由外层 UnitOfWork 统一提交。"""

        async def _update(db: AsyncSession, *, owns_session: bool) -> bool:
            result = await db.execute(
                select(CapturedJobModel).where(
                    and_(
                        CapturedJobModel.id == job_id,
                        CapturedJobModel.user_id == user_id,
                    )
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.status = status
                row.updated_at = datetime.now()
                if owns_session:
                    await db.commit()
                return True
            return False

        if session is not None:
            return await _update(session, owns_session=False)
        async with async_session() as db:
            return await _update(db, owns_session=True)

    async def claim_for_application(self, job_id: int, user_id: str, session: AsyncSession | None = None) -> bool:
        """原子占用岗位发送权，防止多请求重复点击；可接入外层 UnitOfWork。"""

        async def _claim(db: AsyncSession, *, owns_session: bool) -> bool:
            result = await db.execute(
                update(CapturedJobModel)
                .where(
                    CapturedJobModel.id == job_id,
                    CapturedJobModel.user_id == user_id,
                    CapturedJobModel.status.notin_(["applied", "applying", "manual_takeover"]),
                )
                .values(status="applying", updated_at=datetime.now())
            )
            if owns_session:
                await db.commit()
            return result.rowcount == 1

        if session is not None:
            return await _claim(session, owns_session=False)
        async with async_session() as db:
            return await _claim(db, owns_session=True)


# 全局单例
_job_capture_repo: Optional[JobCaptureRepo] = None


def get_job_capture_repo() -> JobCaptureRepo:
    """获取 JobCaptureRepo 单例"""
    global _job_capture_repo
    if _job_capture_repo is None:
        _job_capture_repo = JobCaptureRepo()
    return _job_capture_repo
