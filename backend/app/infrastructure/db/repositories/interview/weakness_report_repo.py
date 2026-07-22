"""
面试短板地图报告持久化服务
负责短板报告的存储和查询
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert

from app.infrastructure.db.models import async_session
from app.infrastructure.db.models.interview import WeaknessReportModel

logger = logging.getLogger(__name__)


class WeaknessReportRepo:
    """面试短板地图报告服务类"""

    def __init__(self):
        """初始化当前对象实例。"""
        logger.info("WeaknessReportService 初始化")

    async def save_report(
        self,
        user_id: str,
        session_id: str,
        report_data: dict,
        series_id: Optional[str] = None
    ) -> int:
        """
        保存短板地图报告（UPSERT：同一 session 只保留最新一份）

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            report_data: 报告数据 JSON
            series_id: 系列 ID（可选）

        Returns:
            int: 报告 ID
        """
        async with async_session() as db:
            try:
                now = datetime.now()
                stmt = insert(WeaknessReportModel).values(
                    user_id=user_id,
                    session_id=session_id,
                    series_id=series_id,
                    report_data=report_data,
                    created_at=now,
                    updated_at=now,
                ).on_conflict_do_update(
                    index_elements=[WeaknessReportModel.session_id],
                    set_={
                        'report_data': report_data,
                        'series_id': series_id,
                        'updated_at': now,
                    },
                ).returning(WeaknessReportModel.id)
                result_id = (await db.execute(stmt)).scalar_one()
                await db.commit()
                logger.info(f"保存短板报告: ID={result_id}, session={session_id}")
                return result_id
            except Exception as e:
                await db.rollback()
                logger.error(f"保存短板报告失败: {e}")
                raise

    async def get_report_by_session(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取指定会话的短板报告

        Args:
            session_id: 会话 ID
            user_id: 用户 ID（可选，用于权限校验）

        Returns:
            报告数据字典，不存在返回 None
        """
        async with async_session() as db:
            stmt = select(WeaknessReportModel).where(WeaknessReportModel.session_id == session_id)
            if user_id:
                stmt = stmt.where(WeaknessReportModel.user_id == user_id)
            obj = (await db.execute(stmt)).scalar_one_or_none()
            if not obj:
                return None
            return self._row_to_dict(obj)

    async def list_reports(
        self,
        user_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取用户的短板报告历史列表

        Args:
            user_id: 用户 ID
            limit: 最大返回数量

        Returns:
            报告列表
        """
        async with async_session() as db:
            stmt = (
                select(WeaknessReportModel)
                .where(WeaknessReportModel.user_id == user_id)
                .order_by(WeaknessReportModel.created_at.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [self._row_to_dict(row) for row in rows]

    async def delete_report(self, report_id: int, user_id: str) -> bool:
        """
        删除短板报告

        Args:
            report_id: 报告 ID
            user_id: 用户 ID（用于权限校验）

        Returns:
            是否删除成功
        """
        async with async_session() as db:
            try:
                result = await db.execute(
                    delete(WeaknessReportModel).where(
                        WeaknessReportModel.id == report_id,
                        WeaknessReportModel.user_id == user_id,
                    )
                )
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"删除短板报告: ID={report_id}")
                return deleted
            except Exception as e:
                await db.rollback()
                logger.error(f"删除短板报告失败: {e}")
                return False

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        report_data = row.report_data if hasattr(row, 'report_data') else row['report_data']
        created_at = row.created_at if hasattr(row, 'created_at') else row['created_at']
        updated_at = row.updated_at if hasattr(row, 'updated_at') else row['updated_at']
        return {
            'id': row.id if hasattr(row, 'id') else row['id'],
            'user_id': row.user_id if hasattr(row, 'user_id') else row['user_id'],
            'session_id': row.session_id if hasattr(row, 'session_id') else row['session_id'],
            'series_id': row.series_id if hasattr(row, 'series_id') else row['series_id'],
            'report_data': report_data,
            'created_at': created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            'updated_at': updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at
        }


# 全局单例
_weakness_report_repo = None


def get_weakness_report_repo() -> WeaknessReportRepo:
    """获取 WeaknessReportService 单例"""
    global _weakness_report_repo
    if _weakness_report_repo is None:
        _weakness_report_repo = WeaknessReportRepo()
    return _weakness_report_repo
