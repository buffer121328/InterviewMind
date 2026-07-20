import sys
import types

import pytest

from app.infrastructure.memory import memory


class _FakeSaver:
    def __init__(self):
        self.setup_called = False

    async def setup(self):
        self.setup_called = True


class _FakeContext:
    def __init__(self, saver):
        self.saver = saver
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self.saver

    async def __aexit__(self, *_args):
        self.exited = True


@pytest.mark.asyncio
async def test_postgres_checkpointer_uses_async_context(monkeypatch):
    await memory.close_checkpointer()
    saver = _FakeSaver()
    context = _FakeContext(saver)

    class _FakeAsyncPostgresSaver:
        @classmethod
        def from_conn_string(cls, dsn):
            assert dsn.startswith("postgresql://")
            return context

    module = types.ModuleType("langgraph.checkpoint.postgres.aio")
    module.AsyncPostgresSaver = _FakeAsyncPostgresSaver
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres.aio", module)
    monkeypatch.setattr("app.infrastructure.db.config.get_postgres_dsn", lambda: "postgresql://u:p@db/test")

    result = await memory.get_checkpointer()

    assert result is saver
    assert saver.setup_called is True
    assert context.entered is True
    assert memory.get_checkpointer_type() == "postgres"

    await memory.close_checkpointer()
    assert context.exited is True
    assert memory.get_checkpointer_type() is None
