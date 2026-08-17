"""AgentRun 创建、取消和重试用例协作者。"""

from __future__ import annotations

from typing import Any, Callable

from ai.runtime.agent_runs.outbox import dispatch_pending_outbox
from ai.runtime.agent_runs.service import first_running_stage, serialize_run, task_queue_enabled
from ai.runtime.execution.gate import get_run_gate
from ai.workflows.agent_runs.contracts import DeferredExecutionResult
from ai.workflows.agent_runs.queue.submission import enqueue_agent_run
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import TERMINAL_STATUSES
from app.security.payload_crypto import TaskPayloadConfigurationError
from app.security.security import safe_error_message


class AgentRunMutations:
    """承载 AgentRun 的写入生命周期；服务函数直连，facade 提供状态与类型。"""

    def __init__(self, owner: Any) -> None:
        """绑定 facade 以复用其运行服务与响应/错误类型。

        Args:
            owner: AgentRunUseCases 实例，经其访问 _service、AgentRunResponse 等共享协作者。
        """
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
        """创建队列或 inline 运行：队列关闭时走同步运行门与内联执行。

        Args:
            task_type: 任务类型键，用于解析 Agent 定义。
            payload: 任务载荷，运行时注入 `_agent_run_id` 后传给执行器。
            user_id: 运行归属用户。
            idempotency_key: 幂等键，用于复用已存在的运行。
            session_id: 关联会话标识，可选。
            enqueue_fn: 自定义入队函数，缺省使用 facade 默认 Outbox 投递。
        """
        owner = self._owner
        if not task_queue_enabled():
            lease = None
            if get_agent_definition(task_type).run_gate_policy == "global":
                lease = await get_run_gate().acquire()
                if lease is None:
                    raise owner.AgentRunConflict("当前仍有任务在执行，请稍后重试", status_code=409)
            try:
                try:
                    run, created = await owner._service.create_inline_or_get(
                        user_id=user_id,
                        payload=payload,
                        idempotency_key=idempotency_key,
                        task_type=task_type,
                        initial_stage=first_running_stage(task_type),
                        session_id=session_id,
                    )
                except TaskPayloadConfigurationError as exc:
                    raise owner.AgentRunUnavailable(str(exc), status_code=503) from exc
                if not created:
                    if run.status in TERMINAL_STATUSES:
                        return owner.AgentRunResponse(body=serialize_run(run))
                    raise owner.AgentRunConflict("同一任务正在执行，请稍后查看任务中心", status_code=409)

                    """执行 progress 操作。"""
                async def progress(stage: str) -> None:
                    """progress 操作。

                    Args:
                        stage: 阶段标识。
                    """
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
                    await owner._service.fail(run.id, safe_error_message(exc))
                    raise
                completed = await owner._service.get(run.id, user_id)
                return owner.AgentRunResponse(body=serialize_run(completed or run))
            finally:
                if lease is not None:
                    await lease.release()

        selected_enqueue = enqueue_fn or enqueue_agent_run
        try:
            run, created = await owner._service.create_or_get(
                user_id=user_id,
                payload=payload,
                idempotency_key=idempotency_key,
                task_type=task_type,
                session_id=session_id,
            )
        except TaskPayloadConfigurationError as exc:
            raise owner.AgentRunUnavailable(str(exc), status_code=503) from exc
        if created or run.status == "retrying":
            success, failed = await dispatch_pending_outbox(
                limit=50,
                enqueue_fn=selected_enqueue,
            )
            if failed:
                owner._log_outbox_failure("创建", success, failed)
        return owner.AgentRunResponse(body=serialize_run(run), status_code=202)

    async def cancel_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """取消当前 owner 可取消的运行；不可取消时抛出冲突错误。

        Args:
            run_id: 目标 AgentRun 标识。
            user_id: 运行归属用户，用于 owner 边界校验。
        """
        run = await self._owner._service.cancel(run_id, user_id)
        if not run:
            raise self._owner.AgentRunConflict("任务当前不可取消", status_code=409)
        return serialize_run(run)

    async def retry_run(self, *, run_id: str, user_id: str) -> Any:
        """重试当前 owner 可重试的运行，并即时投递待处理的 Outbox 消息。

        Args:
            run_id: 目标 AgentRun 标识。
            user_id: 运行归属用户，用于 owner 边界校验。
        """
        owner = self._owner
        run = await owner._service.retry(run_id, user_id)
        if not run:
            raise owner.AgentRunConflict("任务不可重试或已超过最大尝试次数", status_code=409)
        success, failed = await dispatch_pending_outbox(
            limit=50,
            enqueue_fn=enqueue_agent_run,
        )
        if failed:
            owner._log_outbox_failure("重试", success, failed)
        return owner.AgentRunResponse(body=serialize_run(run), status_code=202)
