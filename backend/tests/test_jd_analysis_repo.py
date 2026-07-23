"""JD 分析结果仓库事务边界测试。"""

import pytest

from app.db.repositories.resume.jd_analysis_repo import JDAnalysisRepo


class _FakeSession:
    def __init__(self):
        self.calls = []
        self.added = []

    async def scalar(self, _stmt):
        self.calls.append("scalar")
        return None

    def add(self, obj):
        self.calls.append("add")
        self.added.append(obj)

    async def flush(self):
        self.calls.append("flush")
        self.added[-1].id = 321

    async def commit(self):
        self.calls.append("commit")

    async def refresh(self, _obj):
        self.calls.append("refresh")


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_jd_save_result_uses_external_session_without_commit():
    repo = JDAnalysisRepo()
    session = _FakeSession()

    result_id = await repo.save_result(
        user_id="user-1",
        resume_source_type="resume",
        resume_content_snapshot="resume",
        job_description="jd",
        analysis_result={"ok": True},
        session=session,
    )

    assert result_id == 321
    assert session.calls == ["add", "flush"]


@pytest.mark.asyncio
async def test_jd_save_result_owns_session_commits_and_refreshes(monkeypatch):
    from app.db.repositories.resume import jd_analysis_repo

    repo = JDAnalysisRepo()
    session = _FakeSession()
    monkeypatch.setattr(jd_analysis_repo, "async_session", lambda: _FakeSessionContext(session))

    result_id = await repo.save_result(
        user_id="user-1",
        resume_source_type="resume",
        resume_content_snapshot="resume",
        job_description="jd",
        analysis_result={"ok": True},
    )

    assert result_id == 321
    assert session.calls == ["add", "flush", "commit", "refresh"]
