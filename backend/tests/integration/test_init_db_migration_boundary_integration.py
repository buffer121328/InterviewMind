"""init_db 与动态向量迁移职责边界的真实 PostgreSQL 集成测试。

在独立临时数据库上验证：迁移 head（含迁移 16）之后运行 `init_db()`
（模拟 AUTO_CREATE_TABLES=true 的开发启动）不会重建旧单维度 HNSW 索引。

默认不连接外部基础设施；设置 TEST_POSTGRES_DSN 后可单独运行：

    uv run pytest -q -m "integration and requires_postgres" \
        tests/integration/test_init_db_migration_boundary_integration.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _require_real_asyncpg() -> None:
    """清掉可能的命名空间占位模块，确保后续导入真实 asyncpg。"""

    for name in ("asyncpg", "asyncpg.pool"):
        module = sys.modules.get(name)
        if module is not None and not hasattr(module, "__file__"):
            sys.modules.pop(name, None)


def _server_dsn(dsn: str) -> str:
    head, _, _ = dsn.rpartition("/")
    return f"{head}/postgres"


@pytest.mark.integration
@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_init_db_after_migration_keeps_dynamic_hnsw_only(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行 init_db 迁移边界测试")
    psycopg = pytest.importorskip("psycopg")
    _require_real_asyncpg()

    test_db = f"agent_interview_init_boundary_{uuid.uuid4().hex[:8]}"
    test_dsn = f"{dsn.rstrip('/').rsplit('/', 1)[0]}/{test_db}"
    with psycopg.connect(_server_dsn(dsn), connect_timeout=10, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolcreatedb AND rolname = current_user").fetchone():
            pytest.skip("测试账号无 CREATEDB 权限，跳过 init_db 边界集成测试")
        conn.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
        conn.execute(f'CREATE DATABASE "{test_db}"')

    try:
        env = {**os.environ, "DATABASE_URL": test_dsn}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, f"alembic upgrade 失败:\n{result.stderr[-2000:]}"

        from sqlalchemy.ext.asyncio import create_async_engine

        import app.db.models.base as db_base

        async_engine = create_async_engine(test_dsn.replace("postgresql://", "postgresql+asyncpg://"))
        monkeypatch.setattr(db_base, "engine", async_engine)
        await db_base.init_db()  # 模拟 AUTO_CREATE_TABLES=true 的开发启动
        await async_engine.dispose()

        sync_test_dsn = test_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        with psycopg.connect(sync_test_dsn, connect_timeout=10) as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'rag_chunks'"
                ).fetchall()
            }
    finally:
        with psycopg.connect(_server_dsn(dsn), connect_timeout=10, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')

    exact_names = {name for name in indexes if not name.startswith("idx_rag_chunks_embedding_hnsw_")}
    assert "idx_rag_chunks_embedding_hnsw" not in indexes
    assert "idx_rag_chunks_embedding_hnsw_1024" in indexes
    assert "idx_rag_chunks_embedding_hnsw_1536" in indexes
    assert "idx_rag_chunks_content_trgm" in indexes
    assert "idx_rag_chunks_metadata_gin" in indexes
    assert exact_names  # 防御断言失效：索引集合不应为空
