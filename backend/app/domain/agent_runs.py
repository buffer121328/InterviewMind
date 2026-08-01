"""Agent run domain rules shared by runtime and HTTP layers."""

from __future__ import annotations

from collections.abc import Sequence

TASK_TYPE_INTERVIEW_START = "interview_start"
TASK_TYPE_INTERVIEW_TURN = "interview_turn"
TASK_TYPE_VOICE_INTERVIEW_TURN = "voice_interview_turn"
TASK_TYPE_RESUME_OPTIMIZE = "resume_optimize"
TASK_TYPE_RESUME_WORKSPACE = "resume_workspace"
TASK_TYPE_RESUME_GENERATION = "resume_generation"
TASK_TYPE_INTERVIEW_REPORT = "interview_report"
TASK_TYPE_JOB_ASSETS = "job_assets"
TASK_TYPE_JOB_RECOMMENDATION_CAPTURE = "job_recommendation_capture"
TASK_TYPE_EVALUATION_SUITE = "evaluation_suite"
# 仅用于读取数据库中的历史任务；采集 API 与执行器已下线。
# 历史 task_type 记录全部归档/过保留期后，在 AgentRun schema 清理阶段删除。
TASK_TYPE_INTERVIEW_EXPERIENCE_COLLECT = "interview_experience_collect"

ACTIVE_STATUSES: frozenset[str] = frozenset(
    {"queued", "retrying", "running", "cancel_requested"}
)
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})


def is_terminal_status(status: str) -> bool:
    """Return whether an AgentRun status is terminal."""
    return status in TERMINAL_STATUSES


def is_active_status(status: str) -> bool:
    """Return whether an AgentRun status can still make progress."""
    return status in ACTIVE_STATUSES


def can_cancel_status(status: str) -> bool:
    """Return whether a run in the given status accepts cancellation."""
    return status in ACTIVE_STATUSES


def build_task_plan_from_steps(
    steps: Sequence[tuple[str, str]],
    *,
    stage: str,
    status: str,
) -> list[dict[str, str]]:
    """Build the frontend task plan from domain task steps and current state."""
    stage_index = next((index for index, item in enumerate(steps) if item[0] == stage), -1)
    terminal_success = status == "succeeded"
    terminal_failure = status in {"failed", "cancelled"}
    if terminal_failure and stage_index < 0:
        stage_index = 0

    plan: list[dict[str, str]] = []
    for index, (step_id, title) in enumerate(steps):
        if terminal_success or index < stage_index:
            step_status = "completed"
        elif index == stage_index:
            step_status = "failed" if terminal_failure else "running"
        else:
            step_status = "pending"
        plan.append({"id": step_id, "title": title, "status": step_status})
    return plan
