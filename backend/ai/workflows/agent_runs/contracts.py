"""AgentRun 旧任务协议的兼容导出；权威结果契约位于 Harness。"""

from collections.abc import Awaitable, Callable

from ai.runtime.harness.contracts import (
    DeferredExecutionResult,
    ExecutionResult,
    PersistResultCallback,
    ProgressCallback,
)

TaskExecutor = Callable[[dict, str, ProgressCallback], Awaitable[ExecutionResult]]

__all__ = [
    "DeferredExecutionResult",
    "ExecutionResult",
    "PersistResultCallback",
    "ProgressCallback",
    "TaskExecutor",
]
