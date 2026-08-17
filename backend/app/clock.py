"""提供持久化安全的 UTC 时钟与 API 时间戳工具。"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """返回当前 UTC 时间的 naive datetime，供旧数据库列使用。"""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_isoformat(value: datetime | None) -> str | None:
    """将持久化的 UTC 时间序列化为带显式 UTC 偏移的 ISO 字符串。

    旧数据库列刻意存 naive UTC 值；API 返回时必须补偏移，
    否则浏览器会把无时区的 ISO 字符串当成本地时间解析。

    Args:
        value: 已持久化的时间戳；naive 值按 UTC 解释，None 直接返回 None。
    """
    if value is None:
        return None
    # naive 值补 UTC 时区，带时区值统一换算到 UTC。
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat().replace('+00:00', 'Z')
