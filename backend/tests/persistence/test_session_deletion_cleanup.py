"""Regression coverage for explicit data cleanup during interview-session deletion."""

from types import SimpleNamespace

import pytest

from app.db.repositories.session.repo_impl import session_mgmt
from app.db.repositories.session.repo_impl.session_mgmt import SessionManagementService


class _DeleteDb:
    """Captures a delete transaction without opening a real database connection."""

    def __init__(self) -> None:
        self.executed = []
        self.driver_sql = []
        self.committed = False

    async def scalar(self, _statement):
        return SimpleNamespace(series_id="series-1")

    async def execute(self, statement):
        self.executed.append(statement)

    async def exec_driver_sql(self, statement, parameters):
        self.driver_sql.append((statement, parameters))

    async def commit(self):
        self.committed = True


class _AsyncSessionContext:
    def __init__(self, db: _DeleteDb) -> None:
        self._db = db

    async def __aenter__(self) -> _DeleteDb:
        return self._db

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.mark.asyncio
async def test_delete_session_explicitly_cleans_attempts_artifacts_and_invalidates_series(monkeypatch):
    """Rows without FK cascades are removed and an incomplete series loses its aggregate profile."""
    db = _DeleteDb()
    service = SessionManagementService()

    async def allowed(*_args, **_kwargs):
        return True

    monkeypatch.setattr(service, "_check_session_access", allowed)
    monkeypatch.setattr(session_mgmt, "async_session", lambda: _AsyncSessionContext(db))

    assert await service.delete_session("session-2", user_id="owner-1") is True

    rendered = "\n".join(str(statement) for statement in db.executed)
    assert "interview_question_attempts" in rendered
    assert "artifacts" in rendered
    assert "company_profile" in rendered
    assert "sessions" in rendered
    assert db.committed is True
    assert {statement for statement, _params in db.driver_sql} == {
        "DELETE FROM checkpoints WHERE thread_id = $1",
        "DELETE FROM writes WHERE thread_id = $1",
    }
