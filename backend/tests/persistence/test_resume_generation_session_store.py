"""Generation session continuation persistence contracts."""

from types import SimpleNamespace

import pytest
from app.clock import utc_now
from app.db.repositories.resume import resume_generation_repo as repo_module
from app.db.repositories.resume.resume_generation_repo import SessionStore


class _FakeSession:
    def __init__(self, row):
        self.row = row
        self.calls: list[str] = []

    async def scalar(self, _statement):
        self.calls.append("scalar")
        return self.row

    async def commit(self):
        self.calls.append("commit")

    async def refresh(self, _row):
        self.calls.append("refresh")

    async def delete(self, _row):
        self.calls.append("delete")


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _row(**overrides):
    values = {
        "id": "generation-1",
        "user_id": "owner-1",
        "resume_content": "# Resume",
        "job_description": "Backend engineer",
        "optimization_result": {},
        "template_style": "professional",
        "questions": ["What did you build?"],
        "user_answers": {},
        "review_result": {},
        "iteration_count": 0,
        "draft_content": "",
        "final_markdown": "",
        "generated_resume_id": None,
        "agent_run_id": None,
        "status": "awaiting_input",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _store(monkeypatch, row):
    session = _FakeSession(row)
    monkeypatch.setattr(repo_module, "async_session", lambda: _FakeSessionContext(session))
    return SessionStore(ttl_hours=24), session


@pytest.mark.asyncio
async def test_claim_continuation_accepts_complete_answers_once(monkeypatch):
    row = _row()
    store, db = _store(monkeypatch, row)

    session = await store.claim_continuation(
        "generation-1",
        user_id="owner-1",
        answers={"What did you build?": "A resumable workflow"},
        continuation_key="continuation-a",
    )

    assert session.status == "draft_generation"
    assert row.user_answers == {"What did you build?": "A resumable workflow"}
    assert row.review_result == {"_continuation_key": "continuation-a"}
    assert db.calls == ["scalar", "commit", "refresh"]


@pytest.mark.asyncio
async def test_claim_continuation_reuses_identical_digest_and_rejects_changed_answers(monkeypatch):
    row = _row(
        status="draft_generation",
        user_answers={"What did you build?": "A resumable workflow"},
        review_result={"_continuation_key": "continuation-a"},
    )
    store, db = _store(monkeypatch, row)

    duplicate = await store.claim_continuation(
        "generation-1",
        user_id="owner-1",
        answers={"What did you build?": "A resumable workflow"},
        continuation_key="continuation-a",
    )

    assert duplicate.status == "draft_generation"
    assert db.calls == ["scalar"]

    with pytest.raises(ValueError, match="当前不接受"):
        await store.claim_continuation(
            "generation-1",
            user_id="owner-1",
            answers={"What did you build?": "Changed answer"},
            continuation_key="continuation-b",
        )


@pytest.mark.asyncio
async def test_claim_continuation_requires_owner_and_rejects_changed_completed_input(monkeypatch):
    store, _db = _store(monkeypatch, None)

    with pytest.raises(ValueError, match="不存在"):
        await store.claim_continuation(
            "generation-1",
            user_id="other-owner",
            answers={"What did you build?": "Answer"},
            continuation_key="continuation-a",
        )

    completed_row = _row(
        status="completed",
        generated_resume_id=7,
        review_result={"_continuation_key": "continuation-a"},
    )
    store, _db = _store(monkeypatch, completed_row)
    completed = await store.claim_continuation(
        "generation-1",
        user_id="owner-1",
        answers={"What did you build?": "Answer"},
        continuation_key="continuation-a",
    )
    assert completed.generated_resume_id == 7

    with pytest.raises(ValueError, match="当前不接受"):
        await store.claim_continuation(
            "generation-1",
            user_id="owner-1",
            answers={"What did you build?": "Changed answer"},
            continuation_key="continuation-b",
        )


@pytest.mark.asyncio
async def test_bind_continuation_run_is_idempotent_and_rejects_drift(monkeypatch):
    row = _row(
        status="draft_generation",
        review_result={"_continuation_key": "continuation-a"},
    )
    store, db = _store(monkeypatch, row)

    bound = await store.bind_continuation_run(
        "generation-1",
        user_id="owner-1",
        continuation_key="continuation-a",
        agent_run_id="run-1",
    )
    assert bound.agent_run_id == "run-1"
    assert row.agent_run_id == "run-1"
    assert db.calls == ["scalar", "commit", "refresh"]

    duplicate = await store.bind_continuation_run(
        "generation-1",
        user_id="owner-1",
        continuation_key="continuation-a",
        agent_run_id="run-1",
    )
    assert duplicate.agent_run_id == "run-1"

    with pytest.raises(ValueError, match="另一生成任务"):
        await store.bind_continuation_run(
            "generation-1",
            user_id="owner-1",
            continuation_key="continuation-a",
            agent_run_id="run-2",
        )


@pytest.mark.asyncio
async def test_save_generated_resume_reuses_existing_agent_run_result(monkeypatch):
    """Recovery after result persistence returns the original resume instead of inserting again."""
    from app.db.repositories.resume.resume_generation_repo import ResumeGenerationRepo

    existing = SimpleNamespace(id=23)

    class ExistingResultSession(_FakeSession):
        def add(self, _row):
            raise AssertionError("existing generation result must not be inserted again")

    db = ExistingResultSession(existing)
    monkeypatch.setattr(repo_module, "async_session", lambda: _FakeSessionContext(db))

    resume_id = await ResumeGenerationRepo().save_generated_resume(
        user_id="owner-1",
        title="Resume",
        content="# Resume",
        generation_session_id="generation-1",
        agent_run_id="run-1",
    )

    assert resume_id == 23
    assert db.calls == ["scalar"]
