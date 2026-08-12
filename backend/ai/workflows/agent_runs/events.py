"""AgentRun 事件查询和可重放 SSE 投影。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from app.domain.agent_runs import TERMINAL_STATUSES
from ai.runtime.agent_runs.event_stream import replay_cursor
from ai.runtime.agent_runs.service import AgentRunService, serialize_event


async def stream_event_sse(
    *,
    service: AgentRunService,
    run_id: str,
    user_id: str,
    after_sequence: int,
    last_event_id: str | None,
) -> AsyncGenerator[str, None]:
    """按 owner 范围轮询并投影 AgentRun 事件，保持数据库事件顺序和终态语义。"""
    cursor = replay_cursor(after_sequence=after_sequence, last_event_id=last_event_id)
    while True:
        events = await service.list_events(
            run_id,
            user_id,
            after_sequence=cursor,
            limit=200,
        ) or []
        for event in events:
            data: dict[str, Any] = serialize_event(event)
            cursor = event.sequence
            yield (
                f"id: {event.sequence}\n"
                f"event: {event.event_type}\n"
                f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            )
        latest = await service.get(run_id, user_id)
        if latest is None or (latest.status in TERMINAL_STATUSES and not events):
            return
        await asyncio.sleep(1)
