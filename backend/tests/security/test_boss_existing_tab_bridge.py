"""Tests for reusing an already-open Edge/Chrome BOSS tab through Apple events."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from integrations.boss import existing_tab_bridge as bridge_module
from integrations.boss.existing_tab_bridge import (
    BossExistingTabBridge,
    BossExistingTabError,
    BossTabExecution,
    BossTabStatus,
    boss_search_url_matches_intent,
    boss_existing_tab_poll_interval_seconds,
    build_boss_search_url,
    get_existing_tab_browser_target,
    normalize_existing_tab_browser_channel,
)


def make_card(index: int) -> dict[str, str]:
    """Build one official bounded BOSS card using real underscore/hyphen job-id characters."""
    return {
        "company_name": f"示例科技 {index}",
        "company_size_text": "已上市 互联网 100-499人",
        "job_title": f"Agent 工程师 {index}",
        "salary_text": "20-30K",
        "city": "深圳",
        "title_summary": "3-5年 本科",
        "job_description": "负责 Agent 产品及 Python 服务端开发工作",
        "source_url": f"https://www.zhipin.com/job_detail/card_{index}-real.html",
    }


def test_existing_tab_channel_normalization_uses_allowlist(monkeypatch):
    """Only Edge and Chrome aliases may reach the AppleScript application name."""
    monkeypatch.setenv("BOSS_BROWSER_CHANNEL", "edge")

    assert normalize_existing_tab_browser_channel(None) == "msedge"
    assert get_existing_tab_browser_target("chrome").app_name == "Google Chrome"
    with pytest.raises(BossExistingTabError, match="只支持"):
        normalize_existing_tab_browser_channel("chromium")


def test_setup_errors_use_actionable_conflict_status_instead_of_masked_server_error():
    """Permission and browser setup failures must survive the app's generic 5xx redaction."""
    error = BossExistingTabError("browser_javascript_disabled", "请开启浏览器设置")

    assert error.status_code == 409


def test_build_search_url_reuses_city_and_safe_filters_but_resets_page():
    """A new query preserves allowlisted filters without carrying pagination or tracking params."""
    target = build_boss_search_url(
        current_url=(
            "https://www.zhipin.com/web/geek/jobs?city=101280600&query=old"
            "&experience=104&page=3&ka=page-3"
        ),
        query="AI Agent / RAG",
        city=None,
    )
    parsed = urlparse(target)
    params = parse_qs(parsed.query)

    assert parsed.path == "/web/geek/jobs"
    assert params == {
        "city": ["101280600"],
        "jobType": ["1901"],
        "query": ["AI Agent / RAG"],
    }


@pytest.mark.parametrize(
    ("experience", "expected_code"),
    [
        ("any", None),
        ("no_experience", "101"),
        ("experience_unlimited", "101"),
        ("one_to_three", "104"),
    ],
)
def test_build_search_url_preserves_experience_intent(
    experience: str, expected_code: str | None
):
    """Only the four product choices may reach the BOSS URL, with no stale value reuse."""
    target = build_boss_search_url(
        current_url="https://www.zhipin.com/web/geek/jobs?city=101280600&experience=105",
        query="Agent",
        city=None,
        experience=experience,
    )
    params = parse_qs(urlparse(target).query)
    assert params.get("experience") == ([expected_code] if expected_code else None)


def test_build_search_url_rejects_blank_query_and_non_numeric_city():
    """The bridge must not navigate to a broad list or accept an arbitrary city fragment."""
    current = "https://www.zhipin.com/web/geek/jobs?city=101280600"

    with pytest.raises(BossExistingTabError, match="关键词不能为空"):
        build_boss_search_url(current_url=current, query="  ", city=None)
    with pytest.raises(BossExistingTabError, match="数字城市代码"):
        build_boss_search_url(current_url=current, query="Agent", city="深圳")


def test_search_result_url_must_match_target_query_and_explicit_city():
    """Visible stale cards from a previous URL must not complete the new capture request."""
    expected = "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent"

    assert boss_search_url_matches_intent(
        "https://www.zhipin.com/web/geek/jobs?query=agent&city=101280600&page=2",
        expected,
    )
    assert not boss_search_url_matches_intent(
        "https://www.zhipin.com/web/geek/jobs?city=101280600&query=python",
        expected,
    )
    assert not boss_search_url_matches_intent(
        "https://www.zhipin.com/web/geek/jobs?city=101010100&query=agent",
        expected,
    )


def test_poll_interval_has_hard_five_second_floor(monkeypatch):
    """Environment configuration cannot make job-list checks faster than five seconds."""
    monkeypatch.setenv("BOSS_CAPTURE_POLL_INTERVAL_SECONDS", "0.1")
    assert boss_existing_tab_poll_interval_seconds() == 5.0


@pytest.mark.asyncio
async def test_inspect_reuses_five_second_cache(monkeypatch):
    """Repeated status requests inside five seconds must not execute another DOM read."""
    bridge = BossExistingTabBridge()
    execute = AsyncMock(return_value=BossTabExecution(
        tab_id="edge-tab-7",
        result=json.dumps({
            "current_url": "https://www.zhipin.com/web/geek/jobs?query=agent",
            "page_status": "search_ready",
            "ready_state": "complete",
            "visible_card_count": 15,
        }),
    ))
    monkeypatch.setattr(bridge, "_execute_in_existing_tab", execute)

    first = await bridge.inspect("msedge")
    second = await bridge.inspect("msedge")

    assert first.visible_card_count == 15
    assert first.tab_id == "edge-tab-7"
    assert second == first
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_reuses_recent_connected_tab_without_a_second_dom_read(monkeypatch):
    """Clicking capture right after connect must reuse the cached tab and keep the five-second floor."""
    bridge = BossExistingTabBridge()
    target = get_existing_tab_browser_target("msedge")
    cached = BossTabStatus(
        success=True,
        browser_channel="msedge",
        browser_label="Microsoft Edge",
        connected=True,
        current_url="https://www.zhipin.com/web/geek/jobs?city=101280600&query=old",
        page_status="search_ready",
        ready_state="complete",
        visible_card_count=15,
        message="connected",
        tab_id="edge-tab-7",
    )
    bridge._status_cache[target.channel] = (bridge_module.monotonic(), cached)
    inspect = AsyncMock()
    monkeypatch.setattr(bridge, "_inspect_unlocked", inspect)
    monkeypatch.setattr(bridge, "_respect_action_spacing", AsyncMock())
    monkeypatch.setattr(bridge, "_navigate_existing_tab", AsyncMock(return_value="edge-tab-7"))
    monkeypatch.setattr(bridge, "_capture_unlocked", AsyncMock(return_value={
        "kind": "interviewmind-boss-dom-capture-v1",
        "tab_id": "edge-tab-7",
        "source_page_url": "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent&jobType=1901",
        "captured_at": "2026-07-30T00:00:00+00:00",
        "page_status": "search_ready",
        "ready_state": "complete",
        "cards": [make_card(1)],
    }))
    monkeypatch.setattr(
        bridge,
        "_enrich_captured_cards_unlocked",
        AsyncMock(return_value=([make_card(1)], 1, 0)),
    )
    monkeypatch.setattr(bridge_module.asyncio, "sleep", AsyncMock())

    result = await bridge.search_and_capture(query="agent", browser_channel="msedge")

    assert result["success"] is True
    inspect.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_normalizes_and_limits_twenty_real_job_links(monkeypatch):
    """One DOM response is bounded to twenty official cards and accepts '_'/'-' job ids."""
    bridge = BossExistingTabBridge()
    target = get_existing_tab_browser_target("msedge")
    execute = AsyncMock(return_value=BossTabExecution(
        tab_id="edge-tab-7",
        result=json.dumps({
            "kind": "interviewmind-boss-dom-capture-v1",
            "source_page_url": "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent",
            "captured_at": "2026-07-30T00:00:00+00:00",
            "page_status": "search_ready",
            "ready_state": "complete",
            "cards": [make_card(index) for index in range(1, 22)],
        }),
    ))
    monkeypatch.setattr(bridge, "_execute_in_existing_tab", execute)

    capture = await bridge._capture_unlocked(target, max_cards=20)

    assert len(capture["cards"]) == 20
    assert capture["cards"][0]["source_url"].endswith("card_1-real.html")
    assert capture["cards"][0]["company_size_text"] == "100-499人"
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_uses_browser_command_and_pins_tab_id(monkeypatch):
    """The browser exposes execute on the application command, not as a tab method."""
    bridge = BossExistingTabBridge()
    target = get_existing_tab_browser_target("msedge")
    run_applescript = AsyncMock(return_value=json.dumps({
        "tab_id": "edge-tab-7",
        "result": "zhipin.com",
    }))
    monkeypatch.setattr(bridge, "_run_applescript", run_applescript)

    result = await bridge._execute_in_existing_tab(
        target,
        "location.hostname",
        expected_tab_id="edge-tab-7",
    )

    script, expected_tab_id, javascript = run_applescript.await_args.args
    assert "browser.execute(selectedTab" in script
    assert "selectedTab.execute" not in script
    assert expected_tab_id == "edge-tab-7"
    assert javascript == "location.hostname"
    assert result == BossTabExecution(tab_id="edge-tab-7", result="zhipin.com")


def test_closed_or_changed_pinned_tab_stops_instead_of_selecting_another_tab():
    """A changed tab must fail closed so another open BOSS page is never captured accidentally."""
    target = get_existing_tab_browser_target("msedge")

    with pytest.raises(BossExistingTabError) as caught:
        BossExistingTabBridge._raise_for_marker("__PINNED_BOSS_TAB_NOT_FOUND__", target)

    assert caught.value.code == "boss_tab_changed"


@pytest.mark.asyncio
async def test_run_applescript_timeout_mentions_actual_launcher_app(monkeypatch):
    """Timeout guidance must cover the common PyCharm-vs-Terminal TCC mismatch."""
    bridge = BossExistingTabBridge()

    class HangingProcess:
        returncode = None
        stdout = None
        stderr = None

        def __init__(self) -> None:
            self.killed = False

        async def communicate(self):
            if self.killed:
                return b"", b""
            await bridge_module.asyncio.sleep(60)
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setattr(bridge_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        bridge_module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=HangingProcess()),
    )

    with pytest.raises(BossExistingTabError) as caught:
        await bridge._run_applescript(
            "return ''",
            timeout_seconds=0.001,
            timeout_context="测试阶段",
        )

    assert caught.value.code == "browser_automation_permission_timeout"
    assert "测试阶段" in caught.value.message
    assert "Terminal/iTerm" in caught.value.message
    assert "PyCharm" in caught.value.message
    assert "允许 Apple 事件中的 JavaScript" in caught.value.message


@pytest.mark.asyncio
async def test_search_and_capture_navigates_existing_tab_without_opening_browser(monkeypatch):
    """Search updates the selected existing tab and then hands bounded cards to the import flow."""
    bridge = BossExistingTabBridge()
    initial = BossTabStatus(
        success=True,
        browser_channel="msedge",
        browser_label="Microsoft Edge",
        connected=True,
        current_url="https://www.zhipin.com/web/geek/jobs?city=101280600&query=old",
        page_status="search_ready",
        ready_state="complete",
        visible_card_count=15,
        message="connected",
        tab_id="edge-tab-7",
    )
    inspect = AsyncMock(return_value=initial)
    spacing = AsyncMock()
    navigate = AsyncMock(return_value="edge-tab-7")
    capture = AsyncMock(return_value={
        "kind": "interviewmind-boss-dom-capture-v1",
        "tab_id": "edge-tab-7",
        "source_page_url": "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent&jobType=1901",
        "captured_at": "2026-07-30T00:00:00+00:00",
        "page_status": "search_ready",
        "ready_state": "complete",
        "cards": [make_card(1)],
    })
    enrich = AsyncMock(return_value=([make_card(1)], 1, 0))
    sleep = AsyncMock()
    monkeypatch.setattr(bridge, "_inspect_unlocked", inspect)
    monkeypatch.setattr(bridge, "_respect_action_spacing", spacing)
    monkeypatch.setattr(bridge, "_navigate_existing_tab", navigate)
    monkeypatch.setattr(bridge, "_capture_unlocked", capture)
    monkeypatch.setattr(bridge, "_enrich_captured_cards_unlocked", enrich)
    monkeypatch.setattr(bridge_module.asyncio, "sleep", sleep)

    result = await bridge.search_and_capture(
        query="agent",
        city=None,
        max_cards=20,
        browser_channel="msedge",
    )

    assert result["success"] is True
    assert result["cards"][0]["job_title"] == "Agent 工程师 1"
    target_url = navigate.await_args.args[1]
    assert navigate.await_args.kwargs["expected_tab_id"] == "edge-tab-7"
    assert capture.await_args.kwargs["expected_tab_id"] == "edge-tab-7"
    assert parse_qs(urlparse(target_url).query) == {
        "city": ["101280600"],
        "jobType": ["1901"],
        "query": ["agent"],
    }
    sleep.assert_awaited_once_with(5.0)


@pytest.mark.asyncio
async def test_open_job_reuses_pinned_existing_tab_and_rejects_external_url(monkeypatch):
    """打开岗位只能导航已识别的现有标签页，不能启动浏览器或接受外部链接。"""
    bridge = BossExistingTabBridge()
    status = BossTabStatus(
        success=True,
        browser_channel="msedge",
        browser_label="Microsoft Edge",
        connected=True,
        current_url="https://www.zhipin.com/web/geek/jobs?query=agent",
        page_status="search_ready",
        ready_state="complete",
        visible_card_count=3,
        message="connected",
        tab_id="edge-tab-7",
    )
    navigated_status = BossTabStatus(
        **{
            **status.as_dict(),
            "current_url": "https://www.zhipin.com/job_detail/card_1-real.html",
            "page_status": "job_detail",
            "tab_id": "edge-tab-7",
        }
    )
    inspect = AsyncMock(side_effect=[status, navigated_status])
    navigate = AsyncMock(return_value="edge-tab-7")
    monkeypatch.setattr(bridge, "_inspect_unlocked", inspect)
    monkeypatch.setattr(bridge, "_navigate_existing_tab", navigate)

    result = await bridge.open_job(
        "https://www.zhipin.com/job_detail/card_1-real.html",
        "msedge",
    )

    assert result["success"] is True
    assert navigate.await_args.kwargs == {
        "expected_tab_id": "edge-tab-7",
        "allow_job_detail": True,
    }
    with pytest.raises(BossExistingTabError, match="BOSS 官方岗位详情"):
        await bridge.open_job("https://example.com/job_detail/card_1-real.html", "msedge")


@pytest.mark.asyncio
async def test_send_message_uses_pinned_tab_and_requires_postcondition(monkeypatch):
    """发送只允许在锁定标签页执行一次，并以消息气泡出现作为成功后置条件。"""
    bridge = BossExistingTabBridge()
    status = BossTabStatus(
        success=True,
        browser_channel="msedge",
        browser_label="Microsoft Edge",
        connected=True,
        current_url="https://www.zhipin.com/web/geek/jobs?query=agent",
        page_status="search_ready",
        ready_state="complete",
        visible_card_count=3,
        message="connected",
        tab_id="edge-tab-7",
    )
    navigated_status = BossTabStatus(
        **{
            **status.as_dict(),
            "current_url": "https://www.zhipin.com/job_detail/card_1-real.html",
            "page_status": "job_detail",
            "tab_id": "edge-tab-7",
        }
    )
    inspect = AsyncMock(side_effect=[status, navigated_status])
    navigate = AsyncMock(return_value="edge-tab-7")
    execute = AsyncMock(side_effect=[
        BossTabExecution(tab_id="edge-tab-7", result=json.dumps({"status": "contact_clicked"})),
        BossTabExecution(tab_id="edge-tab-7", result=json.dumps({"status": "composer_ready"})),
        BossTabExecution(tab_id="edge-tab-7", result=json.dumps({"status": "send_clicked"})),
        BossTabExecution(tab_id="edge-tab-7", result=json.dumps({"status": "sent"})),
    ])
    sleep = AsyncMock()
    monkeypatch.setattr(bridge, "_inspect_unlocked", inspect)
    monkeypatch.setattr(bridge, "_navigate_existing_tab", navigate)
    monkeypatch.setattr(bridge, "_execute_in_existing_tab", execute)
    monkeypatch.setattr(bridge_module.asyncio, "sleep", sleep)

    result = await bridge.send_message(
        source_url="https://www.zhipin.com/job_detail/card_1-real.html",
        message_text="您好，我希望基于真实项目经验进一步沟通该岗位。",
        browser_channel="msedge",
    )

    assert result["success"] is True
    assert result["status"] == "sent"
    assert navigate.await_args.kwargs == {
        "expected_tab_id": "edge-tab-7",
        "allow_job_detail": True,
    }
    assert execute.await_count == 4
    assert all(
        call.kwargs["expected_tab_id"] == "edge-tab-7"
        for call in execute.await_args_list
    )
    assert "真实项目经验" not in str(result)


@pytest.mark.asyncio
async def test_send_message_marks_unverified_click_as_ambiguous(monkeypatch):
    """点击发送后无法观察到消息气泡时必须返回可能已执行，禁止自动重试。"""
    bridge = BossExistingTabBridge()
    status = BossTabStatus(
        success=True,
        browser_channel="chrome",
        browser_label="Google Chrome",
        connected=True,
        current_url="https://www.zhipin.com/job_detail/card_1-real.html",
        page_status="boss_page",
        ready_state="complete",
        visible_card_count=0,
        message="connected",
        tab_id="chrome-tab-1",
    )
    monkeypatch.setattr(bridge, "_inspect_unlocked", AsyncMock(return_value=status))
    monkeypatch.setattr(bridge, "_navigate_existing_tab", AsyncMock(return_value="chrome-tab-1"))
    monkeypatch.setattr(bridge_module.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(bridge, "_execute_in_existing_tab", AsyncMock(side_effect=[
        BossTabExecution(tab_id="chrome-tab-1", result=json.dumps({"status": "composer_ready"})),
        BossTabExecution(tab_id="chrome-tab-1", result=json.dumps({"status": "send_clicked"})),
        BossTabExecution(tab_id="chrome-tab-1", result=json.dumps({"status": "unverified"})),
    ]))

    with pytest.raises(BossExistingTabError) as caught:
        await bridge.send_message(
            source_url="https://www.zhipin.com/job_detail/card_1-real.html",
            message_text="您好，我希望基于自己的真实项目经验进一步沟通这个岗位和团队需求。",
            browser_channel="chrome",
        )

    assert caught.value.code == "message_send_unverified"
    assert caught.value.request_may_have_run is True


@pytest.mark.asyncio
async def test_send_message_stops_before_contact_when_navigation_changes_job(monkeypatch):
    """导航被站内重定向到其他岗位时，任何沟通点击都不得执行。"""
    bridge = BossExistingTabBridge()
    initial_status = BossTabStatus(
        success=True,
        browser_channel="chrome",
        browser_label="Google Chrome",
        connected=True,
        current_url="https://www.zhipin.com/web/geek/jobs?query=agent",
        page_status="search_ready",
        ready_state="complete",
        visible_card_count=2,
        message="connected",
        tab_id="chrome-tab-1",
    )
    redirected_status = BossTabStatus(
        **{
            **initial_status.as_dict(),
            "current_url": "https://www.zhipin.com/job_detail/other-job.html",
            "page_status": "job_detail",
            "tab_id": "chrome-tab-1",
        }
    )
    execute = AsyncMock()
    monkeypatch.setattr(
        bridge,
        "_inspect_unlocked",
        AsyncMock(side_effect=[initial_status, redirected_status]),
    )
    monkeypatch.setattr(
        bridge,
        "_navigate_existing_tab",
        AsyncMock(return_value="chrome-tab-1"),
    )
    monkeypatch.setattr(bridge, "_execute_in_existing_tab", execute)
    monkeypatch.setattr(bridge_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(BossExistingTabError) as caught:
        await bridge.send_message(
            source_url="https://www.zhipin.com/job_detail/card_1-real.html",
            message_text="您好，我希望基于自己的真实项目经验进一步沟通这个岗位和团队需求。",
            browser_channel="chrome",
        )

    assert caught.value.code == "job_navigation_mismatch"
    assert caught.value.request_may_have_run is False
    execute.assert_not_awaited()
