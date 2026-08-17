"""Phase 2 Planner and text-runtime context governance acceptance tests."""

from __future__ import annotations

import pytest

from ai.agents.interview.interview_runtime import InterviewRuntime
from ai.agents.interview.planning import planner as interview_planner
from ai.agents.interview.planning.context import (
    assemble_planner_context,
    build_candidate_interview_facts,
    build_previous_round_digest,
    clear_interview_fact_cache,
)
from ai.runtime.execution.deadlines import TaskDeadline
from app.schemas.interview.interview import EvaluatingOutput
from app.schemas.llm_outputs import PlanOutput


def _plan_output(count: int) -> PlanOutput:
    """Build a valid model plan with deterministic unique questions."""
    return PlanOutput.model_validate({
        "questions": [
            {
                "id": index + 1,
                "topic": f"主题{index + 1}",
                "content": f"请说明第 {index + 1} 个项目决策及其验证结果。",
                "type": "tech",
                "sources": [],
            }
            for index in range(count)
        ]
    })


def test_compact_facts_keep_only_explicit_resume_lines_and_invalidate_on_source_change():
    """Facts remain verbatim and source fingerprints change with the resume version."""
    first = build_candidate_interview_facts(
        "# 技能\n熟悉 Python 和 FastAPI\n# 项目经历\n负责订单平台，吞吐提升 30%"
    )
    second = build_candidate_interview_facts(
        "# 技能\n熟悉 Python 和 FastAPI\n# 项目经历\n负责订单平台，吞吐提升 40%"
    )

    assert "熟悉 Python 和 FastAPI" in first.core_skills
    assert any("30%" in item for item in first.quantified_results)
    assert first.experience_gaps == []
    assert first.source_fingerprint != second.source_fingerprint


def test_previous_round_digest_uses_fingerprints_and_explicit_profile_outputs():
    """Cross-round digest carries exact prohibited questions without inventing candidate facts."""
    digest = build_previous_round_digest(
        ["请介绍订单项目"],
        {"skill_tags": ["FastAPI"], "key_strengths": ["性能分析清晰"]},
        {"weakness_categories": [{"category": "项目表达", "description": "量化不足"}]},
        "上一轮已完成基础面",
    )

    assert digest.question_fingerprints
    assert digest.prohibited_exact_questions == ["请介绍订单项目"]
    assert digest.verified_strengths == ["性能分析清晰"]
    assert any("量化不足" in item for item in digest.unresolved_weaknesses)


def test_planner_context_is_owner_scoped_budgeted_and_auditable():
    """Planner required sources win budget and the audit contains fingerprints rather than raw text."""
    clear_interview_fact_cache()
    bundle = assemble_planner_context(
        owner_id="user-1",
        cache_scope="series-1",
        resume="# 项目经历\n" + "负责平台性能治理，延迟下降 30%\n" * 300,
        job_description="必须熟悉 Python；负责接口性能与稳定性\n" * 200,
        company_info="示例公司",
        round_index=2,
        round_type="tech_deep",
        max_questions=20,
        strategy_focus="项目深挖",
        requirements="必须恰好生成20题",
        previous_questions=["请介绍你的项目"],
        previous_profile={"skill_tags": ["Python"]},
        weakness_report=None,
        previous_summary=None,
        retrieval_context={"rag_evidences": [{"evidence": "题库证据" * 500}]},
        memory_context="长期记忆" * 1000,
    )

    assert bundle.assembled.input_chars <= 10_000
    assert {"round_rules", "job_description", "resume"}.issubset(
        {item["name"] for item in bundle.assembled.source_audit if item["included_chars"]}
    )
    assert bundle.assembled.content_fingerprint
    assert "负责平台性能治理" not in bundle.assembled.model_event_fields()["input_fingerprint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_count", [0, 5, 19, 20, 25])
async def test_planner_normalizes_any_model_count_to_twenty(monkeypatch, model_count):
    """The second-round plan is exactly 20 questions for empty, partial, exact, or excessive output."""
    async def fake_invoke_structured(**_kwargs):
        return _plan_output(model_count)

    monkeypatch.setattr(interview_planner, "invoke_structured", fake_invoke_structured)
    plan = await interview_planner.generate_interview_plan(
        resume="候选人简历",
        job_description="目标 JD",
        company_info="目标公司",
        max_questions=20,
        api_config={},
        round_type="tech_deep",
        round_index=2,
        owner_id="user-1",
        cache_scope="series-1",
    )

    assert len(plan) == 20
    assert [item["id"] for item in plan] == list(range(1, 21))
    assert len({interview_planner._normalize_question_key(item["content"]) for item in plan}) == 20


@pytest.mark.asyncio
async def test_planner_uses_shared_deadline_and_context_metadata(monkeypatch):
    """Planner sends one deadline and safe source audit through the unified model helper."""
    captured = {}

    async def fake_invoke_structured(**kwargs):
        captured.update(kwargs)
        return _plan_output(2)

    monkeypatch.setattr(interview_planner, "invoke_structured", fake_invoke_structured)
    monkeypatch.setattr(
        interview_planner,
        "get_settings",
        lambda: type("Settings", (), {"interview_plan_timeout_seconds": 7.5})(),
    )
    await interview_planner.generate_interview_plan(
        resume="# 技能\nPython\n" + "项目证据\n" * 2000,
        job_description="必须熟悉 FastAPI",
        company_info="公司",
        max_questions=2,
        api_config={},
        owner_id="user-1",
        cache_scope="series-1",
    )

    assert isinstance(captured["deadline"], TaskDeadline)
    assert captured["deadline"].total_timeout == 7.5
    assert captured["call_metadata"]["source_breakdown"]
    assert "input_fingerprint" in captured["call_metadata"]


@pytest.mark.asyncio
async def test_runtime_truncates_long_answer_but_keeps_current_and_next_question():
    """Overlong answers are audited and cannot evict authoritative turn state."""
    captured = {}

    async def invoker(prompt, output_model, *, deadline=None, call_metadata=None):
        captured.update(
            prompt=prompt,
            output_model=output_model,
            deadline=deadline,
            call_metadata=call_metadata,
        )
        return EvaluatingOutput.model_validate({
            "evaluation_notes": "回答可推进",
            "action": "advance",
            "content": "进入下一题",
            "need_tool": False,
        })

    runtime = InterviewRuntime(
        {
            "interview_plan": [
                {"content": "当前题：解释事件循环", "type": "tech", "followups": []},
                {"content": "下一题：说明并发控制", "type": "tech"},
            ],
            "current_question_index": 0,
            "turn_phase": "feedback",
            "messages": [{"role": "user", "content": "回答证据" * 3000}],
            "memory_context": "记忆" * 1000,
        },
        invoker,
    )
    result = await runtime.run()

    assert result["current_question_index"] == 1
    assert "当前题：解释事件循环" in captured["prompt"]
    assert "下一题：说明并发控制" in captured["prompt"]
    assert "answer" in captured["call_metadata"]["truncated_sources"]
    assert isinstance(captured["deadline"], TaskDeadline)


def test_runtime_tool_context_prefers_success_summary_over_raw_payload():
    """Large tool payloads expose bounded success summaries instead of unbounded raw results."""
    runtime = InterviewRuntime({"interview_plan": []}, lambda *_args, **_kwargs: None)
    runtime.tool_results = {
        "search_question_bank": {
            "summary": "找到三道高相关并发题",
            "content": "原始题库正文" * 1000,
            "internal_id": "should-not-appear",
        }
    }

    rendered = runtime._format_tool_results()

    assert "找到三道高相关并发题" in rendered
    assert "should-not-appear" not in rendered
    assert len(rendered) < 800
