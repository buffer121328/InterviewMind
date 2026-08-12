"""AgentRun 创建、取消和重试用例协作者。"""

from __future__ import annotations

from typing import Any, Callable

from app.domain.agent_runs import TERMINAL_STATUSES
from ai.workflows.agent_runs.contracts import DeferredExecutionResult


class AgentRunMutations:
    """承载 AgentRun 的写入生命周期，依赖 facade 提供的窄适配方法。"""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    async def create_queued_run(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
        session_id: str | None = None,
        enqueue_fn: Callable[..., Any] | None = None,
    ) -> Any:
        owner = self._owner
        if not owner._task_queue_enabled():
            lease = None
            if owner._get_agent_definition(task_type).run_gate_policy == "global":
                lease = await owner._get_run_gate().acquire()
                if lease is None:
                    raise owner.AgentRunConflict("当前仍有任务在执行，请稍后重试", status_code=409)
            try:
                try:
                    run, created = await owner._service.create_inline_or_get(
                        user_id=user_id,
                        payload=payload,
                        idempotency_key=idempotency_key,
                        task_type=task_type,
                        initial_stage=owner._first_running_stage(task_type),
                        session_id=session_id,
                    )
                except owner._task_payload_configuration_error as exc:
                    raise owner.AgentRunUnavailable(str(exc), status_code=503) from exc
                if not created:
                    if run.status in TERMINAL_STATUSES:
                        return owner.AgentRunResponse(payload=owner._serialize_run(run))
                    raise owner.AgentRunConflict("同一任务正在执行，请稍后查看任务中心", status_code=409)

                async def progress(stage: str) -> None:
                    await owner._service.mark_stage(run.id, stage)

                execution_payload = {**payload, "_agent_run_id": run.id}
                try:
                    result = await owner._run_inline_task(
                        task_type,
                        execution_payload,
                        user_id,
                        progress,
                    )
                    if isinstance(result, DeferredExecutionResult):
                        await owner._service.succeed_with_result_writer(run.id, result.persist)
                    else:
                        await owner._service.succeed(run.id, result)
                except Exception as exc:
                    await owner._service.fail(run.id, owner._safe_error_message(exc))
                    raise
                completed = await owner._service.get(run.id, user_id)
                return owner.AgentRunResponse(payload=owner._serialize_run(completed or run))
            finally:
                if lease is not None:
                    await lease.release()

        selected_enqueue = enqueue_fn or owner._enqueue_agent_run
        try:
            run, created = await owner._service.create_or_get(
                user_id=user_id,
                payload=payload,
                idempotency_key=idempotency_key,
                task_type=task_type,
                session_id=session_id,
            )
        except owner._task_payload_configuration_error as exc:
            raise owner.AgentRunUnavailable(str(exc), status_code=503) from exc
        if created or run.status == "retrying":
            success, failed = await owner._dispatch_pending_outbox(
                limit=50,
                enqueue_fn=selected_enqueue,
            )
            if failed:
                owner._log_outbox_failure("创建", success, failed)
        return owner.AgentRunResponse(payload=owner._serialize_run(run), status_code=202)

    async def cancel_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        run = await self._owner._service.cancel(run_id, user_id)
        if not run:
            raise self._owner.AgentRunConflict("任务当前不可取消", status_code=409)
        return self._owner._serialize_run(run)

    async def retry_run(self, *, run_id: str, user_id: str) -> Any:
        owner = self._owner
        run = await owner._service.retry(run_id, user_id)
        if not run:
            raise owner.AgentRunConflict("任务不可重试或已超过最大尝试次数", status_code=409)
        success, failed = await owner._dispatch_pending_outbox(
            limit=50,
            enqueue_fn=owner._enqueue_agent_run,
        )
        if failed:
            owner._log_outbox_failure("重试", success, failed)
        return owner.AgentRunResponse(payload=owner._serialize_run(run), status_code=202)
