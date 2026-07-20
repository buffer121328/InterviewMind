"""简历结果仓库事务边界测试。"""

import pytest

from app.infrastructure.db.repositories.resume.resume_repo import ResumeRepo


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
        self.added[-1].id = 123

    async def commit(self):
        self.calls.append("commit")

    async def refresh(self, _obj):
        self.calls.append("refresh")

    async def rollback(self):
        self.calls.append("rollback")


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_save_result_uses_external_session_without_commit():
    repo = ResumeRepo()
    session = _FakeSession()

    result_id = await repo.save_result(
        user_id="user-1",
        result_type="optimize",
        resume_content="resume",
        result_data={"ok": True},
        session=session,
    )

    assert result_id == 123
    assert session.calls == ["add", "flush"]


@pytest.mark.asyncio
async def test_save_result_owns_session_commits_and_refreshes(monkeypatch):
    from app.infrastructure.db.repositories.resume import resume_repo

    repo = ResumeRepo()
    session = _FakeSession()
    monkeypatch.setattr(resume_repo, "async_session", lambda: _FakeSessionContext(session))

    result_id = await repo.save_result(
        user_id="user-1",
        result_type="optimize",
        resume_content="resume",
        result_data={"ok": True},
    )

    assert result_id == 123
    assert session.calls == ["add", "flush", "commit", "refresh"]
