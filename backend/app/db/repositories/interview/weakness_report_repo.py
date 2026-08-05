"""
面试短板地图报告持久化服务
负责短板报告的存储和查询
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import async_session
from app.db.models.interview import WeaknessReportModel
from app.clock import utc_now

logger = logging.getLogger(__name__)


class WeaknessReportRepo:
    """面试短板地图报告服务类"""

    def __init__(self):
        """初始化 `WeaknessReportRepo` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
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
                now = utc_now()
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
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取指定会话的短板报告

        Args:
            session_id: 会话 ID
            user_id: 当前用户 ID，用于权限校验

        Returns:
            报告数据字典，不存在返回 None
        """
        async with async_session() as db:
            stmt = select(WeaknessReportModel).where(
                WeaknessReportModel.session_id == session_id,
                WeaknessReportModel.user_id == user_id,
            )
            obj = (await db.execute(stmt)).scalar_one_or_none()
            if not obj:
                return None
            return self._row_to_dict(obj)

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
