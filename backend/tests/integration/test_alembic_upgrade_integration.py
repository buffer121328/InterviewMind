"""真实 PostgreSQL Alembic 升级集成测试。

默认不连接外部基础设施；设置 TEST_POSTGRES_DSN 后可单独运行：

    uv run pytest -q -m "integration and requires_postgres" tests/integration/test_alembic_upgrade_integration.py
"""

from pathlib import Path
import os
import sys

import pytest
from sqlalchemy import create_engine, text


def _require_real_asyncpg():
    for name in ("asyncpg", "asyncpg.pool"):
        module = sys.modules.get(name)
        if module is not None and not hasattr(module, "__file__"):
            sys.modules.pop(name, None)
    return pytest.importorskip("asyncpg")


def _require_reset_permission() -> None:
    if os.getenv("TEST_POSTGRES_ALLOW_RESET") != "1":
        pytest.skip("设置 TEST_POSTGRES_ALLOW_RESET=1 才会重置临时测试库")


def _sync_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1).replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


def _reset_public_schema(dsn: str) -> None:
    with create_engine(_sync_dsn(dsn), isolation_level="AUTOCOMMIT").connect() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _table_names(dsn: str) -> set[str]:
    with create_engine(_sync_dsn(dsn)).connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public'"
                )
            ).scalars()
        )


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_alembic_upgrades_test_database_to_head(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL Alembic 升级测试")

    _require_reset_permission()
    _require_real_asyncpg()
    alembic_command = pytest.importorskip("alembic.command")
    alembic_config = pytest.importorskip("alembic.config")

    backend_dir = Path(__file__).resolve().parents[2]
    config = alembic_config.Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    monkeypatch.setenv("DATABASE_URL", dsn)

    _reset_public_schema(dsn)
    alembic_command.upgrade(config, "head")
    assert {
        "sessions",
        "messages",
        "user_profile",
        "resume_results",
        "generated_resumes",
        "candidate_materials",
        "resume_assembly_results",
        "project_rewrite_records",
        "interview_weakness_reports",
        "question_bank_items",
        "question_bank_imports",
        "question_bank_followups",
        "interview_question_attempts",
        "rag_chunks",
        "job_applications",
        "application_events",
        "jd_analysis_results",
        "captured_jobs",
        "agent_runs",
        "agent_run_events",
        "resume_generation_sessions",
        "task_outbox",
    }.issubset(_table_names(dsn))


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_alembic_upgrades_stamped_create_all_schema_to_latest(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL deployment.migrate 测试")
    _require_reset_permission()

    _require_real_asyncpg()
    monkeypatch.setenv("DATABASE_URL", dsn)

    _reset_public_schema(dsn)
    from app.db.models import Base
    import deployment

    engine = create_engine(_sync_dsn(dsn))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            Base.metadata.create_all(connection)
        assert "alembic_version" not in _table_names(dsn)

        deployment.migrate()

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            obsolete_count = connection.execute(
                text(
                    "SELECT count(*) "
                    "FROM pg_attribute AS attribute "
                    "JOIN pg_class AS relation ON relation.oid = attribute.attrelid "
                    "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND relation.relname = 'agent_runs' "
                    "AND attribute.attname = ANY(:obsolete_columns) "
                    "AND NOT attribute.attisdropped"
                ),
                {
                    "obsolete_columns": [
                        "model_provider",
                        "model_name",
                        "model_member",
                        "request_latency_ms",
                        "input_tokens",
                        "output_tokens",
                        "fallback_count",
                        "fallback_path",
                        "estimated_cost_usd",
                        "model_error_type",
                    ]
                },
            ).scalar_one()
        assert revision == deployment.expected_revision()
        assert obsolete_count == 0
    finally:
        engine.dispose()
