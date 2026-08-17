"""RAG ORM 字段映射回归测试。"""

import pytest
from sqlalchemy.dialects import postgresql

from app.db.repositories.interview import rag_index_repo


class _FakeResult:
    rowcount = 2

    def all(self):
        return []

    def scalars(self):
        return self

    def scalar_one(self):
        return 17


class _FakeDb:
    def __init__(self):
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult()

    async def commit(self):
        self.commits += 1


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


@pytest.mark.asyncio
async def test_pending_upsert_is_idempotent_and_preserves_unchanged_embedding(monkeypatch):
    """相同内容重复 upsert 仍返回行，并且不会把已完成 embedding 重置为 pending。"""
    db = _FakeDb()
    monkeypatch.setattr(rag_index_repo, "async_session", lambda: _FakeSession(db))

    chunk_id = await rag_index_repo.RagIndexRepo().upsert_chunk(
        user_id="user-1",
        namespace="user_private",
        source_type="question_bank",
        source_id="42",
        chunk_key="question_bank:42:main",
        content="FastAPI dependency injection",
        content_hash="hash-1",
        metadata={"target_skill": "FastAPI"},
    )

    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    update_clause = sql.split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
    assert chunk_id == 17
    assert "embedding_status = CASE WHEN" in update_clause
    assert "embedding = CASE WHEN" in update_clause
    assert "embedding_dimension = CASE WHEN" in update_clause
    assert " WHERE " not in update_clause
    assert db.commits == 1


@pytest.mark.asyncio
async def test_embedding_upsert_persists_declared_dimension(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(rag_index_repo, "async_session", lambda: _FakeSession(db))

    await rag_index_repo.RagIndexRepo().upsert_chunk_with_embedding(
        user_id="user-1",
        namespace="user_private",
        source_type="question_bank",
        source_id="42",
        chunk_key="question_bank:42:main",
        content="FastAPI dependency injection",
        content_hash="hash-1",
        embedding=[0.1, 0.2],
        embedding_model="embed-model",
        dimensions=2,
    )

    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "embedding_dimension" in sql
    assert db.commits == 1


@pytest.mark.asyncio
async def test_reuse_and_vector_search_filter_model_and_dimension(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(rag_index_repo, "async_session", lambda: _FakeSession(db))
    repo = rag_index_repo.RagIndexRepo()

    assert await repo.get_reusable_embeddings(
        user_id="user-1",
        content_hashes={"hash-1"},
        embedding_model="embed-model",
        dimensions=1024,
    ) == {}
    assert await repo.search_by_vector(
        user_id="user-1",
        namespace="user_private",
        query_embedding=[0.0] * 1024,
        embedding_model="embed-model",
    ) == []

    reuse_sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    search_sql = str(db.statements[1].compile(dialect=postgresql.dialect()))
    assert "rag_chunks.embedding_dimension" in reuse_sql
    assert "rag_chunks.embedding_model" in reuse_sql
    assert "rag_chunks.embedding_dimension" in search_sql
    assert "rag_chunks.embedding_model" in search_sql


@pytest.mark.asyncio
async def test_deactivate_stale_chunks_keeps_current_snapshot_scoped(monkeypatch):
    """删除漂移只作用于同 owner、namespace、source_type 且不在当前快照中的 chunk。"""
    db = _FakeDb()
    monkeypatch.setattr(rag_index_repo, "async_session", lambda: _FakeSession(db))

    affected = await rag_index_repo.RagIndexRepo().deactivate_stale_chunks(
        user_id="user-1",
        namespace="user_private",
        source_type="question_bank",
        active_chunk_scopes={
            ("42", "question_bank:42:main"),
            ("43", "question_bank:43:main"),
        },
    )

    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert affected == 2
    assert "UPDATE rag_chunks SET is_active=" in sql
    assert "(rag_chunks.source_id, rag_chunks.chunk_key) NOT IN" in sql
    assert "rag_chunks.user_id =" in sql
    assert "rag_chunks.namespace =" in sql
    assert "rag_chunks.source_type =" in sql
