"""ATDD contracts for Phase 5 secondary agents and external-I/O degradation."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_greeting_receives_only_five_highlights_and_rejects_unsupported_claims(monkeypatch):
    """Greeting accepts direct highlights only and rejects unsupported model claims."""
    from ai.agents.jobs import greeting_generator as generator

    captured: dict[str, Any] = {}

    async def fake_invoke(prompt, output_model, *args, **kwargs):
        from ai.agents.jobs.greeting_generator import GreetingReflectionOutput

        if output_model is GreetingReflectionOutput:
            return GreetingReflectionOutput(
                approved=True,
                truthfulness_pass=True,
                relevance_pass=True,
                length_pass=True,
                issues=[],
            )
        captured["prompt"] = prompt
        base_message = (
            "您好，我关注到贵司正在招聘后端工程师。我希望结合自己已有的真实项目经历，"
            "说明在服务开发、接口设计、问题排查和协作交付方面与岗位要求的对应关系，"
            "也愿意进一步介绍我承担的职责、技术取舍及可验证结果。希望有机会沟通团队当前重点与岗位预期。"
        )
        return output_model(greetings=[
            {
                "tone": "professional",
                "message_text": base_message,
                "highlights_used": ["从未提供的亿级流量经验"],
                "risk_notes": "",
            },
            {
                "tone": "technical",
                "message_text": base_message,
                "highlights_used": ["真实亮点-0"],
                "risk_notes": "",
            },
            {
                "tone": "result_oriented",
                "message_text": base_message,
                "highlights_used": ["真实亮点-1"],
                "risk_notes": "",
            },
        ])

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", fake_invoke)
    highlights = [f"真实亮点-{index}" for index in range(6)]
    greetings = await generator.generate_greetings(
        company_name="示例公司",
        job_title="后端工程师",
        jd_summary="Python 服务开发",
        candidate_highlights=highlights,
    )

    assert "真实亮点-4" in captured["prompt"]
    assert "真实亮点-5" not in captured["prompt"]
    assert "兜底文案" in greetings[0]["risk_notes"]


@pytest.mark.asyncio
async def test_ability_scores_are_local_and_only_five_profiles_reach_model(monkeypatch):
    """Model failure cannot change deterministic scores and profiles six/seven stay out of prompt."""
    from ai.workflows.analysis.ability_service import AbilityAnalysisService

    captured: dict[str, str] = {}

    async def fail_narrative(prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        raise RuntimeError("narrative unavailable")

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", fail_narrative)
    scores = [10, 8, 6, 4, 2, 1, 0]
    profiles = []
    for index, score in enumerate(scores):
        dimension = {"score": score, "evidence": f"evidence-{index}"}
        profiles.append({
            **{
                name: dict(dimension)
                for name in (
                    "professional_competence",
                    "execution_results",
                    "logic_problem_solving",
                    "communication",
                    "growth_potential",
                    "collaboration",
                )
            },
            "skill_tags": [f"skill-{index}", "PROFILE_SIX_PRIVATE" if index == 5 else ""],
            "total_questions_analyzed": 2,
        })

    profile = await AbilityAnalysisService()._aggregate_profiles_with_weights(profiles)
    expected = (10 * 1.0 + 8 * 0.85 + 6 * 0.7 + 4 * 0.55 + 2 * 0.4) / 3.5

    assert profile.professional_competence.score == pytest.approx(expected, abs=0.01)
    assert profile.professional_competence.trend == "improving"
    assert profile.total_questions_analyzed == 10
    assert "PROFILE_SIX_PRIVATE" not in captured["prompt"]


def test_material_ranking_enforces_local_top_k_and_per_item_budget():
    """Candidate material selection is bounded before model prompt construction."""
    from ai.agents.resume.resume_assembler import rank_materials_for_jd
    from app.config import get_settings

    materials = [
        {
            "id": index,
            "material_type": "project",
            "title": "Python 订单平台" if index % 2 == 0 else "其他经历",
            "content": ("Python FastAPI " if index % 2 == 0 else "普通内容 ") + "X" * 3000,
            "tags": ["Python"] if index % 2 == 0 else [],
            "importance_score": index / 20,
            "confidence_score": 0.8,
            "is_verified": index % 3 == 0,
        }
        for index in range(12)
    ]

    ranked = rank_materials_for_jd("需要 Python FastAPI 订单系统经验", materials, limit=50)

    assert len(ranked) == get_settings().resume_material_max_items
    assert all(len(item["content"]) <= get_settings().resume_material_item_max_chars for item in ranked)
    assert all(item["id"] % 2 == 0 for item in ranked[:4])


@pytest.mark.asyncio
async def test_project_rewrite_has_independent_budgets_and_marks_inference_for_review(monkeypatch):
    """Project/JD contexts are separately bounded and inferred content stays reviewable."""
    from ai.agents.resume import project_rewriter

    captured: dict[str, str] = {}

    class Response:
        content = (
            '{"rewritten_content":"重写草稿","rewrite_reason":"结构优化",'
            '"suggested_data_points":[],"possible_followup_questions":[],'
            '"should_update_material":true,"inferred_content":["主导架构"]}'
        )

    async def fake_invoke(messages, *_args, **_kwargs):
        captured["prompt"] = messages[0].content
        return Response()

    monkeypatch.setattr(project_rewriter.llms, "invoke_text", fake_invoke)
    project = "PROJECT_HEAD" + "A" * 2900 + "PROJECT_MIDDLE_MARKER" + "A" * 3100 + "PROJECT_TAIL"
    jd = "JD_HEAD" + "B" * 1400 + "JD_MIDDLE_MARKER" + "B" * 1600 + "JD_TAIL"
    result = await project_rewriter.rewrite_project(
        project_content=project,
        project_title="订单平台",
        rewrite_mode="jd_customize",
        job_description=jd,
    )

    assert "PROJECT_MIDDLE_MARKER" not in captured["prompt"]
    assert "JD_MIDDLE_MARKER" not in captured["prompt"]
    assert result["requires_user_confirmation"] is True
    assert result["review_notes"]


@pytest.mark.asyncio
async def test_mem0_timeout_degrades_to_empty_with_external_timeout_category(monkeypatch):
    """A mem0 timeout returns immediately as empty evidence and never exposes query text in events."""
    from ai.memory import service as memory_module

    events: list[dict[str, Any]] = []

    async def timeout_call(*_args, **_kwargs):
        raise TimeoutError("slow mem0")

    monkeypatch.setattr(memory_module, "_run_mem0_call", timeout_call)
    monkeypatch.setattr(
        memory_module,
        "record_external_io_event",
        lambda event: events.append(event.to_local_payload()),
    )
    service = memory_module.AgentMemoryService({})
    service._memory = SimpleNamespace(search=lambda **_kwargs: [])
    service._enabled = True

    result = await service.search_memories(user_id="owner-a", query="PRIVATE QUERY")

    assert result == []
    assert events[-1]["event_type"] == "external_io.failed"
    assert events[-1]["status"] == "failed"
    assert events[-1]["error_category"] == "external_io_timeout"
    assert "PRIVATE QUERY" not in str(events)


@pytest.mark.asyncio
async def test_vector_search_timeout_degrades_without_blocking_other_retrieval(monkeypatch):
    """Vector search has its own deadline and a timeout leaves the non-vector path usable."""
    from ai.agents.interview import interview_rag as rag
    from ai.agents.interview.interview_rag_models import RetrievalQuery

    events: list[dict[str, Any]] = []

    class Repo:
        async def search_structured(self, **_kwargs):
            return []

        async def search_by_text(self, **_kwargs):
            return []

        async def search_by_vector(self, **_kwargs):
            await asyncio.sleep(0.05)
            return []

    async def fake_embedding(*_args, **_kwargs):
        return [0.1, 0.2]

    monkeypatch.setattr("ai.rag.embedding_service.generate_embedding", fake_embedding)
    monkeypatch.setattr(rag, "VECTOR_ENABLED", True)
    monkeypatch.setattr(rag, "get_settings", lambda: SimpleNamespace(vector_search_timeout_seconds=0.001))
    monkeypatch.setattr(
        rag,
        "record_external_io_event",
        lambda event: events.append(event.to_local_payload()),
    )

    result = await rag._retrieve_queries(
        repo=Repo(),
        user_id="owner-a",
        queries=[RetrievalQuery(text="Python backend query long enough")],
    )

    assert result == []
    vector_event = next(
        event for event in events
        if event.get("operation") == "rag.search_vector" and event.get("status") == "failed"
    )
    assert vector_event["status"] == "failed"
    assert vector_event["error_category"] == "external_io_timeout"


@pytest.mark.asyncio
async def test_report_memory_entries_are_written_in_parallel(monkeypatch):
    """Optional report-memory writes share latency and cannot serialize the report tail."""
    from ai.workflows.interview.report_memory import persist_interview_report_memories

    active = 0
    max_active = 0
    both_started = asyncio.Event()

    class Service:
        is_enabled = True

        async def add_summary_memory(self, **_kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if active >= 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.5)
            active -= 1
            return {"id": "memory"}

    async def get_service(_api_config=None):
        return Service()

    monkeypatch.setattr("ai.memory.get_agent_memory_service", get_service)
    written = await persist_interview_report_memories(
        user_id="owner-a",
        session_id="session-a",
        profile={"key_weaknesses": ["系统设计"], "key_strengths": []},
        weakness_report={"weakness_categories": [], "improvement_actions": [{"action": "练习容量估算"}]},
        api_config=None,
    )

    assert written == 2
    assert max_active == 2
