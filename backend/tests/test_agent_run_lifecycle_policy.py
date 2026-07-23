"""AgentRun 生命周期语义。"""

from ai.runtime.agent_runs.lifecycle import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    can_request_cancel,
    can_request_pause,
    can_resume,
    cancel_transition,
    is_active_status,
    is_terminal_status,
    pause_transition,
    resume_transition,
)


def test_active_and_terminal_status_sets_are_disjoint():
    assert ACTIVE_STATUSES.isdisjoint(TERMINAL_STATUSES)
    assert is_active_status("running")
    assert is_active_status("cancel_requested")
    assert not is_active_status("cancelled")
    assert is_terminal_status("cancelled")
    assert is_terminal_status("failed")


def test_cancel_transition_distinguishes_pending_from_cooperative_cancel():
    assert cancel_transition("queued") == "cancelled"
    assert cancel_transition("retrying") == "cancelled"
    assert cancel_transition("running") == "cancel_requested"
    assert cancel_transition("paused") == "cancel_requested"
    assert cancel_transition("awaiting_approval") == "cancel_requested"
    assert cancel_transition("cancel_requested") == "cancel_requested"
    assert cancel_transition("succeeded") is None
    assert cancel_transition("failed") is None
    assert cancel_transition("cancelled") is None


def test_pause_and_resume_transitions_are_explicit():
    assert pause_transition("queued") == "paused"
    assert pause_transition("running") == "pause_requested"
    assert pause_transition("awaiting_approval") == "paused"
    assert pause_transition("cancel_requested") is None
    assert resume_transition("pause_requested") == "running"
    assert resume_transition("paused") == "running"
    assert resume_transition("awaiting_approval") == "running"
    assert resume_transition("running") is None


def test_guard_helpers_match_transition_rules():
    for status in ACTIVE_STATUSES:
        assert can_request_cancel(status)
    for status in TERMINAL_STATUSES:
        assert not can_request_cancel(status)
    assert can_request_pause("running")
    assert not can_request_pause("cancel_requested")
    assert can_resume("paused")
    assert not can_resume("cancelled")
