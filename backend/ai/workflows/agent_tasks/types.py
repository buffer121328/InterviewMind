"""AgentRun 业务任务执行协议。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

"""进度回调：接收阶段名称，供 AgentRun 生命周期追踪执行进度。"""
ProgressCallback = Callable[[str], Awaitable[None]]

"""延迟持久化回调：在 AgentRun 完成事务内写业务结果。"""
PersistResultCallback = Callable[[AsyncSession], Awaitable[dict]]


@dataclass(frozen=True)
class DeferredExecutionResult:
    """延迟执行结果：业务结果需和 AgentRun 完成态在同一数据库事务内落库。"""

    persist: PersistResultCallback


"""执行器返回类型：普通 dict 或需延迟持久化的结果。"""
ExecutionResult = dict | DeferredExecutionResult
"""任务执行器签名：(payload, user_id, progress) -> ExecutionResult。"""
TaskExecutor = Callable[[dict, str, ProgressCallback], Awaitable[ExecutionResult]]
