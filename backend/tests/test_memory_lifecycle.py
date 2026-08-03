"""Acceptance tests for automatic memory lifecycle and historical consolidation."""

import json

import pytest

from ai.memory.lifecycle import (
    ConsolidationAction,
    LifecycleAction,
    build_historical_consolidation_prompt,
    build_incremental_lifecycle_prompt,
    parse_historical_plan,
    parse_incremental_plan,
)
from ai.memory.service import AgentMemoryService


@pytest.mark.parametrize(
    ("action", "target_id", "content"),
    [
        ("ADD", None, None),
        ("NONE", None, None),
        ("UPDATE", "existing-1", "用户现在主要使用 FastAPI 和 PostgreSQL"),
        ("DELETE", "existing-1", None),
    ],
)
def test_incremental_plan_accepts_valid_lifecycle_actions(action, target_id, content):
    payload = {
        "operations": [
            {
                "new_id": "new-1",
                "action": action,
                "target_id": target_id,
                "content": content,
                "confidence": 0.96,
                "reason": "same durable topic",
            }
        ]
    }

    plan = parse_incremental_plan(
        json.dumps(payload),
        new_ids={"new-1"},
        existing_ids={"existing-1"},
    )

    assert plan[0].action is LifecycleAction(action)
    assert plan[0].target_id == target_id
    assert plan[0].content == content


def test_incremental_plan_falls_back_to_add_for_low_confidence_or_unowned_ids():
    payload = {
        "operations": [
            {
                "new_id": "new-1",
                "action": "UPDATE",
                "target_id": "other-user-memory",
                "content": "unsafe",
                "confidence": 0.99,
            },
            {
                "new_id": "new-2",
                "action": "NONE",
                "confidence": 0.60,
            },
        ]
    }

    plan = parse_incremental_plan(
        json.dumps(payload),
        new_ids={"new-1", "new-2"},
        existing_ids={"existing-1"},
    )

    assert {operation.new_id: operation.action for operation in plan} == {
        "new-1": LifecycleAction.ADD,
        "new-2": LifecycleAction.ADD,
    }


def test_incremental_plan_falls_back_to_add_for_malformed_output():
    plan = parse_incremental_plan(
        "not-json",
        new_ids={"new-1"},
        existing_ids={"existing-1"},
    )

    assert plan[0].action is LifecycleAction.ADD


def test_historical_plan_defaults_to_keep_and_validates_mutations():
    payload = {
        "operations": [
            {
                "memory_id": "memory-1",
                "action": "UPDATE",
                "content": "用户偏好使用 FastAPI",
                "confidence": 0.95,
                "reason": "canonicalized preference",
            },
            {
                "memory_id": "memory-2",
                "action": "DELETE",
                "confidence": 0.96,
                "reason": "assistant recommendation",
            },
            {
                "memory_id": "other-user-memory",
                "action": "DELETE",
                "confidence": 0.99,
            },
        ]
    }

    plan = parse_historical_plan(
        json.dumps(payload),
        owned_ids={"memory-1", "memory-2", "memory-3"},
    )

    assert {operation.memory_id: operation.action for operation in plan} == {
        "memory-1": ConsolidationAction.UPDATE,
        "memory-2": ConsolidationAction.DELETE,
        "memory-3": ConsolidationAction.KEEP,
    }


def test_lifecycle_prompts_use_bounded_json_records_without_secrets():
    existing = [{"id": "existing-1", "memory": "用户偏好 FastAPI", "metadata": {}}]
    new = [{"id": "new-1", "memory": "用户主要使用 FastAPI", "metadata": {}}]

    incremental = build_incremental_lifecycle_prompt(existing=existing, new=new)
    historical = build_historical_consolidation_prompt(records=existing + new)

    assert "existing-1" in incremental
    assert "new-1" in incremental
    assert "ADD, NONE, UPDATE, or DELETE" in incremental
    assert "KEEP, UPDATE, or DELETE" in historical
    assert "api_key" not in incremental.lower()


class _FakeLifecycleLLM:
    """Return one structured lifecycle response and record call count."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload, ensure_ascii=False)


class _StatefulMemory:
    """Small synchronous mem0 replacement that records mutation ordering."""

    def __init__(self, *, existing, add_result, lifecycle_payload):
        self.records = {item["id"]: dict(item) for item in existing}
        self.add_result = add_result
        self.llm = _FakeLifecycleLLM(lifecycle_payload)
        self.operations = []

    def search(self, **_kwargs):
        return {"results": list(self.records.values())}

    def add(self, *_args, **_kwargs):
        for item in self.add_result["results"]:
            self.records[item["id"]] = dict(item)
        return self.add_result

    def get_all(self, **_kwargs):
        return {"results": list(self.records.values())}

    def update(self, *, memory_id, data):
        self.operations.append(("update", memory_id, data))
        self.records[memory_id]["memory"] = data
        return {"message": "updated"}

    def delete(self, *, memory_id):
        self.operations.append(("delete", memory_id))
        self.records.pop(memory_id, None)
        return {"message": "deleted"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected_operations"),
    [
        ("NONE", [("delete", "new-1")]),
        (
            "UPDATE",
            [
                ("update", "existing-1", "用户现在主要使用 FastAPI 和 PostgreSQL"),
                ("delete", "new-1"),
            ],
        ),
        ("DELETE", [("delete", "existing-1"), ("delete", "new-1")]),
    ],
)
async def test_later_round_applies_lifecycle_in_fail_safe_order(action, expected_operations):
    content = "用户现在主要使用 FastAPI 和 PostgreSQL" if action == "UPDATE" else None
    memory = _StatefulMemory(
        existing=[{"id": "existing-1", "memory": "用户偏好 FastAPI", "metadata": {}}],
        add_result={"results": [{"id": "new-1", "memory": "用户偏好 FastAPI", "metadata": {}}]},
        lifecycle_payload={
            "operations": [
                {
                    "new_id": "new-1",
                    "action": action,
                    "target_id": "existing-1" if action in {"UPDATE", "DELETE"} else None,
                    "content": content,
                    "confidence": 0.97,
                    "reason": "later-round lifecycle",
                }
            ]
        },
    )
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    await service.add_interaction(
        user_id="user-1",
        session_id="round-2",
        user_message="我现在主要使用 FastAPI 和 PostgreSQL",
        assistant_message="收到。",
    )

    assert memory.operations == expected_operations


@pytest.mark.asyncio
async def test_first_round_new_fact_skips_lifecycle_model_and_remains_addition():
    memory = _StatefulMemory(
        existing=[],
        add_result={"results": [{"id": "new-1", "memory": "用户偏好 FastAPI", "metadata": {}}]},
        lifecycle_payload={"operations": []},
    )
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    await service.add_interaction(
        user_id="user-1",
        session_id="round-1",
        user_message="我偏好 FastAPI",
        assistant_message="收到。",
    )

    assert "new-1" in memory.records
    assert memory.llm.calls == []
    assert memory.operations == []


@pytest.mark.asyncio
async def test_historical_consolidation_dry_run_and_confirmed_apply():
    records = [
        {"id": "memory-1", "memory": "用户偏好 FastAPI", "metadata": {}},
        {"id": "memory-2", "memory": "用户被建议每天刷题", "metadata": {}},
        {"id": "memory-3", "memory": "用户主要使用 FastAPI", "metadata": {}},
    ]
    payload = {
        "operations": [
            {
                "memory_id": "memory-1",
                "action": "UPDATE",
                "content": "用户偏好并主要使用 FastAPI",
                "confidence": 0.96,
                "reason": "merge same topic",
            },
            {
                "memory_id": "memory-2",
                "action": "DELETE",
                "confidence": 0.98,
                "reason": "assistant-only recommendation",
            },
            {
                "memory_id": "memory-3",
                "action": "DELETE",
                "confidence": 0.96,
                "reason": "merged into memory-1",
            },
        ]
    }
    memory = _StatefulMemory(existing=records, add_result={"results": []}, lifecycle_payload=payload)
    service = AgentMemoryService({"version": "test"})
    service._memory = memory
    service._enabled = True

    preview = await service.consolidate_existing_memories(
        user_id="user-1",
        dry_run=True,
        max_memories=50,
    )

    assert preview["dry_run"] is True
    assert preview["counts"] == {"KEEP": 0, "UPDATE": 1, "DELETE": 2}
    assert memory.operations == []

    applied = await service.consolidate_existing_memories(
        user_id="user-1",
        dry_run=False,
        max_memories=50,
    )

    assert applied["dry_run"] is False
    assert applied["applied_counts"] == {"UPDATE": 1, "DELETE": 2}
    assert len(memory.records) == 1
    assert memory.records["memory-1"]["memory"] == "用户偏好并主要使用 FastAPI"
