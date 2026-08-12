"""Owner-scoped memory access for agents and tools.

This module is intentionally lower-level than the HTTP memory management
workflow. It exposes only the owner-bound service factory needed by runtime
agents and tools; request/response mapping and destructive-operation safety
remain in ``ai.workflows.memory.use_cases``.
"""

from __future__ import annotations

from typing import Any

from .service import AgentMemoryService, get_agent_memory_service


async def get_owner_memory_service(
    user_id: str,
    api_config: dict[str, Any] | None = None,
) -> AgentMemoryService:
    """Return the memory service configured for one owner."""
    return await get_agent_memory_service(api_config)


__all__ = ["AgentMemoryService", "get_owner_memory_service"]
