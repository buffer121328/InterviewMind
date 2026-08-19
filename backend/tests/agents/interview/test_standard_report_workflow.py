"""标准面试报告的单调用和完整来源准备契约。"""

from unittest.mock import AsyncMock

import pytest

from app.schemas.llm_outputs import SessionInterviewReportOutput


def _model_output() -> SessionInterviewReportOutput:
    dimension = {
        "score": 7.0,
        "evidence": "能够结合 [Q1] 说明实际做法",
        "reason": "证据充分",
        "improvement_tip": "补充量化结果",
        "better_answer_example": "说明背景、行动和结果",
    }
    return SessionInterviewReportOutput.model_validate(
        {
            "question_evidence": [
                {
                    "question_id": "Q1",
                    "topic": "系统设计",
                    "question_summary": "缓存设计",
                    "candidate_claims": ["说明了缓存策略"],
                    "demonstrated_skills": ["系统设计"],
                    "missing_evidence": ["容量估算"],
                    "communication_observations": ["表达清晰"],
                }
            ],
            "candidate_profile": {
                "professional_competence": dimension,
                "execution_results": dimension,
                "logic_problem_solving": dimension,
                "communication": dimension,
                "growth_potential": dimension,
                "collaboration": dimension,
                "skill_tags": ["Python"],
                "overall_assessment": "表现稳定",
                "key_strengths": ["思路清晰"],
                "key_weaknesses": ["量化不足"],
                "recommendation": "maybe",
                "confidence": 0.7,
            },
            "weakness_report": {
                "question_evidence": [],
                "weakness_categories": [{"category": "系统设计", "description": "容量估算不足", "severity": "medium"}],
                "question_failures": [],
                "improvement_actions": [{"action": "练习容量估算", "priority": 1, "estimated_effort": "3天"}],
                "recommended_questions": ["如何估算缓存容量？"],
                "priority_order": ["系统设计"],
            },
        }
    )


def test_standard_source_preparation_is_deterministic_and_traceable_for_long_answers():
    from ai.workflows.interview.reports.standard import prepare_standard_report_source

    qa_history = [{"question": "请介绍缓存设计", "answer": "A" * 800, "answer_points": ["容量", "淘汰"]}]
    prepared = prepare_standard_report_source(
        resume="简历正文",
        job_description="JD 正文",
        company_info="公司信息",
        qa_history=qa_history,
        source_version="rsv1-source",
        raw_char_budget=120,
    )

    assert prepared.model_context == prepare_standard_report_source(
        resume="简历正文",
        job_description="JD 正文",
        company_info="公司信息",
        qa_history=qa_history,
        source_version="rsv1-source",
        raw_char_budget=120,
    ).model_context
    assert prepared.source_coverage["qa_count"] == 1
    assert "[Q1]" in prepared.model_context
    assert "answer_sha256" in prepared.model_context
    assert "omitted_char_count" in prepared.model_context
    assert "A" * 800 not in prepared.model_context


@pytest.mark.asyncio
async def test_standard_report_uses_exactly_one_general_structured_generation(monkeypatch):
    from ai.workflows.interview.reports import standard

    invoke = AsyncMock(return_value=_model_output())
    monkeypatch.setattr(standard.llm_utils, "invoke_structured", invoke)

    result = await standard.StandardInterviewReportService().generate(
        title="后端面试",
        mode="mock",
        round_index=1,
        max_questions=5,
        resume="简历正文",
        job_description="JD 正文",
        company_info="公司信息",
        qa_history=[{"question": "缓存如何设计？", "answer": "我会先定义容量和淘汰策略。"}],
        report_source_version="rsv1-source",
        api_config={"general": {"model": "demo"}},
    )

    assert invoke.await_count == 1
    assert invoke.await_args.kwargs["channel"] == "general"
    assert invoke.await_args.kwargs["output_model"] is SessionInterviewReportOutput
    assert invoke.await_args.kwargs["max_retries"] == 0
    assert invoke.await_args.kwargs["max_tokens"] == 3500
    assert result.evaluation_digest.startswith("sha256:")
    assert result.markdown.startswith("# 后端面试")
    assert result.profile["overall_assessment"] == "表现稳定"

@pytest.mark.asyncio
async def test_standard_trigger_persists_pdf_and_safe_evaluation_digest_without_deep_records(monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace

    from ai.agents.interview import interview_analysis
    from ai.workflows.interview.reports.standard import StandardReportGeneration

    saved_updates = []

    class FakeSessionRepo:
        async def get_session(self, *_args, **_kwargs):
            return SimpleNamespace(
                title="后端面试",
                metadata=SimpleNamespace(
                    resume_content="简历正文",
                    job_description="JD 正文",
                    company_info="公司信息",
                    interview_plan=[],
                    series_id=None,
                    mode="mock",
                    round_index=1,
                    max_questions=5,
                    report_source_version="rsv1-source",
                    turn_checkpoint_refs=[],
                ),
                messages=[
                    SimpleNamespace(role="assistant", content="缓存如何设计？", question_index=0),
                    SimpleNamespace(role="user", content="我会先定义容量和淘汰策略。", question_index=0),
                ],
            )

        async def save_interview_plan(self, *_args, **_kwargs):
            return True

        async def update_session(self, **kwargs):
            saved_updates.append(kwargs)
            return SimpleNamespace()

        async def save_profile(self, *_args, **_kwargs):
            raise AssertionError("标准报告不得写入深度画像")

    class FakeStandardService:
        async def generate(self, **kwargs):
            assert kwargs["report_source_version"] == "rsv1-source"
            assert kwargs["deadline"].total_timeout == 600
            return StandardReportGeneration(
                markdown="# 后端面试 · 面试报告",
                profile={},
                weakness_report={},
                evaluation_digest="sha256:digest",
                source_coverage={"qa_count": 1, "derived_ir_count": 0},
            )

    persisted = []

    class FakeArtifactService:
        async def persist_interview_report_pdf(self, **kwargs):
            persisted.append(kwargs)
            return SimpleNamespace(id=23)

    session_repo_module = import_module("app.db.repositories.session.session_repo")
    artifact_service_module = import_module("app.files.artifact_service")
    monkeypatch.setattr(session_repo_module, "SessionRepo", FakeSessionRepo)
    monkeypatch.setattr(
        "ai.workflows.interview.reports.standard.StandardInterviewReportService",
        FakeStandardService,
    )
    monkeypatch.setattr(artifact_service_module, "ArtifactService", FakeArtifactService)
    monkeypatch.setattr(
        "ai.workflows.analysis.analysis_service.get_session_report_analysis_service",
        lambda: (_ for _ in ()).throw(AssertionError("不得进入深度链路")),
    )

    await interview_analysis.trigger_session_report_analysis(
        "session-1",
        user_id="owner-1",
        report_mode="standard",
        report_source_version="rsv1-source",
        raise_on_error=True,
    )

    assert persisted == [
        {
            "user_id": "owner-1",
            "session_id": "session-1",
            "title": "后端面试-标准面试报告",
            "markdown": "# 后端面试 · 面试报告",
            "report_source_version": "rsv1-source",
        }
    ]
    digest_ref = saved_updates[-1]["metadata_updates"]["turn_checkpoint_refs"][-1]
    assert digest_ref == {
        "kind": "standard_report_evaluation",
        "report_mode": "standard",
        "report_source_version": "rsv1-source",
        "evaluation_digest": "sha256:digest",
        "qa_count": 1,
        "derived_ir_count": 0,
        "generation_mode": "model_reviewed",
        "degradation_reason": None,
        "artifact_id": 23,
    }

@pytest.mark.asyncio
async def test_standard_report_degrades_to_pdf_safe_evidence_when_structured_output_is_invalid(monkeypatch):
    from ai.workflows.interview.reports import standard

    invoke = AsyncMock(return_value={"invalid": True})
    monkeypatch.setattr(standard.llm_utils, "invoke_structured", invoke)

    result = await standard.StandardInterviewReportService().generate(
        title="后端面试",
        mode="mock",
        round_index=1,
        max_questions=5,
        resume="简历正文",
        job_description="JD 正文",
        company_info="公司信息",
        qa_history=[{"question": "缓存如何设计？", "answer": "我会先定义容量和淘汰策略。"}],
        report_source_version="rsv1-source",
        api_config=None,
    )

    assert invoke.await_count == 1
    assert result.profile["generation_mode"] == "degraded_evidence_only"
    assert result.generation_mode == "degraded_evidence_only"
    assert result.degradation_reason == "output_contract_failure"
    assert result.weakness_report["degradation_reason"] == "output_contract_failure"


@pytest.mark.asyncio
async def test_standard_report_records_source_estimates_only_for_context_assembly(monkeypatch):
    """标准报告把安全来源估算归因到组装阶段，而非模型传输输入桶。"""
    import observability

    from ai.workflows.interview.reports import standard

    invoke = AsyncMock(return_value=_model_output())
    monkeypatch.setattr(standard.llm_utils, "invoke_structured", invoke)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    observability._reset_langfuse_for_tests()
    try:
        async with observability.agent_observation(
            name="standard-report-context-test",
            agent_type="interview",
            user_id="owner-1",
            session_id="session-1",
            input_payload={"case": "context-attribution"},
        ) as observation:
            await standard.StandardInterviewReportService().generate(
                title="后端面试",
                mode="mock",
                round_index=1,
                max_questions=5,
                resume="PRIVATE_RESUME",
                job_description="PRIVATE_JD",
                company_info="PRIVATE_COMPANY",
                qa_history=[{"question": "PRIVATE_QUESTION", "answer": "PRIVATE_ANSWER"}],
                report_source_version="rsv1-source",
                api_config={"general": {"model": "demo"}},
            )

        context_event = next(
            event for event in observation.model_events
            if event["event_type"] == "context.assembled"
        )
        assert context_event["stage"] == "interview_report.context_assembly"
        assert context_event["source_breakdown"].keys() == {
            "resume", "job_description", "company_info", "qa_history",
        }
        assert context_event["source_token_breakdown"]["qa_history"] > 0
        serialized = str(observation.model_events)
        assert "PRIVATE_RESUME" not in serialized
        assert "PRIVATE_JD" not in serialized
        assert "PRIVATE_COMPANY" not in serialized
        assert "PRIVATE_QUESTION" not in serialized
        assert "PRIVATE_ANSWER" not in serialized
    finally:
        observability._reset_langfuse_for_tests()
