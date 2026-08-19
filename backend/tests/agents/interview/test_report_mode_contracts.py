"""报告模式、兼容默认值与 owner 隔离契约测试。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.domain.interview_report_modes import (
    InterviewReportMode,
    build_authoritative_report_source_version,
    build_report_idempotency_key,
    normalize_report_mode,
)
from app.schemas.interview.schemas import InterviewReportRunRequest, InterviewStartRequest
from app.schemas.interview.session import SessionMarkdownReportResponse


def test_report_mode_is_explicit_and_legacy_default_is_deep():
    assert normalize_report_mode(None) is InterviewReportMode.DEEP
    assert normalize_report_mode("standard") is InterviewReportMode.STANDARD
    assert build_report_idempotency_key("session-1", "standard", "source-a") != build_report_idempotency_key(
        "session-1", "deep", "source-a"
    )

    report_request = InterviewReportRunRequest(session_id="session-1")
    start_request = InterviewStartRequest(thread_id="thread-1", mode="mock")
    assert report_request.report_mode is InterviewReportMode.DEEP
    assert start_request.report_mode is InterviewReportMode.DEEP

    with pytest.raises(ValidationError):
        InterviewReportRunRequest(session_id="session-1", report_mode="unsupported")


def test_standard_report_response_is_pdf_only_and_not_ready_without_artifact():
    response = SessionMarkdownReportResponse(
        success=False,
        session_id="session-1",
        report_mode=InterviewReportMode.STANDARD,
        status="not_ready",
        message="报告尚未生成",
    )

    assert response.report_mode is InterviewReportMode.STANDARD
    assert response.status == "not_ready"
    assert response.markdown == ""
    assert response.profile is None
    assert response.weakness_report is None
    assert response.pdf_artifact is None


def test_report_mode_reads_legacy_metadata_as_deep():
    metadata = SimpleNamespace()
    assert normalize_report_mode(getattr(metadata, "report_mode", None)) is InterviewReportMode.DEEP


def test_report_source_version_is_deterministic_but_never_contains_source_text():
    session = SimpleNamespace(
        session_id="session-1",
        metadata=SimpleNamespace(
            resume_content="private resume",
            job_description="private jd",
            company_info="private company",
            interview_plan=[{"question": "private question"}],
            round_type="tech_initial",
            max_questions=5,
        ),
        messages=[SimpleNamespace(role="user", content="private answer", question_index=0, timestamp="2026-08-17")],
    )
    version = build_authoritative_report_source_version(session)

    assert version == build_authoritative_report_source_version(session)
    assert version.startswith("rsv1-")
    assert "private" not in version


def test_report_persistence_models_keep_mode_and_source_identity_fields():
    from app.db.models.artifact import ArtifactModel
    from app.db.models.session import SessionModel

    session_columns = SessionModel.__table__.c
    artifact_columns = ArtifactModel.__table__.c
    for name in (
        "report_mode",
        "report_source_version",
        "stable_context_version",
        "stable_context_fingerprint",
        "round_strategy_version",
        "turn_state_version",
        "turn_state",
        "turn_checkpoint_refs",
    ):
        assert name in session_columns
    assert "artifact_mode" in artifact_columns
    assert "report_source_version" in artifact_columns


def test_report_mode_migration_backfills_legacy_artifacts_and_has_safe_downgrade():
    migration = Path(__file__).resolve().parents[3] / "alembic/versions/20260817_17_interview_report_modes.py"
    source = migration.read_text(encoding="utf-8")
    assert "UPDATE sessions SET report_mode = 'deep'" in source
    assert "WHEN source_type = 'interview_report' THEN 'deep'" in source
    assert "coexisting modes or source versions" in source


@pytest.mark.asyncio
async def test_standard_report_read_returns_only_owner_scoped_pdf_metadata(monkeypatch):
    from ai.workflows.interview.reports import use_cases as reports

    class FakeSessionRepo:
        async def get_session(self, session_id, user_id=None):
            if user_id != "owner-1":
                return None
            return SimpleNamespace(
                title="面试",
                metadata=SimpleNamespace(
                    mode="mock",
                    round_index=1,
                    max_questions=5,
                    company_profile=None,
                    report_source_version="source-v1",
                    turn_checkpoint_refs=[{
                        "kind": "standard_report_evaluation",
                        "report_source_version": "source-v1",
                        "generation_mode": "degraded_evidence_only",
                        "degradation_reason": "model_timeout",
                    }],
                ),
            )

    class FakeArtifactService:
        async def get_report_pdf(self, **kwargs):
            assert kwargs == {
                "session_id": "session-1",
                "user_id": "owner-1",
                "report_mode": InterviewReportMode.STANDARD,
                "report_source_version": "source-v1",
            }
            return SimpleNamespace(
                id=42,
                title="标准面试报告",
                format="pdf",
                mime_type="application/pdf",
                size_bytes=512,
                created_at="2026-08-17T00:00:00+00:00",
                artifact_mode="standard",
                report_source_version="source-v1",
            )

    use_cases = reports.InterviewReportUseCases()
    use_cases._session_repo = FakeSessionRepo()
    use_cases._artifact_service = FakeArtifactService()
    monkeypatch.setattr(reports, "get_weakness_report_repo", lambda: None)

    result = await use_cases.get_session_report(
        session_id="session-1",
        user_id="owner-1",
        report_mode=InterviewReportMode.STANDARD,
    )

    assert result.success is True
    assert result.status == "ready"
    assert result.report_mode is InterviewReportMode.STANDARD
    assert result.report_quality == "degraded_evidence_only"
    assert result.degradation_reason == "model_timeout"
    assert result.pdf_artifact.id == 42
    assert result.markdown == ""
    assert result.profile is None
    assert result.weakness_report is None
