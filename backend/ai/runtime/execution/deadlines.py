"""跨重试与 fallback 共享的任务总 deadline。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic


class TaskDeadlineExceeded(TimeoutError):
    """任务总时间预算已耗尽，调用方应进入业务兜底而不是重置计时。"""


@dataclass(slots=True)
class TaskDeadline:
    """维护任务总超时和剩余时间；所有 attempt 必须复用同一实例。"""

    total_timeout: float
    started_at: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        """规范化总超时，负数和非法零值按已过期处理。"""
        self.total_timeout = max(0.0, float(self.total_timeout))

    def remaining(self) -> float:
        """返回剩余秒数；结果不会小于零。"""
        return max(0.0, self.total_timeout - (monotonic() - self.started_at))

    @property
    def expired(self) -> bool:
        """返回任务总 deadline 是否已经耗尽。"""
        return self.remaining() <= 0.0

    @property
    def deadline_ms(self) -> int:
        """返回总时间预算的毫秒值，供安全观测使用。"""
        return max(0, int(self.total_timeout * 1000))

    @property
    def remaining_ms(self) -> int:
        """返回剩余时间的毫秒值，供安全观测和 attempt 决策使用。"""
        return max(0, int(self.remaining() * 1000))

    def timeout_for_next_attempt(
        self,
        max_attempt_timeout: float,
        *,
        minimum_required: float = 0.0,
    ) -> float:
        """按剩余预算裁剪单次超时；不足最小启动时间时返回零。"""
        remaining = self.remaining()
        if remaining <= max(0.0, minimum_required):
            return 0.0
        return min(max(0.0, float(max_attempt_timeout)), remaining)

    def require_time(self, minimum_required: float = 0.0) -> float:
        """确认仍有足够时间并返回剩余秒数，否则抛出稳定超时异常。"""
        remaining = self.remaining()
        if remaining <= max(0.0, minimum_required):
            raise TaskDeadlineExceeded("task deadline exhausted")
        return remaining


_current_task_deadline: ContextVar[TaskDeadline | None] = ContextVar(
    "current_task_deadline", default=None
)


@contextmanager
def task_deadline_scope(
    total_timeout: float | None = None,
    *,
    deadline: TaskDeadline | None = None,
) -> Iterator[TaskDeadline]:
    """在当前异步上下文绑定共享 deadline；嵌套调用默认复用显式实例。"""
    if deadline is None and total_timeout is None:
        raise ValueError("total_timeout or deadline is required")
    selected = deadline or TaskDeadline(total_timeout or 0.0)
    token = _current_task_deadline.set(selected)
    try:
        yield selected
    finally:
        _current_task_deadline.reset(token)


def get_current_task_deadline() -> TaskDeadline | None:
    """读取当前任务绑定的 deadline；未迁移流程返回 ``None``。"""
    return _current_task_deadline.get()
