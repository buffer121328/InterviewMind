"""真实 PostgreSQL checkpoint 集成测试。

默认不连接外部基础设施；设置 TEST_POSTGRES_DSN 后可单独运行：

    uv run pytest -q -m "integration and requires_postgres" tests/integration/test_postgres_checkpoint_integration.py
"""

import os
import sys
import uuid

import pytest


def _import_real_async_postgres_saver():
    """绕过根 conftest 的轻量 mock，按需导入真实 PostgreSQL saver。"""
    mocked_parent = sys.modules.get("langgraph.checkpoint.postgres")
    if mocked_parent is not None and not hasattr(mocked_parent, "__path__"):
        sys.modules.pop("langgraph.checkpoint.postgres", None)
    postgres = pytest.importorskip("langgraph.checkpoint.postgres.aio")
    return postgres.AsyncPostgresSaver


@pytest.mark.integration
@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_async_postgres_saver_setup_against_real_database():
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL checkpoint 测试")

    async_postgres_saver = _import_real_async_postgres_saver()
    context = async_postgres_saver.from_conn_string(dsn)
    async with context as saver:
        await saver.setup()

    assert saver is not None


@pytest.mark.integration
@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_async_postgres_saver_persists_checkpoint_after_reopen():
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL checkpoint 测试")

    async_postgres_saver = _import_real_async_postgres_saver()
    checkpoint_base = pytest.importorskip("langgraph.checkpoint.base")
    thread_id = f"agent-interview-test-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = checkpoint_base.empty_checkpoint()
    checkpoint["channel_values"] = {"stage": "persisted"}
    checkpoint["channel_versions"] = {"stage": "00000000000000000000000000000001.0.0"}
    checkpoint["versions_seen"] = {}

    first_context = async_postgres_saver.from_conn_string(dsn)
    async with first_context as saver:
        await saver.setup()
        saved_config = await saver.aput(
            config,
            checkpoint,
            {"source": "input", "step": 1, "writes": {}},
            {"stage": "00000000000000000000000000000001.0.0"},
        )

    second_context = async_postgres_saver.from_conn_string(dsn)
    async with second_context as reopened_saver:
        loaded = await reopened_saver.aget(saved_config)

    assert loaded is not None
    assert loaded["channel_values"] == {"stage": "persisted"}
