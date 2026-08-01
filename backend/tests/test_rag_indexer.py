"""RAG 索引快照一致性与 pending 失败语义回归测试。"""

from types import SimpleNamespace

import pytest

from ai.rag import rag_indexer


class _FakeRepo:
    """记录索引器写入和失效调用，不访问真实 pgvector。"""

    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.deactivations: list[dict] = []
        self.pending: list[SimpleNamespace] = []

    async def upsert_chunk(self, **kwargs):
        """记录 pending upsert。"""
        self.upserts.append(kwargs)
        return len(self.upserts)

    async def deactivate_stale_chunks(self, **kwargs):
        """记录快照失效边界。"""
        self.deactivations.append(kwargs)
        return 1

    async def get_pending_chunks(self, **_kwargs):
        """返回预置 pending rows。"""
        return self.pending


@pytest.mark.asyncio
async def test_index_user_data_deactivates_chunks_missing_from_successful_snapshot(monkeypatch):
    """完整来源重建成功后，应失效已删除记录对应的旧 chunk。"""
    chunks = [
        {
            "source_type": "question_bank",
            "source_id": "42",
            "chunk_key": "question_bank:42:main",
            "content": "FastAPI dependency injection",
        },
        {
            "source_type": "question_bank",
            "source_id": "43",
            "chunk_key": "question_bank:43:main",
            "content": "SQLAlchemy transaction",
        },
    ]

    async def fake_extract(_user_id):
        """返回一次完整题库快照。"""
        return chunks

    repo = _FakeRepo()
    indexer = rag_indexer.RagIndexer()
    indexer._repo = repo
    monkeypatch.setattr(rag_indexer, "extract_question_bank_chunks", fake_extract)

    stats = await indexer.index_user_data(
        "user-1",
        with_embedding=False,
        source_types=["question_bank"],
    )

    assert stats == {"question_bank": 2}
    assert len(repo.upserts) == 2
    assert repo.deactivations == [
        {
            "user_id": "user-1",
            "namespace": "user_private",
            "source_type": "question_bank",
            "active_chunk_scopes": {
                ("42", "question_bank:42:main"),
                ("43", "question_bank:43:main"),
            },
        }
    ]


@pytest.mark.asyncio
async def test_empty_successful_snapshot_deactivates_all_previous_source_chunks(monkeypatch):
    """来源表已清空时，成功提取出的空快照必须让旧索引全部失效。"""

    async def fake_extract(_user_id):
        """模拟用户已删除全部题库数据。"""
        return []

    repo = _FakeRepo()
    indexer = rag_indexer.RagIndexer()
    indexer._repo = repo
    monkeypatch.setattr(rag_indexer, "extract_question_bank_chunks", fake_extract)

    stats = await indexer.index_user_data(
        "user-1",
        with_embedding=False,
        source_types=["question_bank"],
    )

    assert stats == {"question_bank": 0}
    assert repo.deactivations[0]["active_chunk_scopes"] == set()


@pytest.mark.asyncio
async def test_pending_embedding_batch_failure_is_not_reported_as_no_work(monkeypatch):
    """外部批量 embedding 失败必须抛错，不能与“没有 pending 数据”的 0 混淆。"""

    async def fail_batch(*_args, **_kwargs):
        """模拟 embedding 依赖失败。"""
        raise TimeoutError("provider timeout")

    repo = _FakeRepo()
    repo.pending = [SimpleNamespace(id=1, content="private chunk")]
    indexer = rag_indexer.RagIndexer()
    indexer._repo = repo
    monkeypatch.setattr(rag_indexer, "generate_embeddings_batch", fail_batch)

    with pytest.raises(RuntimeError, match="待处理 embedding 批次生成失败"):
        await indexer.process_pending_embeddings(user_id="user-1")
