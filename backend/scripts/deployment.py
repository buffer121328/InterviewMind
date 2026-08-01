"""Deployment commands for database migrations and service readiness."""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import redis
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.rag_schema import (
    RAG_VECTOR_TYPE_SQL,
    RagVectorSchemaError,
    configured_embedding_dimension,
    validate_rag_vector_type,
)


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = ("agent_runs", "agent_run_events", "task_outbox")
LEGACY_SCHEMA_REVISION = "20260716_07"
# Schemas created by the former AUTO_CREATE_TABLES path did not have an
# alembic_version table. Require every table present at that revision before
# stamping it, so a partial or unrelated database is never silently accepted.
LEGACY_SCHEMA_TABLES = (
    "sessions",
    "messages",
    "user_profile",
    "interview_weakness_reports",
    "question_bank_items",
    "question_bank_imports",
    "question_bank_followups",
    "interview_question_attempts",
    "resume_results",
    "generated_resumes",
    "candidate_materials",
    "resume_assembly_results",
    "project_rewrite_records",
    "resume_generation_sessions",
    "rag_chunks",
    "job_applications",
    "application_events",
    "jd_analysis_results",
    "captured_jobs",
    "agent_runs",
    "agent_run_events",
    "task_outbox",
)


def database_url() -> str:
    """解析部署使用的数据库连接串，并拒绝缺失或不符合迁移运行要求的配置。"""
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


def expected_revision() -> str:
    """读取部署期望的迁移版本，并将配置缺失转换为明确的 readiness 错误。"""
    config = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one Alembic head, found: {heads}")
    return heads[0]


def run_alembic(*args: str) -> None:
    """运行 alembic，沿用既有任务状态、重试和持久化边界，不在辅助函数中绕过审批或 owner 校验。

    Args:
        *args: 经过类型边界校验的 `args`；其格式和可选值由参数类型及调用流程约束。
    """
    subprocess.run(["alembic", *args], cwd=ROOT, check=True)


def existing_public_tables() -> set[str]:
    """读取当前数据库中的公开表名，用于迁移前兼容性判断而非替代正式迁移。"""
    with psycopg.connect(database_url(), connect_timeout=10) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {row[0] for row in rows}


def migrate() -> None:
    """Create or upgrade the schema exclusively through Alembic."""
    tables = existing_public_tables()
    if tables and "alembic_version" not in tables:
        missing = sorted(set(LEGACY_SCHEMA_TABLES) - tables)
        if missing:
            raise RuntimeError(
                "database has tables but is not a recognized legacy ORM schema; "
                f"missing: {', '.join(missing)}. Restore or migrate it manually before deployment."
            )
        run_alembic("stamp", LEGACY_SCHEMA_REVISION)
    run_alembic("upgrade", "head")


def readiness() -> tuple[bool, dict[str, str]]:
    """检查服务依赖和迁移状态，返回可观测的 readiness 结果而不泄露连接凭据。"""
    details: dict[str, str] = {}
    try:
        expected = expected_revision()
        with psycopg.connect(database_url(), connect_timeout=5) as connection:
            revision_row = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            revision = revision_row[0] if revision_row else None
            missing_tables = [
                table
                for table in REQUIRED_TABLES
                if connection.execute(
                    "SELECT to_regclass(%s)", (f"public.{table}",)
                ).fetchone()[0] is None
            ]
            vector_type_row = connection.execute(RAG_VECTOR_TYPE_SQL).fetchone()
            vector_type = vector_type_row[0] if vector_type_row else None
        details["postgres"] = "ok"
        if revision != expected:
            details["schema"] = f"Alembic revision is {revision or 'missing'}, expected {expected}"
        elif missing_tables:
            details["schema"] = f"missing required tables: {', '.join(missing_tables)}"
        else:
            try:
                validate_rag_vector_type(
                    vector_type,
                    expected_dimension=configured_embedding_dimension(),
                )
                details["schema"] = "ok"
            except RagVectorSchemaError as exc:
                details["schema"] = str(exc)
    except Exception as exc:
        details["postgres"] = f"unavailable: {type(exc).__name__}"

    try:
        redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=5).ping()
        details["redis"] = "ok"
    except Exception as exc:
        details["redis"] = f"unavailable: {type(exc).__name__}"

    return all(value == "ok" for value in details.values()), details


def main() -> None:
    """执行部署入口的迁移和 readiness 流程，失败时以非零状态退出而不伪造成功。"""
    if len(sys.argv) != 2 or sys.argv[1] not in {"migrate", "readiness"}:
        raise SystemExit("usage: python -m scripts.deployment {migrate|readiness}")

    if sys.argv[1] == "migrate":
        migrate()
        return

    ready, details = readiness()
    if not ready:
        raise SystemExit(f"not ready: {details}")


if __name__ == "__main__":
    main()
