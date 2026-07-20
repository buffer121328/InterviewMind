"""AgentRun parent/child payload 契约。"""

from app.infrastructure.runtime.agent_runs.relationships import (
    PARENT_RUN_ID_KEY,
    RUN_RELATIONSHIP_KEY,
    child_run_payload,
    get_parent_run_id,
    get_run_relationship,
)


def test_child_run_payload_preserves_business_fields():
    payload = child_run_payload(
        parent_run_id="run-parent",
        relationship="model_call",
        payload={"model": "gpt-demo"},
    )

    assert payload == {
        "model": "gpt-demo",
        PARENT_RUN_ID_KEY: "run-parent",
        RUN_RELATIONSHIP_KEY: "model_call",
    }


def test_child_run_payload_parent_fields_override_conflicting_input():
    payload = child_run_payload(
        parent_run_id="run-parent",
        relationship="tool_call",
        payload={PARENT_RUN_ID_KEY: "stale", RUN_RELATIONSHIP_KEY: "stale"},
    )

    assert get_parent_run_id(payload) == "run-parent"
    assert get_run_relationship(payload) == "tool_call"


def test_missing_or_invalid_relationship_payload_is_none():
    assert get_parent_run_id({}) is None
    assert get_parent_run_id({PARENT_RUN_ID_KEY: ""}) is None
    assert get_parent_run_id({PARENT_RUN_ID_KEY: 123}) is None
    assert get_run_relationship({}) is None
    assert get_run_relationship({RUN_RELATIONSHIP_KEY: 123}) is None
