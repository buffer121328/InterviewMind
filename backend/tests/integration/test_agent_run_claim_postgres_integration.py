"""真实 PostgreSQL AgentRun 并发领取集成测试。

默认不连接外部基础设施；设置 TEST_POSTGRES_DSN 后可单独运行：

    uv run pytest -q -m "integration and requires_postgres" tests/integration/test_agent_run_claim_postgres_integration.py
"""

import asyncio
from datetime import datetime
import os
import sys
import uuid

import pytest
from cryptography.fernet import Fernet


def _require_real_asyncpg():
    for name in ("asyncpg", "asyncpg.pool"):
        module = sys.modules.get(name)
        if module is not None and not hasattr(module, "__file__"):
            sys.modules.pop(name, None)
    return pytest.importorskip("asyncpg")


@pytest.mark.integration
@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_two_workers_cannot_claim_same_run(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL AgentRun claim 测试")

    _require_real_asyncpg()
    sqlalchemy_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")
    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from app.db.models.agent_run import AgentRunEventModel, AgentRunModel
    from ai.runtime.agent_runs.crypto import encrypt_payload
    from ai.runtime.agent_runs import service as service_module

    async_url = dsn.replace("postgresql://", "postgresql+asyncpg://")
    engine = sqlalchemy_asyncio.create_async_engine(async_url)
    session_factory = sqlalchemy_asyncio.async_sessionmaker(engine, expire_on_commit=False)
    run_id = f"agent-interview-test-{uuid.uuid4()}"
    now = datetime.now()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: AgentRunModel.metadata.create_all(
                    sync_conn,
                    tables=[AgentRunModel.__table__, AgentRunEventModel.__table__],
                )
            )
        async with session_factory() as session:
            session.add(
                AgentRunModel(
                    id=run_id,
                    user_id="user-1",
                    task_type=service_module.TASK_TYPE_INTERVIEW_START,
                    agent_name="interview_start",
                    agent_version="1",
                    status="queued",
                    stage="queued",
                    idempotency_key=run_id,
                    payload_encrypted=encrypt_payload({"thread_id": "thread-1"}),
                    result=None,
                    error_message=None,
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    finished_at=None,
                )
            )
            await session.commit()

        monkeypatch.setattr(service_module, "async_session", session_factory)

        first, second = await asyncio.gather(
            service_module.AgentRunService().claim(run_id),
            service_module.AgentRunService().claim(run_id),
        )

        claimed = [item for item in (first, second) if item is not None]
        rejected = [item for item in (first, second) if item is None]
        assert len(claimed) == 1
        assert len(rejected) == 1
        claimed_run, payload = claimed[0]
        assert claimed_run.status == "running"
        assert claimed_run.attempts == 1
        assert payload == {"thread_id": "thread-1"}
    finally:
        async with engine.begin() as conn:
            await conn.execute(AgentRunEventModel.__table__.delete().where(AgentRunEventModel.run_id == run_id))
            await conn.execute(AgentRunModel.__table__.delete().where(AgentRunModel.id == run_id))
        await engine.dispose()
