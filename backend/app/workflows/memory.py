"""Memory application use cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.memory import (
    MEMORY_DISABLED_MESSAGE,
    memory_history_record_to_item,
    memory_record_to_item,
)
from app.infrastructure.memory import get_agent_memory_service
from app.schemas.memory import (
    MemoryDeleteAllRequest,
    MemoryDeleteResponse,
    MemoryHistoryItem,
    MemoryHistoryResponse,
    MemoryItem,
    MemoryListResponse,
    MemorySearchResponse,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryUseCaseError(Exception):
    """Memory use-case failure."""

    message: str


class MemoryUseCases:
    """Query and mutate long-term user memories."""

    async def list_memories(self, *, user_id: str, page_size: int) -> MemoryListResponse:
        """List all memories for one user."""
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return MemoryListResponse(
                success=True,
                memories=[],
                total=0,
                user_id=user_id,
            )

        records = await memory_service.get_all(user_id=user_id, page_size=page_size)
        memories = [MemoryItem(**memory_record_to_item(record)) for record in records]
        return MemoryListResponse(
            success=True,
            memories=memories,
            total=len(memories),
            user_id=user_id,
        )

    async def search_memories(
        self,
        *,
        user_id: str,
        query: str,
        limit: int,
        memory_type: str | None,
    ) -> MemorySearchResponse:
        """Search memories for one user."""
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return MemorySearchResponse(success=True, memories=[], query=query, total=0)

        memory_types = [memory_type] if memory_type else None
        records = await memory_service.search_memories(
            user_id=user_id,
            query=query,
            limit=limit,
            memory_types=memory_types,
        )
        memories = [MemoryItem(**memory_record_to_item(record)) for record in records]
        return MemorySearchResponse(success=True, memories=memories, query=query, total=len(memories))

    async def get_history(self, *, user_id: str, memory_id: str) -> MemoryHistoryResponse:
        """Return the change history for one memory."""
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return MemoryHistoryResponse(success=True, history=[], memory_id=memory_id)

        records = await memory_service.history(user_id=user_id, memory_id=memory_id)
        history = [
            MemoryHistoryItem(**memory_history_record_to_item(record, memory_id=memory_id))
            for record in records
        ]
        return MemoryHistoryResponse(success=True, history=history, memory_id=memory_id)

    async def delete_memory(self, *, user_id: str, memory_id: str) -> MemoryDeleteResponse:
        """Delete one memory if it belongs to the user."""
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return MemoryDeleteResponse(success=False, message=MEMORY_DISABLED_MESSAGE)

        deleted = await memory_service.delete(user_id=user_id, memory_id=memory_id)
        if deleted:
            return MemoryDeleteResponse(
                success=True,
                message=f"记忆 {memory_id} 已删除",
                memory_id=memory_id,
            )
        return MemoryDeleteResponse(
            success=False,
            message=f"删除失败，记忆 {memory_id} 不存在或不属于当前用户",
        )

    async def delete_all(
        self,
        *,
        user_id: str,
        request: MemoryDeleteAllRequest,
    ) -> MemoryDeleteResponse:
        """Delete all memories for one user when explicitly confirmed."""
        if not request.confirm:
            return MemoryDeleteResponse(success=False, message="需要 confirm=true 才能清空全部记忆")

        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return MemoryDeleteResponse(success=False, message=MEMORY_DISABLED_MESSAGE)

        deleted = await memory_service.delete_all(user_id=user_id, confirm=True)
        if deleted:
            return MemoryDeleteResponse(success=True, message=f"用户 {user_id} 的全部记忆已清空")
        return MemoryDeleteResponse(success=False, message="清空记忆失败")


memory_use_cases = MemoryUseCases()
