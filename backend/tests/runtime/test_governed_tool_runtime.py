"""Tests for registry-backed governed tool execution."""

import pytest

from ai.runtime.context import AgentContext
from ai.tools import GovernedToolRuntime, tool_catalog
from ai.tools.executor import ToolApprovalRequired, ToolExecutionGuard
from evaluation.extractors import EvaluationTraceCollector
from observability import evaluation_runtime_sink


def test_tool_catalog_is_deterministic_and_secret_free():
    catalog = tool_catalog()
    names = {(item["group"], item["name"]) for item in catalog}

    assert ("interview", "search_question_bank") in names
    assert ("resume", "match_jd") in names
    assert ("verification", "verify_claim_against_source") in names
    assert ("jobs", "open_boss_job") in names
    assert ("memory", "search_memory") in names
    assert all("resume_content" not in str(item) for item in catalog)
    assert all("api_key" not in str(item).lower() for item in catalog)


@pytest.mark.asyncio
async def test_runtime_uses_contract_permissions_and_guard_observations(monkeypatch):
    from ai.tools import memory_tools

    async def fake_search_memory(**kwargs):
        assert kwargs["user_id"] == "owner-1"
        assert kwargs["api_config"] == {"memory": "request"}
        return [{"memory": "bounded"}]

    monkeypatch.setattr(memory_tools, "search_memory", fake_search_memory)
    events: list[dict] = []
    runtime = GovernedToolRuntime(
        AgentContext(
            user_id="owner-1",
            api_config={"memory": "request"},
            permissions=frozenset({"memory.search"}),
        ),
        groups=("memory",),
        guard=ToolExecutionGuard(),
        audit_callback=events.append,
    )

    result = await runtime.execute("search_memory", {"query": "项目", "limit": 1})

    assert result == [{"memory": "bounded"}]
    assert [event["status"] for event in events] == ["requested", "started", "completed"]


@pytest.mark.asyncio
async def test_runtime_requires_confirmation_before_external_business_code(monkeypatch):
    from ai.tools import job_tools

    called = False

    async def fake_open(**_kwargs):
        nonlocal called
        called = True
        return {"success": True}

    monkeypatch.setattr(job_tools.jobs_use_cases, "open_job_in_existing_tab", fake_open)
    runtime = GovernedToolRuntime(
        AgentContext(user_id="owner-1", permissions=frozenset({"boss.job.open"})),
        groups=("jobs",),
    )

    with pytest.raises(ToolApprovalRequired):
        await runtime.execute("open_boss_job", {"job_id": 7})
    assert called is False


@pytest.mark.asyncio
async def test_evaluation_fixture_uses_governed_events_without_production_read(monkeypatch):
    from ai.tools import interview_tools

    called = False

    async def fail_production_read(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("fixture must prevent production profile reads")

    monkeypatch.setattr(interview_tools, "get_candidate_profile", fail_production_read)
    collector = EvaluationTraceCollector(evaluation_namespace="eval:fixture-run")
    runtime = GovernedToolRuntime(
        AgentContext(
            user_id="eval-user:fixture-run",
            runtime_data={
                "environment": "evaluation",
                "evaluation_tool_fixtures": {
                    "get_candidate_profile": {
                        "arguments": {},
                        "result": {"gap": "缓存穿透防护"},
                    }
                },
            },
            permissions=frozenset({"candidate.profile.read"}),
        ),
        groups=("interview",),
    )

    with evaluation_runtime_sink(collector.record_runtime_event):
        result = await runtime.execute("get_candidate_profile", group="interview")

    assert result == {"gap": "缓存穿透防护"}
    assert called is False
    assert len(collector.tool_calls) == 1
    assert collector.tool_calls[0].status.value == "completed"
    assert collector.tool_calls[0].simulated is True


@pytest.mark.asyncio
async def test_evaluation_fixture_rejects_nonmatching_tool_arguments():
    runtime = GovernedToolRuntime(
        AgentContext(
            user_id="eval-user:fixture-run",
            runtime_data={
                "environment": "evaluation",
                "evaluation_tool_fixtures": {
                    "search_question_bank": {
                        "arguments": {"query": "Redis"},
                        "result": [],
                    }
                },
            },
            permissions=frozenset({"question_bank.search"}),
        ),
        groups=("interview",),
    )

    with pytest.raises(ValueError, match="argument contract mismatch"):
        await runtime.execute(
            "search_question_bank", {"query": "PostgreSQL"}, group="interview"
        )
