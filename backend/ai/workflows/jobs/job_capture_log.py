"""提供岗位日志相关后端功能。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9_-]+")


class JobCaptureTextLog:
    """定义岗位文本日志相关后端数据结构或服务组件。"""

    def __init__(self, run_id: str) -> None:
        safe_run_id = _SAFE_RUN_ID.sub("-", run_id).strip("-")[:100] or "unknown"
        root = Path(os.getenv("ARTIFACT_STORAGE_DIR", "/app/data/artifacts")).resolve()
        self.path = root / "job-capture-logs" / f"job-capture-{safe_run_id}.txt"

    async def write(self, message: str) -> None:
        """处理写入相关后端逻辑。"""
        safe_message = " ".join(str(message).replace("\x00", "").split())[:500]
        line = f"{datetime.now().isoformat(timespec='seconds')} {safe_message}\n"

        def _append() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        try:
            await asyncio.to_thread(_append)
        except OSError:
            logger.exception("[JobCapture] 无法写入后端采集日志")
