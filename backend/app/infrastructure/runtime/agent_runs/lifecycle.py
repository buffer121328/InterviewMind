"""AgentRun 生命周期状态与转换语义。

这个模块只定义状态机规则，不访问数据库，便于 API、Worker、恢复逻辑和测试复用同一套语义。
"""

from typing import Literal

RunStatus = Literal[
    "queued",
    "retrying",
    "running",
    "pause_requested",
    "paused",
    "awaiting_approval",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
]

ACTIVE_STATUSES: frozenset[str] = frozenset({
    "queued",
    "retrying",
    "running",
    "pause_requested",
    "paused",
    "awaiting_approval",
    "cancel_requested",
})
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
CANCELLABLE_STATUSES: frozenset[str] = ACTIVE_STATUSES
PAUSABLE_STATUSES: frozenset[str] = frozenset({"queued", "retrying", "running", "awaiting_approval"})
RESUMABLE_STATUSES: frozenset[str] = frozenset({"pause_requested", "paused", "awaiting_approval"})


def is_active_status(status: str) -> bool:
    return status in ACTIVE_STATUSES


def is_terminal_status(status: str) -> bool:
    return status in TERMINAL_STATUSES


def can_request_cancel(status: str) -> bool:
    return status in CANCELLABLE_STATUSES


def can_request_pause(status: str) -> bool:
    return status in PAUSABLE_STATUSES


def can_resume(status: str) -> bool:
    return status in RESUMABLE_STATUSES


def cancel_transition(status: str) -> str | None:
    """返回请求取消后的目标状态。

    - 尚未真正执行的 queued/retrying 可以直接进入 cancelled；
    - running/pause_requested/paused/awaiting_approval 需要协作收敛到 cancelled；
    - 终态不可再取消。
    """
    if status in {"queued", "retrying"}:
        return "cancelled"
    if status in {"running", "pause_requested", "paused", "awaiting_approval", "cancel_requested"}:
        return "cancel_requested"
    return None


def pause_transition(status: str) -> str | None:
    if status in {"queued", "retrying", "awaiting_approval"}:
        return "paused"
    if status == "running":
        return "pause_requested"
    return None


def resume_transition(status: str) -> str | None:
    if status in {"pause_requested", "paused", "awaiting_approval"}:
        return "running"
    return None
