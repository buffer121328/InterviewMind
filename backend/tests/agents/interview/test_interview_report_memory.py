"""Regression tests for long-term memory generated from interview reports."""

from unittest.mock import AsyncMock

import pytest

from ai.workflows.interview.reports.memory import (
    build_report_memory_entries,
    persist_interview_report_memories,
)


def test_build_report_memory_entries_uses_persisted_report_artifacts():
    """Only completed interview weaknesses are in the long-term-memory scope."""
    entries = build_report_memory_entries(
        {
            "key_weaknesses": ["回答缺少量化结果"],
            "key_strengths": ["技术基础扎实"],
        },
        {
            "weakness_categories": [
                {"category": "沟通表达", "description": "表达结构不够清晰"},
            ],
            "improvement_actions": [
                {"action": "使用 STAR 结构完成三次复述", "priority": 1},
            ],
        },
    )

    assert entries == [
        ("weakness", "面试短板：回答缺少量化结果；表达结构不够清晰"),
    ]


@pytest.mark.asyncio
async def test_persist_report_memories_uses_request_scoped_mem0_config(monkeypatch):
    """A completed report persists only an owner-scoped weakness memory."""
    add_summary_memory = AsyncMock(return_value={"id": "memory-1"})

    class FakeMemoryService:
        is_enabled = True

    service = FakeMemoryService()
    service.add_summary_memory = add_summary_memory
    captured_configs: list[dict | None] = []

    async def fake_get_service(api_config=None):
        captured_configs.append(api_config)
        return service

    monkeypatch.setattr("ai.memory.get_agent_memory_service", fake_get_service)
    api_config = {"mem0_llm": {"model": "memory"}}

    written = await persist_interview_report_memories(
        user_id="user-1",
        session_id="session-1",
        profile={"key_weaknesses": ["系统设计"], "key_strengths": []},
        weakness_report={
            "weakness_categories": [],
            "improvement_actions": [{"action": "练习容量估算"}],
        },
        api_config=api_config,
    )

    assert written == 1
    assert captured_configs == [api_config]
    assert add_summary_memory.await_count == 1
    call = add_summary_memory.await_args_list[0]
    assert call.kwargs["user_id"] == "user-1"
    assert call.kwargs["session_id"] == "session-1"
    assert call.kwargs["memory_type"] == "weakness"
    assert call.kwargs["metadata"] == {
        "report_generated": True,
        "memory_source": "interview_weakness",
    }


def test_degraded_report_does_not_create_authoritative_memories():
    """Evidence-only fallback must not become long-term strengths or weaknesses."""
    entries = build_report_memory_entries(
        {
            "generation_mode": "degraded_evidence_only",
            "key_weaknesses": ["不应写入"],
            "key_strengths": ["不应写入"],
        },
        {
            "generation_mode": "degraded_evidence_only",
            "improvement_actions": [{"action": "不应写入"}],
        },
    )

    assert entries == []
