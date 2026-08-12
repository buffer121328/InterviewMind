"""面试聊天的可选记忆读写协作。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def write_memory_background(
    thread_id: str,
    user_message: str,
    ai_response_content: str,
    inputs: dict[str, Any],
    user_id: str,
    api_config: dict[str, Any] | None = None,
) -> None:
    """后台写入长期记忆；失败只记录脱敏错误，不阻断主流。"""
    try:
        from ai.memory import get_agent_memory_service, should_skip_write
        from ai.memory.filters import extract_memory_type_hint
        from ai.runtime.execution.background import create_background_task

        if should_skip_write(user_message, ai_response_content):
            return
        memory_service = await get_agent_memory_service(api_config)
        if not memory_service.is_enabled:
            return
        memory_type_hint = extract_memory_type_hint(user_message)
        metadata: dict[str, Any] = {
            "session_id": thread_id,
            "round_index": inputs.get("round_index", 1),
            "round_type": inputs.get("round_type", "tech_initial"),
        }
        if memory_type_hint:
            metadata["memory_type_hint"] = memory_type_hint
        create_background_task(
            memory_service.add_interaction(
                user_id=user_id,
                session_id=thread_id,
                user_message=user_message,
                assistant_message=ai_response_content,
                metadata=metadata,
            ),
            name=f"memory-write:{thread_id}",
        )
        logger.debug("已触发后台记忆写入: user_id=%s", user_id)
    except Exception as exc:  # noqa: BLE001 - optional memory writes fail open.
        logger.warning("后台记忆写入失败: %s", exc)


async def get_memory_context(
    user_id: str,
    query: str,
    memory_types: list[str] | None = None,
    api_config: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """获取长期记忆上下文；记忆服务不可用时 fail open。"""
    try:
        from ai.memory import format_memory_context, get_agent_memory_service

        memory_service = await get_agent_memory_service(api_config)
        if not memory_service.is_enabled:
            return "", []
        memories = await memory_service.search_memories(
            user_id=user_id,
            query=query,
            memory_types=memory_types,
        )
        if not memories:
            return "", []
        return format_memory_context(memories), memories
    except Exception as exc:  # noqa: BLE001 - optional memory lookup fails open.
        logger.warning("获取记忆上下文失败: %s", exc)
        return "", []
