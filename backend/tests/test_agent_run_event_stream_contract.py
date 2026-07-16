"""AgentRun SSE 断线重放契约。"""

from app.services.agent_runs.event_stream import replay_cursor


def test_replay_cursor_uses_after_sequence_without_last_event_id():
    assert replay_cursor(after_sequence=3, last_event_id=None) == 3


def test_replay_cursor_uses_last_event_id_when_larger():
    assert replay_cursor(after_sequence=3, last_event_id="7") == 7


def test_replay_cursor_uses_after_sequence_when_larger():
    assert replay_cursor(after_sequence=8, last_event_id="7") == 8


def test_replay_cursor_ignores_invalid_last_event_id():
    assert replay_cursor(after_sequence=5, last_event_id="not-a-number") == 5
    assert replay_cursor(after_sequence=5, last_event_id="") == 5


def test_replay_cursor_never_goes_negative():
    assert replay_cursor(after_sequence=-1, last_event_id=None) == 0
