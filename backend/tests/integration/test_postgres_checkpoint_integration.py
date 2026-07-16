"""真实 PostgreSQL checkpoint 集成测试。

默认不连接外部基础设施；设置 TEST_POSTGRES_DSN 后可单独运行：

    uv run pytest -q -m "integration and requires_postgres" tests/integration/test_postgres_checkpoint_integration.py
"""

import os

import pytest


@pytest.mark.integration
@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_async_postgres_saver_setup_against_real_database():
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL checkpoint 测试")

    postgres = pytest.importorskip("langgraph.checkpoint.postgres.aio")
    context = postgres.AsyncPostgresSaver.from_conn_string(dsn)
    async with context as saver:
        await saver.setup()

    assert saver is not None
