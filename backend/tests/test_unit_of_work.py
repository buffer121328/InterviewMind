"""UnitOfWork 的事务边界测试。"""

import pytest

from app.db.unit_of_work import UnitOfWork


class FakeSession:
    def __init__(self):
        self.calls = []

    async def commit(self):
        self.calls.append("commit")

    async def rollback(self):
        self.calls.append("rollback")

    async def close(self):
        self.calls.append("close")


@pytest.mark.asyncio
async def test_unit_of_work_commits_and_closes_on_success():
    session = FakeSession()

    async with UnitOfWork(lambda: session) as uow:
        assert uow.db is session

    assert session.calls == ["commit", "close"]


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_and_closes_on_error():
    session = FakeSession()

    with pytest.raises(RuntimeError):
        async with UnitOfWork(lambda: session):
            raise RuntimeError("boom")

    assert session.calls == ["rollback", "close"]


def test_unit_of_work_db_requires_context():
    uow = UnitOfWork(lambda: FakeSession())

    with pytest.raises(RuntimeError, match="尚未进入上下文"):
        _ = uow.db
