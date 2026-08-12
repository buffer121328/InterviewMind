"""聊天 SSE 应暴露可展示的执行计划和步骤状态。"""

import json

import pytest

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
            }},
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
        self.messages = []

    async def add_message(self, **kwargs):
        if self.completed:
            raise ValueError("面试已完成，不能继续提交回答")
        self.messages.append((kwargs["role"], kwargs["content"]))
        return None

    async def update_session(self, **_kwargs):
        return None


class _CompletingGraph:
    def __init__(self, repo: _CompletingRepo):
        self.repo = repo

    async def astream_events(self, *_args, **_kwargs):
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "responder"},
            "data": {"output": {
                "messages": [{"role": "assistant", "content": "本轮面试结束"}],
                "question_count": 5,
                "max_questions": 5,
                "current_question_index": 5,
            }},
        }
        self.repo.completed = True
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "summary"},
            "data": {"output": {"question_count": 5, "max_questions": 5}},
        }


@pytest.mark.asyncio
async def test_final_response_is_saved_before_summary_completes_session(monkeypatch):
    """The closing answer must be persisted before the summary node locks the session."""
    monkeypatch.setattr("ai.memory.should_skip_write", lambda *_args: True)
    repo = _CompletingRepo()
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = repo

    lines = [
        line
        async for line in use_cases._event_generator(
            _CompletingGraph(repo),
            {"current_question_index": 0, "max_questions": 5},
            {},
            "session-completing",
            "我的回答",
            "user-1",
            _Lease(),
        )
    ]
    events = [_decode(line) for line in lines]

    assert [item[0] for item in repo.messages] == ["user", "assistant"]
    assert repo.messages[-1] == ("assistant", "本轮面试结束")
    assert not [event for event in events if event["type"] == "error"]
    assert events[-1]["type"] == "done"
