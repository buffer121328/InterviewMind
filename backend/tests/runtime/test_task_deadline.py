"""TaskDeadline 在 attempt、fallback 和嵌套调用之间共享总时间预算。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from ai.llm import llms
from ai.llm import llm_utils
from ai.llm.llm_utils import invoke_structured
from ai.runtime.execution import deadlines
from ai.runtime.execution.deadlines import (
    TaskDeadline,
    TaskDeadlineExceeded,
    get_current_task_deadline,
    task_deadline_scope,
)


class _Output(BaseModel):
    answer: str


class _Runnable:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    async def ainvoke(self, _input):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _LLM:
    def __init__(self, runnable):
        self.runnable = runnable

    def with_structured_output(self, _output_model, **_kwargs):
        return self.runnable


class _SequencedDeadline:
    """测试替身：首个 attempt 可运行，后续 fallback 没有剩余预算。"""

    deadline_ms = 1000
    remaining_ms = 0

    def __init__(self):
        self.calls = []

    def timeout_for_next_attempt(self, max_attempt_timeout, *, minimum_required=0.0):
        self.calls.append((max_attempt_timeout, minimum_required))
        return 0.1 if len(self.calls) == 1 else 0.0


def test_task_deadline_remaining_and_attempt_timeout_decrease(monkeypatch):
    current = {"value": 10.0}
    monkeypatch.setattr(deadlines, "monotonic", lambda: current["value"])
    deadline = TaskDeadline(total_timeout=5.0, started_at=10.0)

    assert deadline.remaining() == 5.0
    assert deadline.timeout_for_next_attempt(3.0) == 3.0

    current["value"] = 14.5
    assert deadline.remaining() == 0.5
    assert deadline.timeout_for_next_attempt(3.0) == 0.5
    assert deadline.timeout_for_next_attempt(3.0, minimum_required=0.5) == 0.0


def test_task_deadline_scope_exposes_same_instance():
    deadline = TaskDeadline(total_timeout=10)

    with task_deadline_scope(deadline=deadline) as active:
        assert active is deadline
        assert get_current_task_deadline() is deadline

    assert get_current_task_deadline() is None


def test_structured_repair_window_is_ninety_seconds_and_deadline_clipped(monkeypatch):
    """格式修复可等待 90 秒，但不会超出所属任务的剩余预算。"""
    current = {"value": 10.0}
    monkeypatch.setattr(deadlines, "monotonic", lambda: current["value"])

    assert llm_utils._STRUCTURED_REPAIR_TIMEOUT_SECONDS == 90.0
    assert TaskDeadline(total_timeout=120.0, started_at=10.0).timeout_for_next_attempt(
        llm_utils._STRUCTURED_REPAIR_TIMEOUT_SECONDS,
        minimum_required=llm_utils._STRUCTURED_REPAIR_MINIMUM_SECONDS,
    ) == 90.0
    assert TaskDeadline(total_timeout=45.0, started_at=10.0).timeout_for_next_attempt(
        llm_utils._STRUCTURED_REPAIR_TIMEOUT_SECONDS,
        minimum_required=llm_utils._STRUCTURED_REPAIR_MINIMUM_SECONDS,
    ) == 45.0


@pytest.mark.asyncio
async def test_structured_fallback_is_not_started_when_deadline_is_exhausted(monkeypatch):
    import observability

    primary = _Runnable(TimeoutError())
    fallback = _Runnable(_Output(answer="must-not-run"))
    monkeypatch.setattr(
        llms.model_gateway,
        "get_chat_candidates",
        lambda *_args, **_kwargs: [_LLM(primary), _LLM(fallback)],
    )
    deadline = _SequencedDeadline()
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    observability._reset_langfuse_for_tests()

    async with observability.agent_observation(
        name="deadline-test",
        agent_type="planner",
        user_id="user-1",
        session_id="session-1",
        input_payload={"case": "deadline"},
    ) as observation:
        with pytest.raises(TaskDeadlineExceeded):
            await invoke_structured(
                "return json",
                _Output,
                api_config={"smart": {}},
                max_retries=0,
                deadline=deadline,  # type: ignore[arg-type]
            )

    assert primary.calls == 1
    assert fallback.calls == 0
    assert len(deadline.calls) == 2
    assert [event["event_type"] for event in observation.model_events] == [
        "llm.request.failed",
        "llm.request.skipped",
    ]
    assert all(event["failure_type"] == "timeout" for event in observation.model_events)
    assert "return json" not in str(observation.model_events)
    observability._reset_langfuse_for_tests()
