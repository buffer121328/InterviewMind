import pytest

from ai.agents.resume.resume_review import (
    ReviewConflictError,
    apply_review_decisions,
    initialize_review,
    public_review_state,
)


def _result() -> dict:
    return {
        "assembled_resume": "Python 熟练，主导平台改造",
        "confirmation_items": [
            {
                "item_id": "skill-item",
                "original_text": "Python 了解",
                "optimized_text": "Python 熟练",
            },
            {
                "item_id": "lead-item",
                "original_text": "参与平台改造",
                "optimized_text": "主导平台改造",
            },
        ],
    }


def test_initialize_review_is_durable_and_pending():
    result = initialize_review(_result())

    assert result["human_review"]["status"] == "pending"
    assert result["human_review"]["version"] == 1
    assert result["human_review"]["resolved_resume"] is None


def test_partial_review_does_not_release_resume():
    result = initialize_review(_result())
    updated = apply_review_decisions(
        result,
        decisions=[{"item_id": "skill-item", "decision": "approved"}],
        expected_version=1,
    )

    assert updated["human_review"]["status"] == "pending"
    assert updated["human_review"]["resolved_resume"] is None
    assert public_review_state(updated)["items"][0]["status"] == "approved"


def test_completed_review_reverts_rejected_change():
    result = initialize_review(_result())
    updated = apply_review_decisions(
        result,
        decisions=[
            {"item_id": "skill-item", "decision": "rejected"},
            {"item_id": "lead-item", "decision": "approved"},
        ],
        expected_version=1,
    )

    review = updated["human_review"]
    assert review["status"] == "completed"
    assert review["resolved_resume"] == "Python 了解，主导平台改造"
    assert len(review["events"]) == 2


def test_stale_review_version_is_rejected():
    with pytest.raises(ReviewConflictError, match="版本冲突"):
        apply_review_decisions(
            initialize_review(_result()),
            decisions=[{"item_id": "skill-item", "decision": "approved"}],
            expected_version=2,
        )


def test_missing_optimized_text_fails_closed():
    result = initialize_review(_result())
    result["assembled_resume"] = "内容已被其他流程修改"

    with pytest.raises(ReviewConflictError, match="无法安全撤回"):
        apply_review_decisions(
            result,
            decisions=[
                {"item_id": "skill-item", "decision": "rejected"},
                {"item_id": "lead-item", "decision": "approved"},
            ],
            expected_version=1,
        )


def test_public_state_hides_internal_audit_events():
    state = public_review_state(initialize_review(_result()))

    assert "events" not in state


def test_legacy_review_items_receive_stable_ids():
    legacy = _result()
    for item in legacy["confirmation_items"]:
        item.pop("item_id")

    first = public_review_state(legacy)
    second = public_review_state(legacy)

    assert all(item["item_id"] for item in first["items"])
    assert [item["item_id"] for item in first["items"]] == [
        item["item_id"] for item in second["items"]
    ]
