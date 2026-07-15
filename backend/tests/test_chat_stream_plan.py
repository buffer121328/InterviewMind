"""聊天 SSE 应暴露可展示的执行计划和步骤状态。"""

import json

import pytest

from app.api import chat


class _Chunk:
    content = "下一题"


class _Graph:
    async def astream_events(self, *_args, **_kwargs):
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "responder"},
            "data": {"chunk": _Chunk()},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "responder"},
            "data": {"output": {"question_count": 2, "max_questions": 5, "current_question_index": 2}},
        }


class _Repo:
    async def add_message(self, **_kwargs):
        return None

    async def update_session(self, **_kwargs):
        return None


class _Lease:
    released = False

    async def release(self):
        self.released = True


def _decode(line: str) -> dict:
    return json.loads(line.removeprefix("data: ").strip())


@pytest.mark.asyncio
async def test_event_generator_emits_execution_plan(monkeypatch):
    monkeypatch.setattr(chat, "session_repo", _Repo())
    monkeypatch.setattr("app.services.agent_memory.should_skip_write", lambda *_args: True)
    lease = _Lease()

    lines = [
        line
        async for line in chat.event_generator(
            _Graph(),
            {"current_question_index": 1, "max_questions": 5},
            {},
            "session-1",
            "我的回答",
            "user-1",
            lease,
        )
    ]
    events = [_decode(line) for line in lines]
    types = [event["type"] for event in events]

    assert types[0] == "plan"
    assert "step_update" in types
    assert "token" in types
    assert types[-1] == "done"
    plan = json.loads(events[0]["content"])
    assert [step["id"] for step in plan] == [
        "save_answer",
        "analyze_answer",
        "generate_response",
        "update_progress",
    ]
    completed = {
        json.loads(event["content"])["id"]
        for event in events
        if event["type"] == "step_update" and json.loads(event["content"])["status"] == "completed"
    }
    assert completed == {"save_answer", "analyze_answer", "generate_response", "update_progress"}
    assert lease.released is True
