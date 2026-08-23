"""Phase 3 report chunking, evidence recovery, and voice-budget acceptance tests."""

from __future__ import annotations

import base64
import re
from types import SimpleNamespace

import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from ai.agents.interview.voice.context import build_voice_history_context
from ai.prompts.voice import build_interview_voice_system_prompt
from ai.workflows.analysis.analysis_service import SessionReportAnalysisService
from app.schemas.interview.voice import VoiceChatRequest
from app.schemas.llm_outputs import EvidenceChunkOutput, SessionInterviewReportOutput


def _report_output() -> SessionInterviewReportOutput:
    """Build a valid report fixture whose conclusions reference question evidence."""
    dimension = {
        "score": 8,
        "evidence": "能够说明关键取舍 [Q1]",
        "reason": "回答包含行动和结果 [Q1]",
        "better_answer_example": "补充更多量化指标",
        "improvement_tip": "使用 STAR 结构",
    }
    return SessionInterviewReportOutput.model_validate({
        "question_evidence": [],
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
                {
                    "category": "项目表达",
                    "description": "结果证据不足 [Q1]",
                    "severity": "medium",
                }
            ],
            "question_failures": [],
            "improvement_actions": [],
            "recommended_questions": [],
            "priority_order": ["项目表达"],
        },
    })


def _qa_history(count: int, *, answer_chars: int = 80) -> list[dict[str, str]]:
    """Build deterministic QA pairs for budget and checkpoint tests."""
    return [
        {
            "question": f"请说明第 {index + 1} 个项目决策",
            "answer": f"候选人回答 {index + 1}：" + "证据" * answer_chars,
        }
        for index in range(count)
    ]


def test_report_context_keeps_twenty_thousand_qa_chars_and_answer_points() -> None:
    """Second-round direct reports retain bounded scoring context without summarization."""
    service = SessionReportAnalysisService()
    qa_text = "开头证据" + ("中" * 20_100) + "结尾证据\n内部评分参考（不得在公开汇总中原样输出）: 指标量化"

    context = service._assemble_report_context(
        resume="候选人简历",
        job_description="岗位 JD",
        company_info="公司信息",
        qa_text=qa_text,
        include_qa=True,
    )

    qa_audit = next(item for item in context.source_audit if item["name"] == "qa_history")
    assert qa_audit["included_chars"] == 20_000
    assert qa_audit["truncated"] is True
    assert "开头证据" in context.model_context
    assert "指标量化" in context.model_context
    assert "…[truncated]…" in context.model_context


@pytest.mark.asyncio
async def test_long_report_checkpoints_each_evidence_chunk_and_reuses_it_on_retry(monkeypatch):
    """Final-summary retry skips completed evidence chunks and keeps one evidence item per question."""
    settings = SimpleNamespace(
        interview_report_qa_char_budget=100,
        interview_report_chunk_size=5,
        interview_report_task_timeout_seconds=180,
        interview_deep_report_max_output_tokens=4000,
    )
    monkeypatch.setattr("ai.workflows.analysis.analysis_service.get_settings", lambda: settings)
    calls: list[type] = []

    async def fake_invoke_structured(*, output_model, prompt, call_metadata=None, **_kwargs):
        from ai.workflows.analysis.reviewers.multi_reviewer import ReviewerAssessment

        calls.append(output_model)
        if output_model is ReviewerAssessment:
            perspective = call_metadata["review_perspective"]
            return ReviewerAssessment(
                perspective=perspective,
                score=8,
                evidence_refs=["Q1"],
                confidence=0.8,
            )
        if output_model is EvidenceChunkOutput:
            ids = list(dict.fromkeys(re.findall(r"Q\d+", prompt)))
            return EvidenceChunkOutput.model_validate({
                "items": [
                    {
                        "question_id": question_id,
                        "question_summary": f"{question_id} 摘要",
                        "candidate_claims": [f"{question_id} 主张"],
                    }
                    for question_id in ids
                ]
            })
        return _report_output()

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", fake_invoke_structured)
    checkpoints: list[dict] = []

    async def save_checkpoint(checkpoint: dict) -> None:
        checkpoints.append(checkpoint)

    service = SessionReportAnalysisService()
    profile, weakness = await service.generate_session_report(
        session_id="session-1",
        resume="resume",
        job_description="jd",
        company_info="company",
        qa_history=_qa_history(12),
        checkpoint_callback=save_checkpoint,
    )

    assert calls.count(EvidenceChunkOutput) == 3
    from ai.workflows.analysis.reviewers.multi_reviewer import ReviewerAssessment

    assert calls.count(ReviewerAssessment) == 4
    assert calls.count(SessionInterviewReportOutput) == 1
    assert len(checkpoints) == 3
    assert len(checkpoints[-1]["items"]) == 3
    assert checkpoints[-1]["items"][0]["idempotency_key"].startswith("session-1:")
    assert len(weakness["question_evidence"]) == 12
    assert profile.total_questions_analyzed == 12

    calls.clear()
    _profile, retried_weakness = await service.generate_session_report(
        session_id="session-1",
        resume="resume",
        job_description="jd",
        company_info="company",
        qa_history=_qa_history(12),
        report_checkpoint=checkpoints[-1],
        checkpoint_callback=save_checkpoint,
    )

    assert EvidenceChunkOutput not in calls
    assert calls.count(ReviewerAssessment) == 4
    assert calls.count(SessionInterviewReportOutput) == 1
    assert len(retried_weakness["question_evidence"]) == 12


@pytest.mark.asyncio
async def test_short_report_uses_parallel_reviewers_and_adds_local_trace(monkeypatch):
    """Short QA uses four reviewers plus one reducer and keeps per-question trace."""
    from ai.workflows.analysis.reviewers.multi_reviewer import ReviewerAssessment

    calls: list[type] = []

    async def invoke(*, output_model, call_metadata=None, **_kwargs):
        calls.append(output_model)
        if output_model is ReviewerAssessment:
            return ReviewerAssessment(
                perspective=call_metadata["review_perspective"],
                score=8,
                evidence_refs=["Q1"],
                confidence=0.8,
            )
        return _report_output()

    monkeypatch.setattr("ai.llm.llm_utils.invoke_structured", invoke)

    _profile, weakness = await SessionReportAnalysisService().generate_session_report(
        session_id="session-1",
        resume="resume",
        job_description="jd",
        company_info="company",
        qa_history=_qa_history(2, answer_chars=2),
    )

    assert calls.count(ReviewerAssessment) == 4
    assert calls.count(SessionInterviewReportOutput) == 1
    assert len(weakness["question_evidence"]) == 2
    assert weakness["question_evidence"][0]["question_id"] == "Q1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        (TimeoutError(), "model_timeout"),
        (OutputParserException("invalid structured report"), "output_contract_failure"),
    ],
)
async def test_short_report_degrades_when_narrative_cannot_complete_within_deadline(
    monkeypatch, failure, expected_reason,
):
    """Known report-composition failures preserve deterministic Q&A evidence instead of a blank task failure."""
    settings = SimpleNamespace(
        interview_report_qa_char_budget=12_000,
        interview_report_chunk_size=5,
        interview_report_task_timeout_seconds=120,
    )
    observed_deadlines = []

    async def fail_single_call(_self, *, deadline, **_kwargs):
        observed_deadlines.append(deadline.deadline_ms)
        raise failure

    monkeypatch.setattr("ai.workflows.analysis.analysis_service.get_settings", lambda: settings)
    monkeypatch.setattr(SessionReportAnalysisService, "_generate_single_call", fail_single_call)

    profile, weakness = await SessionReportAnalysisService().generate_session_report(
        session_id="session-1",
        resume="resume",
        job_description="jd",
        company_info="company",
        qa_history=_qa_history(2, answer_chars=2),
    )

    assert observed_deadlines == [120_000]
    assert profile.generation_mode == "degraded_evidence_only"
    assert weakness["generation_mode"] == "degraded_evidence_only"
    assert weakness["degradation_reason"] == expected_reason
    assert len(weakness["question_evidence"]) == 2


@pytest.mark.asyncio
async def test_checkpoint_write_is_owner_scoped_encrypted_and_event_safe(monkeypatch):
    """Checkpoint writes filter by owner, persist ciphertext, and emit no evidence body."""
    from ai.runtime.agent_runs import service as service_module

    run = SimpleNamespace(
        status="running",
        task_type="interview_report",
        step_results={},
        updated_at=None,
    )
    observed: dict[str, object] = {}

    class FakeSession:
        """Capture the owner-scoped statement and in-memory persistence side effects."""

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def scalar(self, statement):
            observed["query_values"] = set(statement.compile().params.values())
            observed["locked"] = statement._for_update_arg is not None
            return run

        async def commit(self):
            observed["committed"] = True

    def encrypt(checkpoint):
        observed["encrypted_input"] = checkpoint
        return "ciphertext-only"

    async def append_event(_self, _session, _run, event_type, payload=None):
        observed["event"] = (event_type, payload)

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module, "encrypt_payload", encrypt)
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    checkpoint = {"items": [{"evidence": "private candidate answer"}]}
    await service_module.AgentRunService().save_checkpoint(
        "run-1",
        "generating_reports",
        checkpoint,
        user_id="owner-1",
    )

    assert observed["query_values"] == {"run-1", "owner-1"}
    assert observed["locked"] is True
    assert observed["encrypted_input"] == checkpoint
    assert run.step_results["generating_reports"]["checkpoint_encrypted"] == "ciphertext-only"
    assert "private candidate answer" not in repr(run.step_results)
    assert observed["event"] == ("run.checkpoint.saved", {"item_count": 1})
    assert observed["committed"] is True


def test_voice_prompt_contains_only_current_next_and_progress_summary():
    """A voice turn does not resend the complete 20-question plan."""
    plan = [
        {"topic": f"主题{index + 1}", "content": f"完整题目 {index + 1}"}
        for index in range(20)
    ]
    prompt = build_interview_voice_system_prompt(plan, current_q_idx=5, follow_up_count=0)

    assert "完整题目 6" in prompt
    assert "完整题目 7" in prompt
    assert "完整题目 1" not in prompt
    assert "完整题目 20" not in prompt
    assert "剩余主问题数：14" in prompt
    assert "主题1" in prompt


def test_voice_history_uses_recent_text_and_older_summary_without_metadata(monkeypatch):
    """Audio URLs and internal IDs never enter the bounded rolling-history context."""
    monkeypatch.setattr(
        "ai.agents.interview.voice.context.get_settings",
        lambda: SimpleNamespace(voice_recent_message_count=4, voice_history_max_chars=1200),
    )
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"第 {index} 条文本 " + "内容" * 120,
            "audio_url": f"private-audio-{index}",
            "internal_id": f"internal-{index}",
        }
        for index in range(12)
    ]
    context = build_voice_history_context(history)

    assert context.input_chars <= 1200
    assert "private-audio" not in context.model_context
    assert "internal-" not in context.model_context
    assert "第 11 条文本" in context.model_context
    assert {"recent_history", "history_summary"}.issubset(
        {item["name"] for item in context.source_audit if item["included_chars"]}
    )


def _wav_header(*, duration_seconds: int, sample_rate: int = 8000) -> bytes:
    """Build a minimal PCM/WAV header whose data-size field represents the requested duration."""
    byte_rate = sample_rate * 2
    data_size = duration_seconds * byte_rate
    return (
        b"RIFF"
        + (36 + data_size).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + sample_rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + data_size.to_bytes(4, "little")
    )


def test_voice_request_rejects_malformed_and_over_duration_audio(monkeypatch):
    """Audio is rejected before AgentRun creation when base64 is invalid or WAV duration is excessive."""
    monkeypatch.setattr(
        "app.schemas.interview.voice.get_settings",
        lambda: SimpleNamespace(voice_audio_max_bytes=8_000_000, voice_audio_max_duration_seconds=120),
    )
    base = {
        "system_prompt": "prompt",
        "session_id": "voice-1",
        "api_config": {},
    }
    with pytest.raises(ValidationError, match="音频格式无效"):
        VoiceChatRequest(audio="not-base64!!!", **base)

    encoded = base64.b64encode(_wav_header(duration_seconds=121)).decode()
    with pytest.raises(ValidationError, match="单次录音不能超过 120 秒"):
        VoiceChatRequest(audio=encoded, **base)


def test_report_context_includes_full_current_resume_within_configured_budget(monkeypatch) -> None:
    """Deep reports retain the complete current resume instead of clipping it at 4,000 chars."""
    settings = SimpleNamespace(
        interview_report_context_total_chars=40_000,
        interview_report_resume_char_budget=10_000,
    )
    monkeypatch.setattr("ai.workflows.analysis.analysis_service.get_settings", lambda: settings)
    resume = "简历经历" * 1_365  # 5,460 characters, matching the latest HR session source size.

    context = SessionReportAnalysisService._assemble_report_context(
        resume=resume,
        job_description="岗位 JD",
        company_info="公司信息",
        qa_text="Q1 候选人回答" * 100,
        include_qa=True,
    )

    resume_audit = next(item for item in context.source_audit if item["name"] == "resume")
    assert resume_audit["selected_chars"] == len(resume)
    assert resume_audit["included_chars"] == len(resume)
    assert resume_audit["truncated"] is False
    assert "resume" not in context.truncated_sources
    event_fields = context.model_event_fields()
    assert event_fields["source_breakdown"]["resume"] == len(resume)
    assert event_fields["source_raw_breakdown"]["resume"] == len(resume)
    assert event_fields["source_raw_token_breakdown"]["resume"] >= event_fields["source_token_breakdown"]["resume"]
    assert resume not in str(event_fields)
