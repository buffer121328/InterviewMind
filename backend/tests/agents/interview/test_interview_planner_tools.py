"""面试 Planner 可选工具的契约与降级测试。"""

import pytest

from ai.agents.interview.planning import planner


@pytest.mark.asyncio
async def test_planner_tool_selection_executes_allowlisted_fixture(monkeypatch):
    decisions = iter([
        planner.PlannerToolDecision(
            need_tool=True,
            tool_name="get_weakness_report",
            tool_args={},
            reason="需要确认未解决短板",
        ),
        planner.PlannerToolDecision(need_tool=False),
    ])

    async def fake_invoke_structured(**kwargs):
        return next(decisions)

    monkeypatch.setattr(planner, "invoke_structured", fake_invoke_structured)
    result = await planner._run_planner_tool_selection(
        resume="熟悉 Python",
        job_description="招聘后端工程师",
        round_type="tech_initial",
        round_index=2,
        previous_questions=[],
        previous_profile=None,
        weakness_report=None,
        retrieval_context=None,
        memory_context=None,
        api_config={},
        owner_id="eval-user:test",
        session_id="eval-session",
        planner_tool_fixtures={
            "get_weakness_report": {
                "arguments": {},
                "result": {"status": "available", "weakness_categories": ["缓存一致性"]},
            }
        },
        cache_scope="eval-session",
    )

    assert result["planner_tool_selections"][0]["tool"] == "get_weakness_report"
    assert result["planner_tool_selections"][0]["result"]["weakness_categories"] == ["缓存一致性"]


@pytest.mark.asyncio
async def test_planner_tool_selection_rejects_unknown_tool(monkeypatch):
    async def fake_invoke_structured(**kwargs):
        return planner.PlannerToolDecision(
            need_tool=True,
            tool_name="open_boss_job",
            tool_args={"job_id": 1},
        )

    monkeypatch.setattr(planner, "invoke_structured", fake_invoke_structured)
    result = await planner._run_planner_tool_selection(
        resume="熟悉 Python",
        job_description="招聘后端工程师",
        round_type="tech_initial",
        round_index=1,
        previous_questions=[],
        previous_profile=None,
        weakness_report=None,
        retrieval_context={"existing": True},
        memory_context=None,
        api_config={},
        owner_id="eval-user:test",
        session_id=None,
        planner_tool_fixtures={},
        cache_scope="eval-session",
    )

    assert result == {"existing": True}


@pytest.mark.asyncio
async def test_planner_tool_selection_degrades_when_tool_fails(monkeypatch):
    async def fake_invoke_structured(**kwargs):
        return planner.PlannerToolDecision(
            need_tool=True,
            tool_name="get_weakness_report",
            tool_args={},
        )

    monkeypatch.setattr(planner, "invoke_structured", fake_invoke_structured)
    result = await planner._run_planner_tool_selection(
        resume="熟悉 Python",
        job_description="招聘后端工程师",
        round_type="tech_initial",
        round_index=1,
        previous_questions=[],
        previous_profile=None,
        weakness_report=None,
        retrieval_context=None,
        memory_context=None,
        api_config={},
        owner_id="eval-user:test",
        session_id=None,
        planner_tool_fixtures={
            "get_weakness_report": {
                "arguments": {"unexpected": True},
                "result": {"status": "available"},
            }
        },
        cache_scope="eval-session",
    )

    assert result["planner_tool_selections"][0]["result"]["status"] == "degraded"
