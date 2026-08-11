"""提供时钟相关后端功能。"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """返回当前 UTC 时间，并以无时区 datetime 形式兼容旧数据库列。"""
    return datetime.now(UTC).replace(tzinfo=None)
