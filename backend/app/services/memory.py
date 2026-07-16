"""LangGraph checkpoint 生命周期管理。

优先使用 PostgreSQL 异步 checkpointer；初始化失败时回退到进程内
MemorySaver。长期语义记忆由 ``agent_memory`` 单独负责。
"""

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_global_checkpointer: Any = None
_checkpointer_context: Any = None
_checkpointer_type: Optional[str] = None
_init_lock: Optional[asyncio.Lock] = None
_init_lock_loop = None


def _get_init_lock() -> asyncio.Lock:
    """为当前事件循环返回初始化锁，避免并发创建多个连接池。"""
    global _init_lock, _init_lock_loop
    loop = asyncio.get_running_loop()
    if _init_lock is None or _init_lock_loop is not loop:
        _init_lock = asyncio.Lock()
        _init_lock_loop = loop
    return _init_lock


async def get_checkpointer():
    """获取进程内单例 checkpointer。"""
    global _global_checkpointer, _checkpointer_context, _checkpointer_type

    if _global_checkpointer is not None:
        return _global_checkpointer

    async with _get_init_lock():
        if _global_checkpointer is not None:
            return _global_checkpointer

        context = None
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from app.db.config import get_postgres_dsn

            context = AsyncPostgresSaver.from_conn_string(get_postgres_dsn())
            saver = await context.__aenter__()
            await saver.setup()
            _global_checkpointer = saver
            _checkpointer_context = context
            _checkpointer_type = "postgres"
            logger.info("LangGraph PostgreSQL Checkpoint 初始化成功")
            return saver
        except ImportError as exc:
            logger.warning("PostgreSQL Checkpoint 不可用（缺少依赖）: %s", exc)
        except Exception as exc:
            logger.warning("PostgreSQL Checkpoint 初始化失败，回退到内存: %s", exc)
            if context is not None:
                try:
                    await context.__aexit__(type(exc), exc, exc.__traceback__)
                except Exception:
                    logger.debug("清理失败的 Checkpoint 上下文时出错", exc_info=True)

        from langgraph.checkpoint.memory import MemorySaver

        _global_checkpointer = MemorySaver()
        _checkpointer_context = None
        _checkpointer_type = "memory"
        logger.info("LangGraph 使用 MemorySaver（进程重启后状态丢失）")
        return _global_checkpointer


def get_checkpointer_type() -> Optional[str]:
    return _checkpointer_type


async def get_async_sqlite_saver(db_path: str = None):
    """旧调用兼容入口。"""
    del db_path
    return await get_checkpointer()


async def close_checkpointer() -> None:
    """关闭 PostgreSQL checkpointer 持有的异步上下文。"""
    global _global_checkpointer, _checkpointer_context, _checkpointer_type

    context = _checkpointer_context
    _global_checkpointer = None
    _checkpointer_context = None
    _checkpointer_type = None
    if context is not None:
        try:
            await context.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("关闭 PostgreSQL Checkpoint 失败: %s", exc)
    logger.info("Checkpointer 已关闭")


def reset_checkpointer() -> None:
    """测试用同步重置；已进入的异步上下文应优先调用 close_checkpointer。"""
    global _global_checkpointer, _checkpointer_context, _checkpointer_type
    _global_checkpointer = None
    _checkpointer_context = None
    _checkpointer_type = None
