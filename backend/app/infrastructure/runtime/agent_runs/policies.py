"""AgentRun 生命周期策略。"""

from typing import Literal

RunRetryPolicy = Literal["whole_run_retry", "checkpoint_resume_only"]

_RETRY_POLICIES: dict[str, RunRetryPolicy] = {
    "interview_start": "whole_run_retry",
    "interview_turn": "checkpoint_resume_only",
    "voice_interview_turn": "checkpoint_resume_only",
    "resume_optimize": "whole_run_retry",
    "interview_report": "whole_run_retry",
    "job_assets": "whole_run_retry",
}


def get_retry_policy(task_type: str) -> RunRetryPolicy:
    """返回任务的重试策略，未知任务默认禁止整次重试。"""
    return _RETRY_POLICIES.get(task_type, "checkpoint_resume_only")


def allows_whole_run_retry(task_type: str) -> bool:
    """是否允许用户对整个 Run 重新执行。"""
    return get_retry_policy(task_type) == "whole_run_retry"
