"""结构化面试报告消费与训练交接验收测试。"""

from types import SimpleNamespace

import pytest


PROFILE = {
    "overall_assessment": "整体表现稳定",
    "recommendation": "重点练习系统设计",
    "professional_competence": {"score": 8, "evidence": "能够说明取舍 [Q1]"},
    "key_strengths": ["技术取舍清晰"],
    "key_weaknesses": ["容量估算不足"],
}
WEAKNESS = {
    "question_evidence": [{"question_id": "Q1", "question_summary": "缓存设计", "missing_evidence": ["容量数据"]}],
    "weakness_categories": [{"category": "系统设计", "description": "缺少容量估算", "severity": "high"}],
    "question_failures": [{"question": "如何设计缓存", "issue": "缺少量化", "better_example": "补充容量与命中率"}],
    "improvement_actions": [{"action": "练习容量估算", "priority": 1, "estimated_effort": "3天"}],
    "recommended_questions": ["如何估算缓存容量？", "如何设计缓存淘汰策略？"],
    "priority_order": ["系统设计", "项目表达"],
}


class FakeSessionRepo:
    async def get_session(self, session_id, user_id=None):
        if user_id != "owner-1":
            return None
        return SimpleNamespace(
            title="面试",
            metadata=SimpleNamespace(mode="mock", round_index=1, max_questions=5, company_profile=None),
        )

    async def get_profile(self, session_id, user_id=None):
        return {**PROFILE, "last_updated": "2026-08-04T10:00:00"}


class FakeWeaknessRepo:
    async def get_report_by_session(self, session_id, user_id=None):
        return {"report_data": WEAKNESS, "updated_at": "2026-08-04T10:01:00"}


@pytest.mark.asyncio
async def test_session_report_returns_structured_fields_and_markdown(monkeypatch):
    from ai.workflows.interview.reports import use_cases as reports

    use_cases = reports.InterviewReportUseCases()
    use_cases._session_repo = FakeSessionRepo()
    monkeypatch.setattr(reports, "get_weakness_report_repo", lambda: FakeWeaknessRepo())

    result = await use_cases.get_session_report(session_id="session-1", user_id="owner-1")

    assert result.success is True
    assert result.markdown.startswith("# 面试")
    assert result.profile.overall_assessment == "整体表现稳定"
    assert result.weakness_report.recommended_questions == ["如何估算缓存容量？", "如何设计缓存淘汰策略？"]
    assert result.weakness_report.question_evidence[0].question_id == "Q1"


@pytest.mark.asyncio
async def test_save_recommended_questions_uses_persisted_indices_and_is_idempotent(monkeypatch):
    from ai.workflows.interview.reports import use_cases as reports
    from app.schemas.interview.interview_report import SaveReportQuestionsRequest

    calls = []

    class FakeQuestionRepo:
        async def create_report_question_if_absent(self, **kwargs):
            calls.append(kwargs)
            return (10 + len(calls), len(calls) == 1)

    use_cases = reports.InterviewReportUseCases()
    use_cases._session_repo = FakeSessionRepo()
    use_cases._question_bank_repo = FakeQuestionRepo()
    monkeypatch.setattr(reports, "get_weakness_report_repo", lambda: FakeWeaknessRepo())

    result = await use_cases.save_recommended_questions(
        session_id="session-1",
        request=SaveReportQuestionsRequest(question_indices=[0, 1]),
        user_id="owner-1",
    )

    assert result.saved_count == 1
    assert result.skipped_count == 1
    assert calls[0]["question_text"] == "如何估算缓存容量？"
    assert calls[0]["origin_session_id"] == "session-1"


@pytest.mark.asyncio
async def test_save_recommended_questions_rejects_forged_index(monkeypatch):
    from ai.workflows.interview.reports import use_cases as reports
    from app.schemas.interview.interview_report import SaveReportQuestionsRequest

    use_cases = reports.InterviewReportUseCases()
    use_cases._session_repo = FakeSessionRepo()
    monkeypatch.setattr(reports, "get_weakness_report_repo", lambda: FakeWeaknessRepo())

    with pytest.raises(reports.InterviewReportBadRequest):
        await use_cases.save_recommended_questions(
            session_id="session-1",
            request=SaveReportQuestionsRequest(question_indices=[9]),
            user_id="owner-1",
        )
