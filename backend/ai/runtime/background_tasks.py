"""应用级后台任务注册与清理。

用于替代裸 `asyncio.create_task`，确保任务异常有日志，并在应用关闭时尽量等待任务完成。
"""

import asyncio
import logging
from typing import Any, Coroutine, Set

logger = logging.getLogger(__name__)

_background_tasks: Set[asyncio.Task] = set()


def create_background_task(coro: Coroutine[Any, Any, Any], name: str = "background-task") -> asyncio.Task:
    """创建并跟踪后台任务。"""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _on_done(done_task: asyncio.Task) -> None:
        """执行 `_on_done` 相关逻辑。

        Args:
            done_task: 调用方传入的 `done_task` 参数。
        """
        _background_tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.info("后台任务已取消: %s", done_task.get_name())
        except Exception as exc:
            logger.error("后台任务执行失败: %s: %s", done_task.get_name(), exc, exc_info=True)

    task.add_done_callback(_on_done)
    return task


async def drain_background_tasks(timeout: float = 5.0) -> None:
    """关闭应用时等待后台任务完成，超时后取消。"""
    if not _background_tasks:
        return

    tasks = list(_background_tasks)
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    logger.info("后台任务清理完成: done=%s, cancelled=%s", len(done), len(pending))
