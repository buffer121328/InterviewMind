"""AgentRun 业务任务模块。

具体执行器通过 ``__getattr__`` 延迟导入，避免仅使用一个任务时加载所有 Agent
图、可选模型依赖与浏览器集成。
"""

from importlib import import_module

from ai.workflows.agent_tasks.registry import EXECUTORS, execute_registered_task
from ai.workflows.agent_tasks.types import DeferredExecutionResult, ExecutionResult, ProgressCallback, TaskExecutor

_EXECUTOR_MODULES = {
    "execute_interview_report": "ai.workflows.agent_tasks.interview_report",
    "execute_interview_start": "ai.workflows.agent_tasks.interview_start",
    "execute_job_assets": "ai.workflows.agent_tasks.job_assets",
    "execute_resume_optimize": "ai.workflows.agent_tasks.resume_optimize",
    "execute_resume_workspace": "ai.workflows.agent_tasks.resume_workspace",
}


def __getattr__(name: str):
    """Load a named task executor only when a caller explicitly requests it."""
    try:
        module_name = _EXECUTOR_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    return getattr(import_module(module_name), name)

__all__ = [
    "DeferredExecutionResult",
    "EXECUTORS",
    "ExecutionResult",
    "ProgressCallback",
    "TaskExecutor",
    "execute_interview_report",
    "execute_interview_start",
    "execute_job_assets",
    "execute_registered_task",
    "execute_resume_optimize",
    "execute_resume_workspace",
]
