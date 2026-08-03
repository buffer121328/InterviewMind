"""Memory application use cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ai.memory import get_agent_memory_service
from ai.workflows.model_credentials import ModelCredentialUseCases
from app.domain.memory import (
    MEMORY_DISABLED_MESSAGE,
    canonicalize_memory_records,
    memory_history_record_to_item,
    memory_record_to_item,
)
from app.schemas.memory import (
    MemoryCleanupRequest,
    MemoryCleanupResponse,
    MemoryConsolidateRequest,
    MemoryConsolidationResponse,
    MemoryCreateRequest,
    MemoryDeleteAllRequest,
    MemoryDeleteResponse,
    MemoryHistoryItem,
    MemoryHistoryResponse,
    MemoryItem,
    MemoryListResponse,
    MemorySearchResponse,
    MemoryUpdateRequest,
    MemoryWriteResponse,
)
from app.security.model_credentials import ModelCredentialError, get_model_credential_store

logger = logging.getLogger(__name__)


async def get_owner_memory_service(user_id: str, api_config: dict | None):
    """Resolve request config first, then owner-scoped Redis channel bindings."""

    resolved_config = api_config
    if resolved_config is None:
        try:
            resolved_config = await ModelCredentialUseCases(
                get_model_credential_store()
            ).resolve_memory_api_config(user_id)
        except ModelCredentialError as exc:
            logger.warning("无法恢复用户 mem0 通道配置: %s", type(exc).__name__)
    return await get_agent_memory_service(resolved_config)


@dataclass(slots=True)
class MemoryUseCaseError(Exception):
    """Memory use-case failure."""

    message: str


class MemoryUseCases:
    """Query and mutate long-term user memories."""

    async def list_memories(
        self,
        *,
        user_id: str,
        page_size: int,
        api_config: dict | None = None,
    ) -> MemoryListResponse:
        """List memories using request-scoped model credentials without persisting them."""
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryListResponse(
                success=True,
                memories=[],
                total=0,
                user_id=user_id,
                message=MEMORY_DISABLED_MESSAGE,
            )

        records = await memory_service.get_all(user_id=user_id, page_size=page_size)
        canonical_records = canonicalize_memory_records(records)
        memories = [MemoryItem(**memory_record_to_item(record)) for record in canonical_records]
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
        api_config: dict | None = None,
    ) -> MemorySearchResponse:
        """Search memories using request-scoped model credentials without persisting them."""
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemorySearchResponse(
                success=True,
                memories=[],
                query=query,
                total=0,
                message=MEMORY_DISABLED_MESSAGE,
            )

        memory_types = [memory_type] if memory_type else None
        records = await memory_service.search_memories(
            user_id=user_id,
            query=query,
            limit=limit,
            memory_types=memory_types,
        )
        canonical_records = canonicalize_memory_records(records)
        memories = [MemoryItem(**memory_record_to_item(record)) for record in canonical_records]
        return MemorySearchResponse(success=True, memories=memories, query=query, total=len(memories))

    async def get_history(
        self,
        *,
        user_id: str,
        memory_id: str,
        api_config: dict | None = None,
    ) -> MemoryHistoryResponse:
        """Return memory history through the same request-scoped mem0 client."""
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryHistoryResponse(
                success=True,
                history=[],
                memory_id=memory_id,
                message=MEMORY_DISABLED_MESSAGE,
            )

        records = await memory_service.history(user_id=user_id, memory_id=memory_id)
        history = [
            MemoryHistoryItem(**memory_history_record_to_item(record, memory_id=memory_id))
            for record in records
        ]
        return MemoryHistoryResponse(success=True, history=history, memory_id=memory_id)

    async def consolidate_memories(
        self,
        *,
        user_id: str,
        request: MemoryConsolidateRequest,
    ) -> MemoryConsolidationResponse:
        """Preview or explicitly apply owner-scoped historical memory consolidation."""
        if not request.dry_run and not request.confirm:
            raise MemoryUseCaseError("实际整合长期记忆前必须显式 confirm=true")

        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryConsolidationResponse(
                success=False,
                dry_run=request.dry_run,
                total_before=0,
                total_after=0,
                message=MEMORY_DISABLED_MESSAGE,
            )

        result = await memory_service.consolidate_existing_memories(
            user_id=user_id,
            dry_run=request.dry_run,
            max_memories=request.max_memories,
        )
        return MemoryConsolidationResponse(success=True, **result)

    async def cleanup_memories(
        self,
        *,
        user_id: str,
        request: MemoryCleanupRequest,
    ) -> MemoryCleanupResponse:
        """Preview, mark, or delete only memories eligible under gradual decay."""

        if not request.dry_run and not request.confirm:
            raise MemoryUseCaseError("应用长期记忆清理前必须显式 confirm=true")
        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryCleanupResponse(
                success=False,
                dry_run=request.dry_run,
                total_before=0,
                total_after=0,
                message=MEMORY_DISABLED_MESSAGE,
            )
        result = await memory_service.cleanup_stale_memories(
            user_id=user_id,
            dry_run=request.dry_run,
            max_memories=request.max_memories,
        )
        return MemoryCleanupResponse(success=True, **result)

    async def add_memory(
        self,
        *,
        user_id: str,
        request: MemoryCreateRequest,
    ) -> MemoryWriteResponse:
        """Create a raw user-authored memory without automatic extraction."""
        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryWriteResponse(success=False, message=MEMORY_DISABLED_MESSAGE)
        result = await memory_service.add_memory(
            user_id=user_id,
            content=request.content,
            memory_type=request.memory_type,
        )
        memory_id = _memory_id_from_result(result)
        if not memory_id:
            return MemoryWriteResponse(success=False, message="添加记忆失败")
        return MemoryWriteResponse(success=True, message="长期记忆已添加", memory_id=memory_id)

    async def update_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        request: MemoryUpdateRequest,
    ) -> MemoryWriteResponse:
        """Replace one owner-scoped memory after the service validates ownership."""
        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryWriteResponse(success=False, message=MEMORY_DISABLED_MESSAGE)
        result = await memory_service.update_memory(
            user_id=user_id,
            memory_id=memory_id,
            content=request.content,
        )
        if result is None:
            return MemoryWriteResponse(success=False, message="更新失败，记忆不存在或不属于当前用户")
        return MemoryWriteResponse(success=True, message="长期记忆已更新", memory_id=memory_id)

    async def delete_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        api_config: dict | None = None,
    ) -> MemoryDeleteResponse:
        """Delete one owner-scoped memory through the request-scoped mem0 client."""
        memory_service = await get_owner_memory_service(user_id, api_config)
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

        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryDeleteResponse(success=False, message=MEMORY_DISABLED_MESSAGE)

        deleted = await memory_service.delete_all(user_id=user_id, confirm=True)
        if deleted:
            return MemoryDeleteResponse(success=True, message=f"用户 {user_id} 的全部记忆已清空")
        return MemoryDeleteResponse(success=False, message="清空记忆失败")


memory_use_cases = MemoryUseCases()


def _memory_id_from_result(result: object) -> str | None:
    """Extract the first mem0 result id across its supported response shapes."""
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("id"), str):
        return result["id"]
    results = result.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        memory_id = results[0].get("id")
        return memory_id if isinstance(memory_id, str) else None
    return None
