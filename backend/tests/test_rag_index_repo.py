"""RAG ORM 字段映射回归测试。"""

import pytest

from app.db.repositories.interview import rag_index_repo


class _FakeResult:
    def all(self):
        return []

    def scalars(self):
        return self


class _FakeDb:
    async def execute(self, _statement):
        return _FakeResult()


class _FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False


@pytest.mark.asyncio
async def test_rag_searches_use_chunk_metadata_mapping(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(rag_index_repo, "async_session", lambda: _FakeSession(db))
    repo = rag_index_repo.RagIndexRepo()

    assert await repo.search_by_text(
        user_id="user-1",
        namespace="user_private",
        query="FastAPI",
    ) == []
    assert await repo.search_by_vector(
        user_id="user-1",
        namespace="user_private",
        query_embedding=[0.0] * 1536,
    ) == []
    assert await repo.search_structured(
        user_id="user-1",
        namespace="user_private",
        tags=["backend"],
        target_skill="FastAPI",
        is_verified=True,
    ) == []
