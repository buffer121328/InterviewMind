"""面试图 checkpoint 安全：水合凭据绝不进入持久化 state。"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

import ai.agents.interview.interview_graph as interview_graph
from ai.agents.interview.interview_graph import InterviewRuntimeContext


@pytest.mark.asyncio
async def test_checkpoint_never_contains_hydrated_api_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """runtime context 中的水合配置只存在内存，不写入 checkpoint 序列化结果。"""

    checkpointer = MemorySaver()

    async def fake_checkpointer():
        return checkpointer

    async def fake_planner(state, runtime):
        assert runtime.context.api_config is not None
        assert runtime.context.api_config["smart"]["api_key"] == "fixture-sk-checkpoint-123456"
        return {
            "interview_plan": [{"content": "介绍你自己", "topic": "intro"}],
            "current_question_index": 0,
            "question_count": 0,
            "follow_up_count": 0,
            "total_follow_up_count": 0,
            "turn_phase": "opening",
            "current_sub_question": None,
            "max_follow_ups": 2,
            "round_index": 1,
            "round_type": "tech_initial",
        }

    async def fake_responder(state, runtime):
        assert runtime.context.api_config is not None
        return {"messages": [], "max_questions": 1}

    monkeypatch.setattr(interview_graph, "get_checkpointer", fake_checkpointer)
    monkeypatch.setattr(interview_graph, "node_planner", fake_planner)
    monkeypatch.setattr(interview_graph, "node_responder", fake_responder)

    graph = await interview_graph.build_interview_graph("mock")
    api_config = {
        "smart": {"model": "fixture-model", "api_key": "fixture-sk-checkpoint-123456"},
    }
    inputs = {
        "messages": [],
        "resume_context": "resume",
        "job_description": "jd",
        "company_info": "未知",
        "mode": "mock",
        "session_id": "session-security-test",
        "user_id": "user-1",
        "run_id": "run-security-test",
        "max_questions": 1,
        "question_bank_count": 0,
        "round_index": 1,
        "round_type": "tech_initial",
    }
    config = {"configurable": {"thread_id": "interview:session-security-test:run:security"}}
    await graph.ainvoke(
        inputs,
        config=config,
        context=InterviewRuntimeContext(api_config=api_config),
    )

    checkpoints = [item async for item in checkpointer.alist(config)]
    serialized = repr(checkpoints)
    assert "fixture-sk-checkpoint-123456" not in serialized
    assert "api_config" not in serialized
    assert "api_key" not in serialized


def test_interview_state_schema_excludes_api_config() -> None:
    """图 state schema 不再声明任何凭据相关字段。"""

    assert "api_config" not in interview_graph.InterviewState.__required_keys__
    assert "api_config" not in interview_graph.InterviewState.__optional_keys__
