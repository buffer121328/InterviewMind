from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.runtime.agent_runs.governance import _sanitize_governance_payload
from ai.runtime.agent_runs.serialization import _first_token_duration_ms
from app.db.models import (
    AgentRunEventModel,
    AgentRunModel,
    ModelMetricEventModel,
)


class AgentRunEventsMixin:
    async def _append_event(
            self,
            session: AsyncSession,
            run: AgentRunModel,
            event_type: str,
            payload: dict[str, Any] | None = None,
        ) -> AgentRunEventModel:
            """记录一条 AgentRun 事件到数据库。"""

            sequence = int(await session.scalar(
                select(func.coalesce(func.max(AgentRunEventModel.sequence), 0)).where(AgentRunEventModel.run_id == run.id)
            ) or 0) + 1     # 计算新事件的 sequence（序列号），即当前已有事件的序号最大值 + 1。
            event = AgentRunEventModel(
                run_id=run.id,
                sequence=sequence,
                event_type=event_type,
                stage=run.stage,
                payload=payload or {},
                schema_version=1,
                created_at=self._runtime_now(),
            )
            session.add(event)
            return event

    async def record_governance_event(
            self,
            run_id: str,
            *,
            user_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
        ) -> bool:
            """持久化工具或 Guardrails 的最小审计事件。

            只接收摘要载荷，避免把原始简历、JD、模型输出或密钥写入可重放事件流。
            不存在的 run、跨用户 run 或非治理事件会被拒绝，调用方可将审计失败视作
            非业务失败，以免影响已完成的工具动作。
            """

            if not event_type.startswith(("tool.", "guardrail.")):
                raise ValueError("governance event_type must start with tool. or guardrail.")

            async with self._runtime_unit_of_work() as uow:
                session = uow.db
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run or run.user_id != user_id:
                    return False

                await self._append_event(
                    session,
                    run,
                    event_type,
                    _sanitize_governance_payload(payload or {}),
                )
                run.updated_at = self._runtime_now()
            return True

    async def record_observation(
            self,
            run_id: str,
            *,
            observation_id: str | None = None,
            trace_id: str | None = None,
            model_events: list[dict[str, Any]] | None = None,
        ) -> None:
            """记录观测相关后端逻辑。"""
            async with self._runtime_unit_of_work() as uow:
                session = uow.db
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run:
                    return

                if trace_id:
                    run.trace_id = trace_id
                observed_first_token = _first_token_duration_ms(model_events)
                if observed_first_token is not None:
                    existing_first_token = getattr(run, "first_token_duration_ms", None)
                    run.first_token_duration_ms = (
                        observed_first_token
                        if existing_first_token is None
                        else min(existing_first_token, observed_first_token)
                    )
                run.updated_at = self._runtime_now()
                if not model_events:
                    return
                observation_id = observation_id or trace_id or f"legacy:{run_id}"
                existing = await session.scalar(
                    select(func.count(ModelMetricEventModel.id)).where(
                        ModelMetricEventModel.run_id == run_id,
                        ModelMetricEventModel.observation_id == observation_id,
                    )
                )
                if existing:
                    return
                now = self._runtime_now()
                for event_index, event in enumerate(model_events):
                    payload = _sanitize_governance_payload(event)
                    event_type = str(payload.get("event_type") or "unknown")
                    is_degradation = (
                        event_type in {"llm.request.failed", "llm.request.skipped"}
                        or int(payload.get("fallback_index") or 0) > 0
                        or bool(payload.get("authoritative_source_truncated"))
                        or bool(payload.get("truncated_sources"))
                    )
                    session.add(ModelMetricEventModel(
                        user_id=run.user_id,
                        run_id=run.id,
                        observation_id=observation_id,
                        trace_id=trace_id,
                        event_index=event_index,
                        agent_name=str(payload.get("agent_name") or run.agent_name or "unknown"),
                        task_type=run.task_type,
                        stage=str(payload.get("stage") or run.stage)[:160],
                        event_type=event_type[:160],
                        is_degradation=is_degradation,
                        payload=payload,
                        created_at=now,
                    ))
