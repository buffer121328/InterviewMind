"""简历 LangGraph 编排、安全上下文和缓存测试。"""

import asyncio

import pytest
from langgraph.cache.memory import InMemoryCache
from langgraph.checkpoint.memory import MemorySaver

import app.agents.resume.resume_orchestrator as orchestrator


def _initial_state() -> dict:
    return {
        "resume_content": "Python 后端开发，熟悉 FastAPI",
        "job_description": "招聘 Python 后端开发",
        "user_id": "user-1",
        "change_items": [],
        "assembled_resume": "",
        "confirmation_items": [],
        "retry_guidance": "",
        "retry_count": 0,
        "trace": [],
        "errors": [],
    }


def _patch_remaining_stages(monkeypatch) -> None:
    async def stage3(state):
        state.change_items = [{"optimized_text": "Python 后端开发", "confidence": 0.9}]
        return state

    async def stage4(state):
        state.assembled_resume = "Python 后端开发"
        return state

    async def fact(state):
        state.fact_check_result = {"overall_risk": "low", "total_risks": 0}
        return state

    async def judge(state):
        state.judge_result = {"passed": True, "decision": "pass"}
        return state

    async def confirm(state):
        state.confirmation_items = []
        return state

    monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", stage3)
    monkeypatch.setattr(orchestrator, "stage4_assemble", stage4)
    monkeypatch.setattr(orchestrator, "stage5_fact_check", fact)
    monkeypatch.setattr(orchestrator, "stage5_quality_judge", judge)
    monkeypatch.setattr(orchestrator, "stage6_confirmation_prep", confirm)


@pytest.mark.asyncio
async def test_stage1_and_stage2_start_in_parallel(monkeypatch):
    stage1_started = asyncio.Event()
    stage2_started = asyncio.Event()

    async def stage1(state):
        stage1_started.set()
        await asyncio.wait_for(stage2_started.wait(), timeout=0.5)
        state.jd_analysis = {"match_score": 90}
        return state

    async def stage2(state, session_ids=None, include_profile=False):
        stage2_started.set()
        await asyncio.wait_for(stage1_started.wait(), timeout=0.5)
        state.material_pool = {"resume": state.resume_content}
        return state

    monkeypatch.setattr(orchestrator, "stage1_jd_analysis", stage1)
    monkeypatch.setattr(orchestrator, "stage2_material_selection", stage2)
    _patch_remaining_stages(monkeypatch)

    graph = orchestrator._build_resume_graph().compile(cache=InMemoryCache())
    result = await graph.ainvoke(
        _initial_state(), context=orchestrator.ResumeRuntimeContext()
    )

    assert result["jd_analysis"]["match_score"] == 90
    assert result["material_pool"]["resume"] == _initial_state()["resume_content"]


@pytest.mark.asyncio
async def test_deterministic_nodes_are_cached_between_runs(monkeypatch):
    calls = {"stage1": 0, "fact": 0}

    async def stage1(state):
        calls["stage1"] += 1
        state.jd_analysis = {"match_score": 90}
        return state

    async def stage2(state, session_ids=None, include_profile=False):
        state.material_pool = {"resume": state.resume_content}
        return state

    async def fact(state):
        calls["fact"] += 1
        state.fact_check_result = {"overall_risk": "low", "total_risks": 0}
        return state

    monkeypatch.setattr(orchestrator, "stage1_jd_analysis", stage1)
    monkeypatch.setattr(orchestrator, "stage2_material_selection", stage2)
    _patch_remaining_stages(monkeypatch)
    monkeypatch.setattr(orchestrator, "stage5_fact_check", fact)

    graph = orchestrator._build_resume_graph().compile(cache=InMemoryCache())
    for _ in range(2):
        await graph.ainvoke(_initial_state(), context=orchestrator.ResumeRuntimeContext())

    assert calls == {"stage1": 1, "fact": 1}


@pytest.mark.asyncio
async def test_api_config_is_not_written_to_checkpoint(monkeypatch):
    async def stage1(state):
        assert state.api_config == {"api_key": "top-secret"}
        state.jd_analysis = {"match_score": 90}
        return state

    async def stage2(state, session_ids=None, include_profile=False):
        state.material_pool = {"resume": state.resume_content}
        return state

    monkeypatch.setattr(orchestrator, "stage1_jd_analysis", stage1)
    monkeypatch.setattr(orchestrator, "stage2_material_selection", stage2)
    _patch_remaining_stages(monkeypatch)

    checkpointer = MemorySaver()
    graph = orchestrator._build_resume_graph().compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "resume-security-test"}}
    await graph.ainvoke(
        _initial_state(),
        config=config,
        context=orchestrator.ResumeRuntimeContext(api_config={"api_key": "top-secret"}),
    )

    checkpoints = [item async for item in checkpointer.alist(config)]
    serialized = repr(checkpoints)
    assert "top-secret" not in serialized
    assert "api_config" not in serialized



@pytest.mark.asyncio
async def test_balanced_mode_uses_agent_rewrite_node(monkeypatch):
    calls = {"agent": 0, "legacy": 0}

    async def stage1(state):
        state.jd_analysis = {"match_score": 90}
        return state

    async def stage2(state, session_ids=None, include_profile=False):
        state.material_pool = {"resume": state.resume_content}
        return state

    async def agent_stage(state, mode="balanced"):
        calls["agent"] += 1
        assert mode == "balanced"
        state.change_items = [{"optimized_text": "agent", "confidence": 0.9}]
        return state

    async def legacy_stage(state):
        calls["legacy"] += 1
        state.change_items = [{"optimized_text": "legacy", "confidence": 0.9}]
        return state

    monkeypatch.setattr(orchestrator, "stage1_jd_analysis", stage1)
    monkeypatch.setattr(orchestrator, "stage2_material_selection", stage2)
    monkeypatch.setattr(orchestrator, "stage3_rewrite_agent", agent_stage)
    monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", legacy_stage)
    _patch_remaining_stages(monkeypatch)
    monkeypatch.setattr(orchestrator, "stage3_rewrite_agent", agent_stage)
    monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", legacy_stage)

    graph = orchestrator._build_resume_graph().compile(cache=InMemoryCache())
    result = await graph.ainvoke(
        _initial_state(), context=orchestrator.ResumeRuntimeContext(mode="balanced")
    )

    assert calls == {"agent": 1, "legacy": 0}
    assert result["change_items"][0]["optimized_text"] == "agent"


@pytest.mark.asyncio
async def test_quality_mode_uses_legacy_rewrite_node(monkeypatch):
    calls = {"agent": 0, "legacy": 0}

    async def stage1(state):
        state.jd_analysis = {"match_score": 90}
        return state

    async def stage2(state, session_ids=None, include_profile=False):
        state.material_pool = {"resume": state.resume_content}
        return state

    async def agent_stage(state, mode="balanced"):
        calls["agent"] += 1
        state.change_items = [{"optimized_text": "agent", "confidence": 0.9}]
        return state

    async def legacy_stage(state):
        calls["legacy"] += 1
        state.change_items = [{"optimized_text": "legacy", "confidence": 0.9}]
        return state

    monkeypatch.setattr(orchestrator, "stage1_jd_analysis", stage1)
    monkeypatch.setattr(orchestrator, "stage2_material_selection", stage2)
    monkeypatch.setattr(orchestrator, "stage3_rewrite_agent", agent_stage)
    monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", legacy_stage)
    _patch_remaining_stages(monkeypatch)
    monkeypatch.setattr(orchestrator, "stage3_rewrite_agent", agent_stage)
    monkeypatch.setattr(orchestrator, "stage3_custom_rewrite", legacy_stage)

    graph = orchestrator._build_resume_graph().compile(cache=InMemoryCache())
    result = await graph.ainvoke(
        _initial_state(), context=orchestrator.ResumeRuntimeContext(mode="quality")
    )

    assert calls == {"agent": 0, "legacy": 1}
    assert result["change_items"][0]["optimized_text"] == "legacy"
