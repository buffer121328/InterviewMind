"""将新建满意度反馈追加到私有的按日 Markdown 改进日志。"""

from __future__ import annotations

import asyncio
import fcntl
import html
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from app.config import get_settings

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_LOG_DIRECTORY = ("feedback", "satisfaction")


class _SatisfactionFeedback(Protocol):
    """日度日志所需的已持久化反馈字段，不暴露提交者身份。"""

    id: str
    agent_type: str
    rating: int | None
    satisfied_aspects: list[str]
    dissatisfied_aspects: list[str]
    comment: str | None
    created_at: datetime


def _as_shanghai_time(value: datetime) -> datetime:
    """将数据库中的 UTC 时间（含 legacy naive 值）转换为中国标准时间。"""

    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(_SHANGHAI)


def _safe_inline_text(value: object) -> str:
    """将用户输入规范为单行 Markdown 文本，防止其改变日志结构。"""

    text = " ".join(str(value).split())
    return html.escape(text, quote=False)


def _format_aspects(values: object) -> str:
    """格式化多选反馈方面；空值使用明确占位符。"""

    if not isinstance(values, list):
        return "无"
    aspects: list[str] = []
    for value in values:
        normalized = _safe_inline_text(value)
        if normalized:
            aspects.append(normalized)
    return "、".join(aspects) if aspects else "无"


def _format_rating(value: object) -> str:
    """只输出有效星级，避免异常记录污染日报。"""

    return f"{value} / 5" if type(value) is int and 1 <= value <= 5 else "未评分"


def _format_entry(record: _SatisfactionFeedback, submitted_at: datetime) -> str:
    """格式化一条不含 user_id、任务引用或原始面试内容的日志记录。"""

    agent_type = {"interview": "面试", "resume_optimize": "简历优化"}.get(
        record.agent_type, _safe_inline_text(record.agent_type)
    )
    comment = _safe_inline_text(record.comment) if record.comment else ""
    entry = [
        f"## {submitted_at.strftime('%H:%M:%S')} CST · {agent_type}",
        f"- 反馈编号：`{_safe_inline_text(record.id)}`",
        f"- 评分：{_format_rating(record.rating)}",
        f"- 满意方面：{_format_aspects(record.satisfied_aspects)}",
        f"- 不满意方面：{_format_aspects(record.dissatisfied_aspects)}",
    ]
    if comment:
        entry.append(f"- 补充说明：{comment}")
    return "\n".join(entry) + "\n\n"


def _append_entry_sync(record: _SatisfactionFeedback, runtime_data_dir: Path) -> Path:
    """在文件锁内创建或追加日报，确保并发请求不会交错写入。"""

    submitted_at = _as_shanghai_time(record.created_at)
    log_path = runtime_data_dir.joinpath(*_LOG_DIRECTORY, f"{submitted_at:%Y-%m-%d}.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a+", encoding="utf-8") as log_file:
        fcntl.flock(log_file.fileno(), fcntl.LOCK_EX)
        try:
            log_file.seek(0, os.SEEK_END)
            if log_file.tell() == 0:
                log_file.write(
                    f"# 满意度反馈日志 — {submitted_at:%Y-%m-%d}\n\n"
                    "> 此文件由后端自动生成，按中国标准时间归档；不包含提交者身份或原始面试内容。\n\n"
                )
            log_file.write(_format_entry(record, submitted_at))
            log_file.flush()
            os.fsync(log_file.fileno())
        finally:
            fcntl.flock(log_file.fileno(), fcntl.LOCK_UN)
    return log_path


async def append_satisfaction_daily_log(
    record: _SatisfactionFeedback,
    *,
    runtime_data_dir: Path | None = None,
) -> Path:
    """将一个新建反馈写入私有日度日志，不在异步事件循环中执行文件 I/O。"""

    root = runtime_data_dir or get_settings().runtime_data_path
    return await asyncio.to_thread(_append_entry_sync, record, root)
