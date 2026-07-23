"""AgentRun 主动恢复循环。"""

import asyncio
import logging
import os

from ai.runtime.agent_runs.outbox import dispatch_pending_outbox
from ai.runtime.agent_runs.service import AgentRunService, task_queue_enabled

logger = logging.getLogger(__name__)


async def run_agent_run_recovery_loop() -> None:
    """周期扫描全部用户的陈旧任务并重新投递。"""
    if not task_queue_enabled():
        return
    interval = max(10, int(os.getenv("AGENT_RUN_RECOVERY_INTERVAL_SECONDS", "60")))
    service = AgentRunService()
    while True:
        try:
            recovered = await service.recover_all_stale_runs(limit=200)
            success, failed = await dispatch_pending_outbox(limit=200)
            if recovered or success or failed:
                logger.info(
                    "主动恢复 Agent 任务: recovered=%s outbox_dispatched=%s outbox_failed=%s",
                    len(recovered),
                    success,
                    failed,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("扫描陈旧 Agent 任务失败", exc_info=True)
        await asyncio.sleep(interval)
