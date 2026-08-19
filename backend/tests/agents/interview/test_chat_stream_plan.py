"""聊天 SSE 应暴露可展示的执行计划和步骤状态。"""

import json

import pytest

from ai.workflows.interview.chat import stream as chat_stream
from ai.workflows.interview.chat.stream import ChatStreamUseCases


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
            "data": {"output": {
                "messages": [{"role": "assistant", "content": "下一题"}],
                "question_count": 2,
                "max_questions": 5,
                "current_question_index": 2,
                "turn_state": {"state_version": 1},
            }},
        }


class _Repo:
    async def commit_interview_turn(self, **_kwargs):
        return {"committed": True, "idempotent": False}


class _Lease:
    released = False

    async def release(self):
        self.released = True


def _decode(line: str) -> dict:
    return json.loads(line.removeprefix("data: ").strip())


@pytest.mark.asyncio
async def test_event_generator_emits_execution_plan(monkeypatch):
    monkeypatch.setattr("ai.memory.should_skip_write", lambda *_args: True)
    lease = _Lease()
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = _Repo()

    lines = [
        line
        async for line in use_cases._event_generator(
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
    token_contents = [event["content"] for event in events if event["type"] == "token"]
    assert token_contents == ["下一题"]
    assert types[-1] == "done"
    plan = json.loads(events[0]["content"])
    assert [step["id"] for step in plan["steps"]] == [
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


class _CompletingRepo:
    def __init__(self):
        self.completed = False
        self.operations = []

    async def commit_interview_turn(self, **kwargs):
        if self.completed:
            raise AssertionError("completed 之后不得写入面试回合")
        self.operations.append((
            "turn",
            kwargs["user_content"],
            kwargs["assistant_content"],
            kwargs["question_count"],
        ))
        return {"committed": True, "idempotent": False}


class _CompletingGraph:
    async def astream_events(self, *_args, **_kwargs):
        # 模拟 LangGraph 事件投影相对节点执行乱序：先观察 summary，再观察 responder。
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "summary"},
            "data": {"output": {"question_count": 5, "max_questions": 5}},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "responder"},
            "data": {"output": {
                "messages": [{"role": "assistant", "content": "本轮面试结束"}],
                "question_count": 5,
                "max_questions": 5,
                "current_question_index": 5,
                "turn_state": {"state_version": 1},
            }},
        }


@pytest.mark.asyncio
async def test_final_response_and_progress_are_saved_before_session_completion(monkeypatch):
    """Summary projection order must not complete the session before final persistence."""
    monkeypatch.setattr("ai.memory.should_skip_write", lambda *_args: True)
    repo = _CompletingRepo()

    async def fake_handle_interview_complete(**kwargs):
        assert kwargs["session_id"] == "session-completing"
        assert kwargs["user_id"] == "user-1"
        repo.operations.append(("complete",))
        repo.completed = True

    monkeypatch.setattr(chat_stream, "handle_interview_complete", fake_handle_interview_complete)
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = repo

    lines = [
        line
        async for line in use_cases._event_generator(
            _CompletingGraph(),
            {
                "current_question_index": 4,
                "max_questions": 5,
                "api_config": {"fast": {"model": "test"}},
            },
            {},
            "session-completing",
            "我的最终回答",
            "user-1",
            _Lease(),
        )
    ]
    events = [_decode(line) for line in lines]
    state_updates = [
        json.loads(event["content"])
        for event in events
        if event["type"] == "state_update"
    ]

    assert repo.operations == [
        ("turn", "我的最终回答", "本轮面试结束", 5),
        ("complete",),
    ]
    assert state_updates == [{"question_count": 5, "max_questions": 5}]
    assert not [event for event in events if event["type"] == "error"]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_graph_summary_only_returns_completion_state(monkeypatch):
    from ai.agents.interview.interview_graph import node_summary
    from ai.workflows.interview.lifecycle import completion

    completion_calls = []

    async def fake_handle_interview_complete(**kwargs):
        completion_calls.append(kwargs)

    monkeypatch.setattr(completion, "handle_interview_complete", fake_handle_interview_complete)

    result = await node_summary({
        "session_id": "session-1",
        "user_id": "user-1",
        "run_id": "run-1",
        "question_count": 5,
        "max_questions": 5,
        "api_config": None,
    })

    assert result == {"messages": [], "question_count": 5, "max_questions": 5}
    assert completion_calls == []
