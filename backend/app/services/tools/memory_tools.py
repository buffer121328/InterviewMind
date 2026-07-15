"""
记忆相关工具

默认不再兜底到全局用户，调用方必须显式传入 user_id。
"""

import logging
from typing import Any, Dict, List

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


async def search_memory(user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """搜索候选人的长期记忆。"""
    try:
        from app.services.agent_memory.service import get_agent_memory_service

        service = await get_agent_memory_service()
        if not service.is_enabled:
            return [{"message": "记忆服务未启用"}]

        return await service.search_memories(
            user_id=user_id,
            query=query,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        return []


def make_memory_tools(user_id: str) -> List[Any]:
    """构造绑定用户上下文的记忆工具集合。"""

    @tool
    async def search_memory(query: str) -> List[Dict[str, Any]]:
        """搜索候选人的长期记忆信息。"""
        return await globals()["search_memory"](user_id=user_id, query=query)

    return [search_memory]
