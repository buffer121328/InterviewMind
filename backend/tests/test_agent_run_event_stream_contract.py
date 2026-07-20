"""AgentRun SSE 断线重放契约。"""

from app.infrastructure.runtime.agent_runs.event_stream import replay_cursor


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


def test_build_run_event_envelope_uses_inline_defaults():
    from app.infrastructure.runtime.agent_runs.event_stream import build_run_event_envelope

    event = build_run_event_envelope(
        run_id="run-1",
        event_type="run.started",
        stage="generating_response",
        payload={"attempt": 1},
    )

    assert event["event_id"] == "inline:run-1:run.started"
    assert event["run_id"] == "run-1"
    assert event["sequence"] == 0
    assert event["type"] == "run.started"
    assert event["stage"] == "generating_response"
    assert event["payload"] == {"attempt": 1}
    assert event["schema_version"] == 1
    assert isinstance(event["timestamp"], str)
