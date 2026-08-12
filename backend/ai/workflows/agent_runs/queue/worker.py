"""Dramatiq Worker：领取、执行、心跳、协作取消并完成 AgentRun。"""

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

from ai.runtime.agent_runs.service import AgentRunService
from ai.workflows.agent_runs.catalog import get_queued_driver
from app.domain.agent_definitions import get_agent_definition

broker = RedisBroker(url=os.getenv("REDIS_URL", "redis://redis:6379/0"))
broker.add_middleware(AsyncIO())
dramatiq.set_broker(broker)


def requires_global_run_gate(task_type: str) -> bool:
    """兼容视图：并发策略以 AgentDefinition 为权威来源。"""

    return get_agent_definition(task_type).run_gate_policy == "global"


@dramatiq.actor(queue_name="interactive", max_retries=10, min_backoff=1000)
async def execute_agent_run(run_id: str) -> None:
    """执行当前工具或任务调用，先通过契约、权限、审批和审计校验，再把结果返回给上层工作流。

    Args:
        run_id: 运行标识。
    """
    await get_queued_driver(service=AgentRunService()).run(run_id)
