"""AgentRun 队列等待时间使用首次或最近重试入队时间。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from ai.runtime.agent_runs.service import _queue_wait_ms


def test_queue_wait_uses_created_at_for_first_attempt():
    now = datetime(2026, 7, 29, 12, 0, 0)
    run = SimpleNamespace(
        status="queued",
        created_at=now - timedelta(seconds=3),
        updated_at=now - timedelta(seconds=1),
    )

    assert _queue_wait_ms(run, now) == 3000


def test_queue_wait_uses_latest_retry_transition_and_clamps_clock_skew():
    now = datetime(2026, 7, 29, 12, 0, 0)
    retrying = SimpleNamespace(
        status="retrying",
        created_at=now - timedelta(minutes=5),
        updated_at=now - timedelta(milliseconds=250),
    )
    future = SimpleNamespace(
        status="queued",
        created_at=now + timedelta(seconds=1),
        updated_at=now,
    )

    assert _queue_wait_ms(retrying, now) == 250
    assert _queue_wait_ms(future, now) == 0
