"""AgentRun 整次重试策略。"""

from ai.runtime.agent_runs.policies import allows_whole_run_retry, get_retry_policy
from ai.runtime.agent_runs.service import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
)


def test_interactive_runs_do_not_allow_whole_run_retry():
    assert get_retry_policy(TASK_TYPE_INTERVIEW_TURN) == "checkpoint_resume_only"
    assert get_retry_policy(TASK_TYPE_VOICE_INTERVIEW_TURN) == "checkpoint_resume_only"
    assert not allows_whole_run_retry(TASK_TYPE_INTERVIEW_TURN)
    assert not allows_whole_run_retry(TASK_TYPE_VOICE_INTERVIEW_TURN)


def test_background_runs_allow_whole_run_retry():
    for task_type in [
        TASK_TYPE_INTERVIEW_START,
        TASK_TYPE_RESUME_OPTIMIZE,
        TASK_TYPE_INTERVIEW_REPORT,
        TASK_TYPE_JOB_ASSETS,
    ]:
        assert get_retry_policy(task_type) == "whole_run_retry"
        assert allows_whole_run_retry(task_type)


def test_unknown_runs_default_to_checkpoint_resume_only():
    assert get_retry_policy("unknown") == "checkpoint_resume_only"
    assert not allows_whole_run_retry("unknown")
