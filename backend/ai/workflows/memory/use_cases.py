"""记忆管理用例：列表/搜索/历史/合并/清理/增删改，并封装记忆服务不可用时的降级提示。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ai.memory.service import get_agent_memory_service
from app.domain.memory import (
    MEMORY_DISABLED_MESSAGE,
    MemorySource,
    canonicalize_memory_records,
    filter_memory_records_by_source,
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

logger = logging.getLogger(__name__)


async def get_owner_memory_service(user_id: str, api_config: dict | None):
    """获取用户记忆服务；HTTP 管理用例保留请求级配置适配。

    Args:
        user_id: 当前用户标识（当前实现未使用）。
        api_config: 请求级模型配置（可选）。
    """

    del user_id
    return await get_agent_memory_service(api_config)


def _memory_unavailable_message(memory_service) -> str:
    """按记忆服务的就绪状态类别返回用户可读的不可用提示。

    Args:
        memory_service: 记忆服务实例（用于读取就绪状态类别）。
    """
    category = getattr(memory_service, "readiness_category", "initialization_failed")
    return {
        "model_channels_missing": MEMORY_DISABLED_MESSAGE,
        "database_authentication_failed": "mem0 数据库认证失败，请检查 DATABASE_URL 或 MEM0_PGVECTOR_URL",
        "database_unavailable": "mem0 数据库连接不可用，请检查数据库运行状态",
        "vector_schema_error": "mem0 向量表结构未就绪，请检查 pgvector 与向量维度",
        "not_initialized": "mem0 尚未初始化，请稍后重试",
    }.get(category, "mem0 初始化失败，请检查服务配置")


@dataclass(slots=True)
class MemoryUseCaseError(Exception):
    """记忆用例业务异常。"""

    message: str  # 面向用户的可读错误信息


class MemoryUseCases:
    """记忆管理用例：封装记忆服务的列表、搜索、历史与生命周期操作。"""

    async def list_memories(
        self,
        *,
        user_id: str,
        page_size: int,
        sources: list[MemorySource] | None = None,
        api_config: dict | None = None,
    ) -> MemoryListResponse:
        """分页列出当前用户记忆，并按来源过滤；服务不可用时返回空结果。

        Args:
            user_id: 当前用户标识。
            page_size: 单页返回数量上限。
            sources: 需要过滤的记忆来源（可选，None 表示不过滤）。
            api_config: 请求级模型配置（可选）。
        """
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryListResponse(
                success=True,
                memories=[],
                total=0,
                user_id=user_id,
                message=_memory_unavailable_message(memory_service),
            )

        records = await memory_service.get_all(user_id=user_id, page_size=page_size)
        canonical_records = canonicalize_memory_records(records)
        source_filtered_records = filter_memory_records_by_source(canonical_records, sources)
        memories = [MemoryItem(**memory_record_to_item(record)) for record in source_filtered_records]
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
        sources: list[MemorySource] | None = None,
        api_config: dict | None = None,
    ) -> MemorySearchResponse:
        """按关键词与记忆类型搜索当前用户记忆，并按来源过滤。

        Args:
            user_id: 当前用户标识。
            query: 搜索关键词。
            limit: 返回数量上限。
            memory_type: 记忆类型过滤（可选）。
            sources: 需要过滤的记忆来源（可选，None 表示不过滤）。
            api_config: 请求级模型配置（可选）。
        """
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemorySearchResponse(
                success=True,
                memories=[],
                query=query,
                total=0,
                message=_memory_unavailable_message(memory_service),
            )

        memory_types = [memory_type] if memory_type else None
        records = await memory_service.search_memories(
            user_id=user_id,
            query=query,
            limit=limit,
            memory_types=memory_types,
        )
        canonical_records = canonicalize_memory_records(records)
        source_filtered_records = filter_memory_records_by_source(canonical_records, sources)
        memories = [MemoryItem(**memory_record_to_item(record)) for record in source_filtered_records]
        return MemorySearchResponse(success=True, memories=memories, query=query, total=len(memories))

    async def get_history(
        self,
        *,
        user_id: str,
        memory_id: str,
        api_config: dict | None = None,
    ) -> MemoryHistoryResponse:
        """获取单条记忆的变更历史。

        Args:
            user_id: 当前用户标识。
            memory_id: 记忆标识。
            api_config: 请求级模型配置（可选）。
        """
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryHistoryResponse(
                success=True,
                history=[],
                memory_id=memory_id,
                message=_memory_unavailable_message(memory_service),
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
        """整合/合并长期记忆；支持 dry_run 预览，实际写入前必须显式确认。

        Args:
            user_id: 当前用户标识。
            request: 记忆合并请求。
        """
        # 安全关卡：非 dry_run 时必须显式 confirm，防止误操作改写长期记忆
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
                message=_memory_unavailable_message(memory_service),
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
        """清理过期长期记忆；支持 dry_run 预览，实际清理前必须显式确认。

        Args:
            user_id: 当前用户标识。
            request: 记忆清理请求。
        """

        # 安全关卡：非 dry_run 时必须显式 confirm，防止误删长期记忆
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
                message=_memory_unavailable_message(memory_service),
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
        """为当前用户新增一条长期记忆。

        Args:
            user_id: 用户 ID，所有者范围限定。
            request: 请求对象。
        """
        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryWriteResponse(success=False, message=_memory_unavailable_message(memory_service))
        result = await memory_service.add_memory(
            user_id=user_id,
            content=request.content,
            memory_type=request.memory_type,
            memory_source=(request.memory_source.value if request.memory_source else None),
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
        """更新当前用户指定记忆的内容。

        Args:
            user_id: 用户 ID，所有者范围限定。
            memory_id: memory 的 ID。
            request: 请求对象。
        """
        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryWriteResponse(success=False, message=_memory_unavailable_message(memory_service))
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
        """删除当前用户指定的一条记忆。

        Args:
            user_id: 用户 ID，所有者范围限定。
            memory_id: memory 的 ID。
            api_config: 前端请求携带的模型通道配置。
        """
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryDeleteResponse(success=False, message=_memory_unavailable_message(memory_service))

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
        """在 confirm 为 true 时清空当前用户的全部记忆。

        Args:
            user_id: 用户 ID，所有者范围限定。
            request: 请求对象。
        """
        if not request.confirm:
            return MemoryDeleteResponse(success=False, message="需要 confirm=true 才能清空全部记忆")

        api_config = request.api_config.model_dump() if request.api_config else None
        memory_service = await get_owner_memory_service(user_id, api_config)
        if not memory_service.is_enabled:
            return MemoryDeleteResponse(success=False, message=_memory_unavailable_message(memory_service))

        deleted = await memory_service.delete_all(user_id=user_id, confirm=True)
        if deleted:
            return MemoryDeleteResponse(success=True, message=f"用户 {user_id} 的全部记忆已清空")
        return MemoryDeleteResponse(success=False, message="清空记忆失败")


memory_use_cases = MemoryUseCases()


def _memory_id_from_result(result: object) -> str | None:
    """从记忆服务结果中提取记忆 ID（兼容 id 字段或 results[0].id）。

    Args:
        result: 结果对象。
    """
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("id"), str):
        return result["id"]
    results = result.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        memory_id = results[0].get("id")
        return memory_id if isinstance(memory_id, str) else None
    return None
