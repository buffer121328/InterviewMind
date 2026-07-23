"""BOSS 确定性工作流测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from ai.tools import ToolExecutionGuard, ToolExecutionPolicy
from ai.agents.jobs.boss_agent import _build_boss_graph
from ai.tools.boss_tools import open_boss_search_page


@pytest.mark.asyncio
async def test_boss_tool_uses_shared_playwright_session():
    page_text = "BOSS直聘 招聘 " + "岗位信息" * 50
    with patch(
        "ai.workflows.jobs_support.job_capture_service._fetch_page_text_browser",
        new=AsyncMock(return_value=page_text),
    ) as fetch:
        result = await open_boss_search_page("Python", "上海", captcha_timeout=30)

    assert result == page_text
    fetch.assert_awaited_once()
    assert fetch.await_args.kwargs == {
        "headless": False,
        "manual_wait_seconds": 30,
    }
    assert "query=Python" in fetch.await_args.args[0]
    assert "city=%E4%B8%8A%E6%B5%B7" in fetch.await_args.args[0]


@pytest.mark.asyncio
async def test_boss_tool_reports_manual_verification():
    with patch(
        "ai.workflows.jobs_support.job_capture_service._fetch_page_text_browser",
        new=AsyncMock(return_value="请稍候，正在进行安全验证"),
    ):
        result = await open_boss_search_page("Python")

    assert result.startswith("CAPTCHA:")


@pytest.mark.asyncio
async def test_boss_graph_uses_fixed_route_and_only_processes_top_n():
    cards = [
        {"job_title": "A", "company_name": "甲", "preliminary_match_score": 90},
        {"job_title": "B", "company_name": "乙", "preliminary_match_score": 80},
        {"job_title": "C", "company_name": "丙", "preliminary_match_score": 70},
    ]
    guard = ToolExecutionGuard(ToolExecutionPolicy(max_calls=20, max_retries=0))

    with (
        patch("ai.tools.boss_tools.check_environment", new=AsyncMock(return_value="✅ 环境正常")) as env,
        patch("ai.tools.boss_tools.open_boss_search_page", new=AsyncMock(return_value="page")) as open_page,
        patch("ai.tools.boss_tools.extract_job_cards_from_page", new=AsyncMock(return_value=cards)) as extract,
        patch("ai.tools.boss_tools.score_jobs_by_match", new=AsyncMock(return_value=cards)) as score,
        patch("ai.tools.boss_tools.save_job_to_database", new=AsyncMock(side_effect=[
            {"success": True, "job_id": 1, "is_duplicate": False},
            {"success": True, "job_id": 2, "is_duplicate": False},
        ])) as save,
        patch("ai.tools.boss_tools.generate_job_assets", new=AsyncMock(return_value={"success": True})) as assets,
    ):
        graph = _build_boss_graph(
            user_id="user-1",
            resume_content="Python",
            api_config={"fast": {"api_key": "not-in-state"}},
            guard=guard,
            audit_events=[],
        ).compile()
        result = await graph.ainvoke({"query": "Python", "city": "上海", "top_n": 2})

    assert [item["card"]["job_title"] for item in result["processed"]] == ["A", "B"]
    assert guard.calls == 8
    env.assert_awaited_once()
    open_page.assert_awaited_once_with("Python", "上海")
    extract.assert_awaited_once()
    score.assert_awaited_once()
    assert save.await_count == 2
    assert assets.await_count == 2
    assert "api_config" not in result
    assert "page_text" not in result


@pytest.mark.asyncio
async def test_boss_graph_stops_after_environment_failure():
    guard = ToolExecutionGuard(ToolExecutionPolicy(max_calls=5))
    with (
        patch("ai.tools.boss_tools.check_environment", new=AsyncMock(return_value="环境问题: Chrome 未运行")),
        patch("ai.tools.boss_tools.open_boss_search_page", new=AsyncMock()) as open_page,
    ):
        result = await _build_boss_graph(
            user_id="user-1", resume_content="", api_config={}, guard=guard, audit_events=[]
        ).compile().ainvoke({"query": "Python", "city": "", "top_n": 2})

    assert result["error"].startswith("环境问题")
    open_page.assert_not_awaited()
