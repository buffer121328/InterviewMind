"""Regression tests for parallel multi-reviewer session report analysis."""

import asyncio

import pytest

from ai.workflows.analysis.analysis_service import SessionReportAnalysisService
from app.schemas.llm_outputs import SessionInterviewReportOutput, WeaknessReportOutput


def _combined_output() -> SessionInterviewReportOutput:
    """Build a compact valid consensus-output fixture."""
    dimension = {
        "score": 8,
        "evidence": "回答证据 [Q1]",
        "reason": "能够说明关键取舍 [Q1]",
        "better_answer_example": "补充真实指标和复盘",
        "improvement_tip": "使用 STAR 结构",
    }
    return SessionInterviewReportOutput.model_validate({
        "candidate_profile": {
            "professional_competence": dimension,
            "execution_results": dimension,
            "logic_problem_solving": dimension,
            "communication": dimension,
            "growth_potential": dimension,
            "collaboration": dimension,
            "skill_tags": ["FastAPI"],
            "key_strengths": ["技术取舍清晰 [Q1]"],
            "key_weaknesses": ["结果量化不足 [Q1]"],
        },
        "weakness_report": {
            "weakness_categories": [
                {"category": "项目表达", "description": "结果证据不足 [Q1]", "severity": "medium"},
            ],
            "question_failures": [],
            "improvement_actions": [],
            "recommended_questions": [],
            "priority_order": ["项目表达"],
        },
    })


@pytest.mark.asyncio
async def test_session_analysis_runs_four_parallel_reviewers_then_reduces(monkeypatch):
    """All four Send branches start independently before the consensus reducer runs."""
    from ai.workflows.analysis.reviewers.multi_reviewer import ReviewerAssessment

    reviewer_started: list[str] = []
    all_started = asyncio.Event()
    channels: dict[str, tuple[str, float]] = {}
    reducer_calls = 0

    async def invoke(*, output_model, call_metadata, channel, temperature, **_kwargs):
        nonlocal reducer_calls
        if output_model is ReviewerAssessment:
            perspective = call_metadata["review_perspective"]
            reviewer_started.append(perspective)
            channels[perspective] = (channel, temperature)
            if len(reviewer_started) == 4:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return ReviewerAssessment(
                perspective=perspective,
                score=8,
                dimension_scores={"communication": 8},
                strengths=[f"{perspective} 优势"],
                concerns=[],
                evidence_refs=["Q1"],
                confidence=0.8,
            )
        reducer_calls += 1
        assert len(reviewer_started) == 4
        return _combined_output()

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", invoke)
    profile, weakness = await SessionReportAnalysisService().generate_session_report(
        session_id="session-1",
        resume="resume",
        job_description="jd",
        company_info="company",
        qa_history=[{"question": "Q", "answer": "A"}],
        api_config={"smart": {"model": "demo"}},
    )

    assert set(reviewer_started) == {
        "technical_depth",
        "communication",
        "job_fit",
        "factual_risk",
    }
    assert channels["technical_depth"] == ("smart", 0.2)
    assert channels["communication"] == ("fast", 0.3)
    assert channels["job_fit"] == ("match_analyst", 0.2)
    assert channels["factual_risk"] == ("reflector", 0.0)
    assert reducer_calls == 1
    assert profile.skill_tags == ["FastAPI"]
    assert profile.total_questions_analyzed == 1
    assert weakness["consensus_method"] == "parallel_map_reduce"
    assert len(weakness["reviewer_assessments"]) == 4


@pytest.mark.asyncio
async def test_session_analysis_builds_evidence_bounded_report_when_all_reviewers_fail(monkeypatch):
    """All-reviewer failure must complete with real Q&A evidence and no invented scores."""

    async def fail_invoke(*_args, **_kwargs):
        raise RuntimeError("model failed")

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", fail_invoke)
    profile, weakness = await SessionReportAnalysisService().generate_session_report(
        session_id="session-1",
        resume="resume",
        job_description="jd",
        company_info="company",
        qa_history=[{"question": "请介绍 Agent 项目", "answer": "我实现了 RAG 和审批恢复。"}],
    )

    assert profile.generation_mode == "degraded_evidence_only"
    assert profile.recommendation is None
    assert profile.confidence is None
    assert profile.skill_tags == []
    assert set(profile.missing_dimensions) == {
        "professional_competence",
        "execution_results",
        "logic_problem_solving",
        "communication",
        "growth_potential",
        "collaboration",
    }
    for dimension in profile.missing_dimensions:
        assert getattr(profile, dimension).score is None
    assert weakness["generation_mode"] == "degraded_evidence_only"
    assert weakness["degradation_reason"] == "all_reviewers_failed"
    assert weakness["consensus_method"] == "deterministic_evidence_fallback"
    assert weakness["question_evidence"][0]["question_summary"] == "请介绍 Agent 项目"
    assert weakness["question_evidence"][0]["candidate_claims"] == ["我实现了 RAG 和审批恢复。"]
    assert len(weakness["reviewer_assessments"]) == 4
    assert all(item["status"] == "error" for item in weakness["reviewer_assessments"])


def test_weakness_output_accepts_missing_optional_model_fields():
    """Production payload validation remains tolerant of omitted explanatory fields."""
    report = WeaknessReportOutput.model_validate({
        "weakness_categories": [
            {"category": "行为面试", "severity": "medium"},
            {"category": "沟通表达", "severity": "low"},
        ],
        "question_failures": [{"question": "请介绍一次冲突处理经历"}],
    })

    assert report.weakness_categories[0].description == "行为面试表现仍有提升空间"
    assert report.question_failures[0].issue
    assert report.question_failures[0].better_example


@pytest.mark.asyncio
async def test_ability_profile_uses_same_parallel_reviewer_consensus(monkeypatch):
    """Cross-session ability narrative uses four perspective scores while local dimensions stay deterministic."""
    from ai.workflows.analysis.ability_service import AbilityAnalysisService
    from ai.workflows.analysis.reviewers.multi_reviewer import AbilityConsensusOutput, ReviewerAssessment

    reviewer_calls: list[str] = []

    async def invoke(*, output_model, call_metadata, **_kwargs):
        if output_model is ReviewerAssessment:
            perspective = call_metadata["review_perspective"]
            reviewer_calls.append(perspective)
            return ReviewerAssessment(
                perspective=perspective,
                score=7,
                dimension_scores={"professional_competence": 7},
                evidence_refs=["历史1"],
                confidence=0.7,
            )
        return AbilityConsensusOutput(
            overall_assessment="多视角共识：能力稳定。",
            key_strengths=["专业能力"],
            key_weaknesses=["沟通表达"],
            recommendation="hire",
            confidence=0.75,
        )

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", invoke)
    dimension = {"score": 8, "evidence": "历史证据"}
    profile = await AbilityAnalysisService()._aggregate_profiles_with_weights([{
        "professional_competence": dimension,
        "execution_results": dimension,
        "logic_problem_solving": dimension,
        "communication": dimension,
        "growth_potential": dimension,
        "collaboration": dimension,
        "skill_tags": ["FastAPI"],
        "total_questions_analyzed": 3,
    }])

    assert set(reviewer_calls) == {"technical_depth", "communication"}
    assert profile.professional_competence.score == 8
    assert profile.overall_assessment == "多视角共识：能力稳定。"
    assert profile.confidence == 0.75
