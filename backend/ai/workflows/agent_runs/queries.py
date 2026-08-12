"""AgentRun 查询用例协作者。"""

from __future__ import annotations

from typing import Any


class AgentRunQueries:
    """承载 owner-scoped 查询和列表投影；不拥有创建、取消或重试副作用。"""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    async def list_runs(
        self,
        *,
        user_id: str,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if task_type:
            self._owner._validate_task_type(task_type)
        await self._owner._recover_and_dispatch(user_id, limit=200)
        runs, total = await self._owner._service.list_runs(
            user_id,
            status=status,
            task_type=task_type,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "runs": [self._owner._serialize_run(run) for run in runs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def summarize_runs(self, *, user_id: str) -> dict[str, int]:
        return await self._owner._service.summarize_runs(user_id)

    async def list_grouped_runs(
        self,
        *,
        user_id: str,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        if task_type:
            self._owner._validate_task_type(task_type)
        await self._owner._recover_and_dispatch(user_id, limit=200)
        session_groups, other_runs, session_total = await self._owner._service.list_grouped_runs(
            user_id,
            status=status,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
        groups = [
            {
                "group_type": "session",
                "session_id": session_id,
                "session_title": getattr(runs[0], "session_title", None) if runs else None,
                "runs": [self._owner._serialize_run(run) for run in runs],
            }
            for session_id, runs in session_groups
        ]
        if other_runs:
            groups.append(
                {
                    "group_type": "other",
                    "session_id": None,
                    "session_title": None,
                    "runs": [self._owner._serialize_run(run) for run in other_runs],
                }
            )
        return {
            "success": True,
            "groups": groups,
            "total": session_total,
            "session_total": session_total,
            "other_total": len(other_runs),
            "limit": limit,
            "offset": offset,
        }

    async def get_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        run = await self._owner._service.get(run_id, user_id)
        if not run:
            raise self._owner.AgentRunNotFound("任务不存在或无权访问", status_code=404)
        return self._owner._serialize_run(run)

    async def list_events(
        self,
        *,
        run_id: str,
        user_id: str,
        after_sequence: int,
        limit: int,
    ) -> dict[str, Any]:
        events = await self._owner._service.list_events(
            run_id,
            user_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        if events is None:
            raise self._owner.AgentRunNotFound("任务不存在或无权访问", status_code=404)
        return {"events": [self._owner._serialize_event(event) for event in events]}
