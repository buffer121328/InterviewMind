"""
AgentMemoryService - mem0 长期记忆服务

对业务暴露统一接口，隐藏 mem0 返回结构差异。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import get_mem0_config, get_mem0_retention_days, get_mem0_search_limit, is_mem0_background_write

logger = logging.getLogger(__name__)

# 全局单例
_agent_memory_service: Optional["AgentMemoryService"] = None


def _retention_metadata() -> dict:
    """执行 `_retention_metadata` 相关逻辑。"""
    retention_days = get_mem0_retention_days()
    expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)
    return {
        "retention_days": retention_days,
        "expires_at": expires_at.isoformat(),
        "delete_sync_policy": "mem0_delete_by_user_or_expiry",
    }


class AgentMemoryService:
    """
    mem0 长期记忆服务

    提供统一的记忆管理接口，支持：
    - search_memories: 语义检索长期记忆
    - add_interaction: 添加对话交互记忆
    - add_summary_memory: 添加面试总结记忆
    - get_all: 获取用户全部记忆
    - history: 获取记忆变更历史
    - delete: 删除记忆
    """

    def __init__(self, config: dict):
        """
        初始化 mem0 客户端

        Args:
            config: mem0 配置字典
        """
        self._config = config
        self._memory = None
        self._enabled = config is not None

    async def initialize(self):
        """异步初始化 mem0 客户端"""
        if not self._enabled:
            logger.info("AgentMemoryService 已禁用")
            return

        try:
            from mem0 import Memory

            # mem0 的 Memory 是同步的，但我们在异步方法中使用
            # 用配置信息创建一个 mem0 Memory 对象，这是工厂方法
            self._memory = await asyncio.to_thread(
                Memory.from_config,
                self._config
            )
            logger.info("✓ AgentMemoryService 初始化成功")
        except Exception as e:
            logger.error(f"✗ AgentMemoryService 初始化失败: {e}")
            self._enabled = False
            self._memory = None

    @property
    # property将一个方法转换成属性，让你可以像访问属性一样调用方法
    def is_enabled(self) -> bool:
        """检查服务是否启用"""
        return self._enabled and self._memory is not None

    async def search_memories(
        self,
        *,
        user_id: str,
        query: str,
        limit: Optional[int] = None,
        memory_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        检索长期记忆

        Args:
            user_id: 用户 ID
            query: 搜索查询
            limit: 返回结果数量限制
            memory_types: 过滤的记忆类型列表

        Returns:
            list[dict]: 记忆列表，每条包含 id, memory, metadata 等
        """
        if not self.is_enabled:
            return []

        try:
            search_limit = limit or get_mem0_search_limit()

            # mem0 的 search 是同步的，放到线程池执行
            result = await asyncio.to_thread(
                self._memory.search,
                query=query,
                user_id=user_id,
                limit=search_limit,
            )

            # mem0 返回格式可能是 {"results": [...]} 或直接是列表
            memories = []
            if isinstance(result, dict):
                memories = result.get("results", [])
            elif isinstance(result, list):
                memories = result

            # 按 memory_types 过滤
            if memory_types:
                memories = [
                    m for m in memories
                    if m.get("metadata", {}).get("memory_type") in memory_types
                ]

            return memories

        except Exception as e:
            logger.error(f"搜索记忆失败: {e}")
            return []

    async def add_interaction(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        添加对话交互记忆

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            user_message: 用户消息
            assistant_message: 助手回复
            metadata: 额外元数据

        Returns:
            dict: mem0 返回的结果，失败返回 None
        """
        if not self.is_enabled:
            return None

        try:
            # 构造消息格式
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]

            # 构造 metadata
            meta = {
                "project": "agent_interview",
                "source": "chat_turn",
                "session_id": session_id,
                **_retention_metadata(),
            }
            if metadata:
                meta.update(metadata)

            # mem0 的 add 是同步的
            result = await asyncio.to_thread(
                self._memory.add,
                messages=messages,
                user_id=user_id,
                metadata=meta,
            )

            logger.debug(f"添加交互记忆成功: user_id={user_id}")
            return result

        except Exception as e:
            logger.error(f"添加交互记忆失败: {e}")
            return None

    async def add_summary_memory(
        self,
        *,
        user_id: str,
        session_id: str,
        content: str,
        memory_type: str,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        添加面试总结记忆（短板、练习目标等）

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            content: 记忆内容
            memory_type: 记忆类型 (weakness, practice_goal, etc.)
            metadata: 额外元数据

        Returns:
            dict: mem0 返回的结果，失败返回 None
        """
        if not self.is_enabled:
            return None

        try:
            meta = {
                "project": "agent_interview",
                "memory_type": memory_type,
                "source": "interview_summary",
                "session_id": session_id,
                **_retention_metadata(),
            }
            if metadata:
                meta.update(metadata)

            result = await asyncio.to_thread(
                self._memory.add,
                content,
                user_id=user_id,
                metadata=meta,
            )

            logger.info(f"添加总结记忆成功: user_id={user_id}, type={memory_type}")
            return result

        except Exception as e:
            logger.error(f"添加总结记忆失败: {e}")
            return None

    async def get_all(
        self,
        *,
        user_id: str,
        page_size: int = 100,
    ) -> list[dict]:
        """
        获取用户全部记忆

        Args:
            user_id: 用户 ID
            page_size: 每页数量

        Returns:
            list[dict]: 记忆列表
        """
        if not self.is_enabled:
            return []

        try:
            result = await asyncio.to_thread(
                self._memory.get_all,
                user_id=user_id,
                page_size=page_size,
            )

            # 处理返回格式
            if isinstance(result, dict):
                return result.get("results", [])
            elif isinstance(result, list):
                return result
            return []

        except Exception as e:
            logger.error(f"获取全部记忆失败: {e}")
            return []

    async def history(
        self,
        *,
        user_id: str,
        memory_id: str,
    ) -> list[dict]:
        """
        获取记忆变更历史

        Args:
            user_id: 用户 ID（用于校验归属）
            memory_id: 记忆 ID

        Returns:
            list[dict]: 变更历史列表
        """
        if not self.is_enabled:
            return []

        try:
            # 先校验记忆归属
            all_memories = await self.get_all(user_id=user_id)
            memory_ids = [m.get("id") for m in all_memories]

            if memory_id not in memory_ids:
                logger.warning(f"记忆 {memory_id} 不属于用户 {user_id}")
                return []

            result = await asyncio.to_thread(
                self._memory.history,
                memory_id=memory_id,
            )

            if isinstance(result, list):
                return result
            return []

        except Exception as e:
            logger.error(f"获取记忆历史失败: {e}")
            return []

    async def delete(
        self,
        *,
        user_id: str,
        memory_id: str,
    ) -> bool:
        """
        删除记忆

        Args:
            user_id: 用户 ID（用于校验归属）
            memory_id: 记忆 ID

        Returns:
            bool: 是否删除成功
        """
        if not self.is_enabled:
            return False

        try:
            # 先校验记忆归属
            all_memories = await self.get_all(user_id=user_id)
            memory_ids = [m.get("id") for m in all_memories]

            if memory_id not in memory_ids:
                logger.warning(f"记忆 {memory_id} 不属于用户 {user_id}")
                return False

            await asyncio.to_thread(
                self._memory.delete,
                memory_id=memory_id,
            )

            logger.info(f"删除记忆成功: memory_id={memory_id}, delete_sync_policy=mem0_delete_by_user_or_expiry")
            return True

        except Exception as e:
            logger.error(f"删除记忆失败: {e}")
            return False

    async def delete_all(
        self,
        *,
        user_id: str,
        confirm: bool = False,
    ) -> bool:
        """
        清空用户全部记忆

        Args:
            user_id: 用户 ID
            confirm: 必须为 True 才执行删除

        Returns:
            bool: 是否删除成功
        """
        if not confirm:
            logger.warning("delete_all 需要 confirm=True")
            return False

        if not self.is_enabled:
            return False

        try:
            await asyncio.to_thread(
                self._memory.delete_all,
                user_id=user_id,
            )

            logger.info(f"清空用户记忆成功: user_id={user_id}, delete_sync_policy=mem0_delete_all_by_user")
            return True

        except Exception as e:
            logger.error(f"清空用户记忆失败: {e}")
            return False


async def get_agent_memory_service() -> AgentMemoryService:
    """
    获取 AgentMemoryService 单例

    Returns:
        AgentMemoryService: 记忆服务实例
    """
    global _agent_memory_service

    if _agent_memory_service is None:
        config = get_mem0_config()
        _agent_memory_service = AgentMemoryService(config)
        await _agent_memory_service.initialize()

    return _agent_memory_service


async def close_agent_memory_service():
    """关闭全局 AgentMemoryService"""
    global _agent_memory_service
    _agent_memory_service = None
    logger.info("✓ AgentMemoryService 已关闭")
