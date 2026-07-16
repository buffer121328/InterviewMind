"""真实 PostgreSQL Alembic 升级集成测试。

默认不连接外部基础设施；设置 TEST_POSTGRES_DSN 后可单独运行：

    uv run pytest -q -m "integration and requires_postgres" tests/integration/test_alembic_upgrade_integration.py
"""

from pathlib import Path
import os
import sys

import pytest


def _require_real_asyncpg():
    for name in ("asyncpg", "asyncpg.pool"):
        module = sys.modules.get(name)
        if module is not None and not hasattr(module, "__file__"):
            sys.modules.pop(name, None)
    return pytest.importorskip("asyncpg")


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_alembic_upgrades_test_database_to_head(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL Alembic 升级测试")

    _require_real_asyncpg()
    alembic_command = pytest.importorskip("alembic.command")
    alembic_config = pytest.importorskip("alembic.config")

    backend_dir = Path(__file__).resolve().parents[2]
    config = alembic_config.Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    monkeypatch.setenv("DATABASE_URL", dsn)

    alembic_command.upgrade(config, "head")


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_alembic_upgrades_from_previous_head_snapshot_to_latest(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL Alembic 旧 head 升级测试")
    if os.getenv("TEST_POSTGRES_ALLOW_RESET") != "1":
        pytest.skip("设置 TEST_POSTGRES_ALLOW_RESET=1 才会重置临时测试库到旧 head")

    _require_real_asyncpg()
    alembic_command = pytest.importorskip("alembic.command")
    alembic_config = pytest.importorskip("alembic.config")

    backend_dir = Path(__file__).resolve().parents[2]
    config = alembic_config.Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    monkeypatch.setenv("DATABASE_URL", dsn)

    previous_head = "20260716_05"
    alembic_command.downgrade(config, "base")
    alembic_command.upgrade(config, previous_head)
    alembic_command.upgrade(config, "head")
