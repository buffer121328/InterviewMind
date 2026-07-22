"""兼容旧路径的 AgentRun 执行器导出。

业务任务实现已下沉到 ``app.workflows.agent_tasks``；本模块只保留旧导入路径，
避免运行时基础设施继续承载简历、面试报告、岗位资产等业务细节。
"""

from app.workflows.agent_tasks import (
    DeferredExecutionResult,
    EXECUTORS,
    ExecutionResult,
    ProgressCallback,
    TaskExecutor,
    execute_interview_report,
    execute_interview_start,
    execute_job_assets,
    execute_registered_task,
    execute_resume_optimize,
)

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
]
