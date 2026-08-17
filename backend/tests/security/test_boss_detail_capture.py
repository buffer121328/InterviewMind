"""Regression tests for safe BOSS detail enrichment and constrained search filters."""

from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from app.schemas.jobs.job_schemas import BossTabCaptureRequest
from integrations.boss import existing_tab_bridge as bridge_module
from integrations.boss.existing_tab_bridge import (
    BossExistingTabBridge,
    boss_search_url_matches_intent,
    build_boss_search_url,
    get_existing_tab_browser_target,
)


def _card(index: int) -> dict[str, str]:
    return {
        "company_name": f"示例科技 {index}",
        "company_size_text": "100-499人",
        "job_title": f"Agent 工程师 {index}",
        "salary_text": "20-30K",
        "city": "深圳",
        "title_summary": "本科",
        "job_description": f"搜索卡摘要 {index}",
        "source_url": f"https://www.zhipin.com/job_detail/card_{index}-real.html",
    }


def test_capture_request_defaults_to_any_experience_and_full_time() -> None:
    request = BossTabCaptureRequest(query="Agent")

    assert request.experience == "any"
    assert request.job_type == "full_time"
    with pytest.raises(ValidationError):
        BossTabCaptureRequest(query="Agent", experience="3_to_5")
    with pytest.raises(ValidationError):
        BossTabCaptureRequest(query="Agent", job_type="part_time")


def test_search_url_applies_only_requested_experience_and_full_time_filters() -> None:
    target = build_boss_search_url(
        current_url=(
            "https://www.zhipin.com/web/geek/jobs?city=101280600&query=old"
            "&experience=105&jobType=1902&industry=100020"
        ),
        query="AI Agent",
        city=None,
        experience="one_to_three",
        job_type="full_time",
    )

    assert parse_qs(urlparse(target).query) == {
        "city": ["101280600"],
        "experience": ["104"],
        "jobType": ["1901"],
        "industry": ["100020"],
        "query": ["AI Agent"],
    }
    default_target = build_boss_search_url(
        current_url=target,
        query="AI Agent",
        city="101280600",
        experience="any",
        job_type="full_time",
    )
    assert "experience" not in parse_qs(urlparse(default_target).query)


def test_search_intent_rejects_a_page_with_a_different_requested_filter() -> None:
    expected = "https://www.zhipin.com/web/geek/jobs?query=agent&experience=104&jobType=1901"

    assert boss_search_url_matches_intent(
        "https://www.zhipin.com/web/geek/jobs?query=agent&experience=104&jobType=1901",
        expected,
    )
    assert not boss_search_url_matches_intent(
        "https://www.zhipin.com/web/geek/jobs?query=agent&experience=105&jobType=1901",
        expected,
    )


@pytest.mark.asyncio
async def test_detail_enrichment_preserves_summary_for_missing_detail_and_restores_search_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = BossExistingTabBridge()
    target = get_existing_tab_browser_target("msedge")
    cards = [_card(1), _card(2)]
    search_url = "https://www.zhipin.com/web/geek/jobs?city=101280600&query=agent&jobType=1901"
    navigate = AsyncMock(return_value="edge-tab-7")
    capture_detail = AsyncMock(side_effect=[
        {
            "status": "detail_ready",
            "current_url": cards[0]["source_url"],
            "job_description": "详情页职责与技术要求。" * 50,
        },
        {
            "status": "detail_loading",
            "current_url": cards[1]["source_url"],
            "job_description": "",
        },
    ])
    monkeypatch.setattr(bridge, "_navigate_existing_tab", navigate)
    monkeypatch.setattr(bridge, "_capture_job_detail_unlocked", capture_detail)
    monkeypatch.setattr(bridge, "_respect_action_spacing", AsyncMock())
    monkeypatch.setattr(bridge_module.asyncio, "sleep", AsyncMock())

    enriched, enriched_count, fallback_count = await bridge._enrich_captured_cards_unlocked(
        target,
        cards=cards,
        search_url=search_url,
        expected_tab_id="edge-tab-7",
    )

    assert enriched[0]["job_description"].startswith("详情页职责与技术要求")
    assert enriched[1]["job_description"] == "搜索卡摘要 2"
    assert enriched_count == 1
    assert fallback_count == 1
    assert navigate.await_args_list[-1].args[1] == search_url
    assert navigate.await_args_list[-1].kwargs == {
        "expected_tab_id": "edge-tab-7",
        "allow_job_detail": False,
        "activate": True,
    }
