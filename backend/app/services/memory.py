"""
LangGraph 记忆模块

支持两种 Checkpoint 后端：
1. PostgresSaver（生产环境）- 基于 PostgreSQL 持久化图执行状态
2. MemorySaver（开发/测试）- 纯内存存储，进程重启后丢失

与 agent_memory（mem0）的关系：
- agent_memory = 长期语义记忆（用户偏好、弱点、事实）
- PostgreSQL Checkpoint = 图执行状态持久化（面试进行到哪一步、中间结果）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 全局单例 checkpointer 实例
_global_checkpointer = None
_checkpointer_type = None  # "postgres" 或 "memory"


async def get_checkpointer():
    """
    获取检查点保存器（单例模式）
    
    优先使用 PostgreSQL Checkpoint（生产环境），
    如果不可用则回退到 MemorySaver（开发/测试）。
    
    Returns:
        CheckpointSaver 实例
    """
    global _global_checkpointer, _checkpointer_type
    
    if _global_checkpointer is not None:
        return _global_checkpointer
    
    # 尝试使用 PostgreSQL Checkpoint
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from app.db.config import get_postgres_dsn
        
        dsn = get_postgres_dsn()
        _global_checkpointer = PostgresSaver.from_conn_string(dsn)
        
        # 初始化 checkpoint 表
        await _global_checkpointer.setup()
        
        _checkpointer_type = "postgres"
        logger.info("✓ LangGraph PostgreSQL Checkpoint 初始化成功")
        print("✓ LangGraph 使用 PostgreSQL Checkpoint（图状态持久化）")
        
        return _global_checkpointer
        
    except ImportError as e:
        logger.warning(f"PostgreSQL Checkpoint 不可用（缺少依赖）: {e}")
    except Exception as e:
        logger.warning(f"PostgreSQL Checkpoint 初始化失败: {e}")
    
    # 回退到 MemorySaver
    try:
        from langgraph.checkpoint.memory import MemorySaver
        
        _global_checkpointer = MemorySaver()
        _checkpointer_type = "memory"
        logger.info("✓ LangGraph MemorySaver 初始化成功（回退方案）")
        print("✓ LangGraph 使用 MemorySaver（进程重启后状态丢失）")
        
        return _global_checkpointer
        
    except Exception as e:
        logger.error(f"MemorySaver 初始化也失败: {e}")
        raise


def get_checkpointer_type() -> Optional[str]:
    """获取当前 checkpointer 类型"""
    return _checkpointer_type


# 向后兼容的别名
async def get_async_sqlite_saver(db_path: str = None):
    """向后兼容的别名"""
    return await get_checkpointer()


async def close_checkpointer():
    """关闭全局 checkpointer"""
    global _global_checkpointer, _checkpointer_type
    
    if _global_checkpointer is not None:
        # 如果是 PostgreSQL checkpointer，需要关闭连接
        if _checkpointer_type == "postgres":
            try:
                await _global_checkpointer.conn.close()
            except Exception as e:
                logger.warning(f"关闭 PostgreSQL 连接失败: {e}")
    
    _global_checkpointer = None
    _checkpointer_type = None
    logger.info("✓ Checkpointer 已关闭")


def reset_checkpointer():
    """重置全局 checkpointer（用于测试）"""
    global _global_checkpointer, _checkpointer_type
    _global_checkpointer = None
    _checkpointer_type = None
    logger.info("✓ Checkpointer 已重置")
