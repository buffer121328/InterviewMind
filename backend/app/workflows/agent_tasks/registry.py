"""AgentRun 业务任务注册表。

注册表只依赖 domain task 常量和轻量协议；具体任务实现延迟导入，避免 worker
启动时把所有 agent 图、LLM、浏览器编排一次性耦合进 runtime 基础设施。
"""

from app.domain.agent_runs import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_RESUME_OPTIMIZE,
)
from app.workflows.agent_tasks.types import ExecutionResult, ProgressCallback, TaskExecutor


async def _execute_interview_start(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from app.workflows.agent_tasks.interview_start import execute_interview_start

    return await execute_interview_start(payload, user_id, progress)


async def _execute_resume_optimize(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from app.workflows.agent_tasks.resume_optimize import execute_resume_optimize

    return await execute_resume_optimize(payload, user_id, progress)


async def _execute_interview_report(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from app.workflows.agent_tasks.interview_report import execute_interview_report

    return await execute_interview_report(payload, user_id, progress)


async def _execute_job_assets(payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    from app.workflows.agent_tasks.job_assets import execute_job_assets

    return await execute_job_assets(payload, user_id, progress)


EXECUTORS: dict[str, TaskExecutor] = {
    TASK_TYPE_INTERVIEW_START: _execute_interview_start,
    TASK_TYPE_RESUME_OPTIMIZE: _execute_resume_optimize,
    TASK_TYPE_INTERVIEW_REPORT: _execute_interview_report,
    TASK_TYPE_JOB_ASSETS: _execute_job_assets,
}


async def execute_registered_task(task_type: str, payload: dict, user_id: str, progress: ProgressCallback) -> ExecutionResult:
    """根据任务类型从注册表查找并执行对应的业务任务。"""
    try:
        executor = EXECUTORS[task_type]
    except KeyError as exc:
        raise ValueError(f"未知任务类型: {task_type}") from exc
    return await executor(payload, user_id, progress)
