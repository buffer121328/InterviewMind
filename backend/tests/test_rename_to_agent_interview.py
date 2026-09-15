"""Behavioral tests for Task 1 runtime rename behavior."""

import os
import importlib
from pathlib import Path
from unittest.mock import patch

# tests/ is under backend/, so parents[1] = backend/
BACKEND_ROOT = Path(__file__).resolve().parents[1]
LEGACY_NAME = "agent_interview".replace("agent", "ai")


def _memory_request_config(*, dimensions: int = 1536) -> dict:
    """A fully hydrated request-level mem0 configuration for runtime tests."""
    return {
        "mem0_llm": {
            "api_key": "request-llm-key",
            "base_url": "https://api.deepseek.com/v1",
            "model": "request-chat-model",
            "provider": "openai",
        },
        "mem0_embedder": {
            "api_key": "request-embedding-key",
            "base_url": "https://embedding.example.test/v1",
            "model": "request-embedding-model",
            "provider": "openai",
            "dimensions": dimensions,
        },
    }


class TestDbConfigBehavior:
    """Verify backend/app/db/config.py derives defaults from POSTGRES_* env vars."""

    def test_get_postgres_config_uses_agent_interview_defaults(self):
        """Default config should use the renamed agent_interview user/db."""
        env = {
            "DATABASE_URL": "",
            "POSTGRES_USER": "",
            "POSTGRES_PASSWORD": "",
            "POSTGRES_HOST": "",
            "POSTGRES_PORT": "",
            "POSTGRES_DB": "",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.db.config as cfg
            importlib.reload(cfg)
            config = cfg.get_postgres_config()

        assert config["user"] == "agent_interview"
        assert config["database"] == "agent_interview"
        assert config["host"] == "localhost"
        assert config["port"] == 5432

    def test_get_postgres_config_password_from_env(self):
        """Password should come from POSTGRES_PASSWORD env var, not hardcoded."""
        env = {
            "DATABASE_URL": "",
            "POSTGRES_PASSWORD": "test_secret_42",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.db.config as cfg
            importlib.reload(cfg)
            config = cfg.get_postgres_config()

        assert config["password"] == "test_secret_42"

    def test_get_postgres_config_prefers_database_url(self):
        """When DATABASE_URL is set, it should take precedence."""
        env = {
            "DATABASE_URL": "postgresql://myuser:mypass@dbhost:5555/mydb",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.db.config as cfg
            importlib.reload(cfg)
            config = cfg.get_postgres_config()

        assert config["user"] == "myuser"
        assert config["password"] == "mypass"
        assert config["host"] == "dbhost"
        assert config["port"] == 5555
        assert config["database"] == "mydb"

    def test_get_postgres_config_strips_asyncpg_prefix(self):
        """Should handle postgresql+asyncpg:// URLs correctly."""
        env = {
            "DATABASE_URL": "postgresql+asyncpg://user:pw@host:5432/db",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.db.config as cfg
            importlib.reload(cfg)
            config = cfg.get_postgres_config()

        assert config["user"] == "user"
        assert config["database"] == "db"

    def test_no_hardcoded_password_in_module_source(self):
        """The config module source must not contain literal 'cheng123'."""
        content = (BACKEND_ROOT / "app" / "db" / "config.py").read_text(encoding="utf-8")
        assert "cheng123" not in content, (
            "config.py source still contains hardcoded password 'cheng123'"
        )

    def test_no_legacy_name_in_module_source(self):
        """The config module source must not contain the legacy project name."""
        content = (BACKEND_ROOT / "app" / "db" / "config.py").read_text(encoding="utf-8")
        assert LEGACY_NAME not in content, (
            "config.py source still contains the legacy project name"
        )


class TestAlembicEnvBehavior:
    """Verify alembic/env.py overrides URL from environment variables."""

    def test_env_py_overrides_url_from_database_url(self):
        """env.py should set sqlalchemy.url from DATABASE_URL when present."""
        content = (BACKEND_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
        assert "DATABASE_URL" in content
        assert "set_main_option" in content

    def test_alembic_ini_has_no_hardcoded_password(self):
        """alembic.ini must not contain a real password."""
        content = (BACKEND_ROOT / "alembic.ini").read_text(encoding="utf-8")
        assert "cheng123" not in content, (
            "alembic.ini still contains hardcoded password"
        )

    def test_alembic_ini_has_no_legacy_name(self):
        """alembic.ini must not contain the legacy project name."""
        content = (BACKEND_ROOT / "alembic.ini").read_text(encoding="utf-8")
        assert LEGACY_NAME not in content, (
            "alembic.ini still contains the legacy project name"
        )


class TestAgentMemoryConfigBehavior:
    """Verify mem0 keeps infrastructure settings but gets model data only from requests."""

    def test_mem0_pgvector_defaults_use_agent_interview(self):
        import ai.memory.config as mem_cfg

        config = mem_cfg.get_mem0_config(_memory_request_config())

        assert config is not None
        pg_cfg = config["vector_store"]["config"]
        assert pg_cfg["dbname"] == "agent_interview"
        assert pg_cfg["user"] == "agent_interview"

    def test_mem0_model_environment_fallback_is_disabled(self):
        env = {
            "MEM0_ENABLED": "true",
            "MEM0_LLM_API_KEY": "environment-llm-key",
            "MEM0_EMBEDDER_API_KEY": "environment-embedding-key",
            "OPENAI_API_KEY": "environment-openai-key",
        }
        with patch.dict(os.environ, env, clear=False):
            import ai.memory.config as mem_cfg
            importlib.reload(mem_cfg)
            assert mem_cfg.get_mem0_config() is None
            config = mem_cfg.get_mem0_config(_memory_request_config(dimensions=1024))

        assert config is not None
        assert config["llm"]["config"]["api_key"] == "request-llm-key"
        assert config["embedder"]["config"]["api_key"] == "request-embedding-key"
        assert config["embedder"]["config"]["embedding_dims"] == 1024

    def test_mem0_component_env_does_not_override_authoritative_database_url(self):
        env = {
            "MEM0_ENABLED": "true",
            "MEM0_PGVECTOR_URL": "",
            "DATABASE_URL": "postgresql://main_user:main_pass@main-db:5432/main_db",
        }
        with patch.dict(os.environ, env, clear=False):
            import ai.memory.config as mem_cfg
            importlib.reload(mem_cfg)
            config = mem_cfg.get_mem0_config(_memory_request_config())

        assert config is not None
        pg_cfg = config["vector_store"]["config"]
        assert pg_cfg["dbname"] == "main_db"
        assert pg_cfg["user"] == "main_user"
        assert pg_cfg["password"] == "main_pass"

    def test_mem0_frontend_channels_enable_memory_when_env_disabled(self):
        """Complete request api_config should enable mem0 without server-side model keys."""
        env = {
            "MEM0_ENABLED": "true",
        }
        api_config = {
            "mem0_llm": {
                "api_key": "deepseek-key",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-v4-flash",
            },
            "mem0_embedder": {
                "api_key": "dashscope-key",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "text-embedding-v4",
                "dimensions": 1024,
            },
        }
        with patch.dict(os.environ, env, clear=False):
            import ai.memory.config as mem_cfg
            importlib.reload(mem_cfg)
            config = mem_cfg.get_mem0_config(api_config)

        assert config is not None
        assert config["llm"]["config"]["api_key"] == "deepseek-key"
        assert config["llm"]["config"]["model"] == "deepseek-v4-flash"
        assert config["embedder"]["config"]["api_key"] == "dashscope-key"
        assert config["embedder"]["config"]["model"] == "text-embedding-v4"
        assert config["embedder"]["config"]["embedding_dims"] == 1024
        assert config["vector_store"]["config"]["embedding_model_dims"] == 1024
        assert config["vector_store"]["config"]["collection_name"] == "mem0_memories_d1024"


class TestAgentMemoryServiceRename:
    """Verify service.py metadata uses agent_interview."""

    def test_metadata_project_is_agent_interview(self):
        """service.py project metadata must reference agent_interview."""
        import re
        content = (BACKEND_ROOT / "ai" / "memory" / "service.py").read_text(encoding="utf-8")
        project_matches = re.findall(r'"project"\s*:\s*"([^"]+)"', content)
        assert project_matches, "No 'project' key found in metadata dicts"
        for val in project_matches:
            assert val == "agent_interview", f"Expected agent_interview, got {val}"


class TestInitPyCommentUpdate:
    """Verify __init__.py has no stale 'uv run' reference."""

    def test_no_uv_run_reference(self):
        content = (BACKEND_ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
        assert "uv run" not in content, (
            "__init__.py comment still references 'uv run'"
        )


def test_mem0_pgvector_uses_authoritative_database_url(monkeypatch):
    """Without an explicit mem0 DSN, pgvector must use the same database identity as SQLAlchemy."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://main_user:main%20pass@db.internal:6543/main_db",
    )
    monkeypatch.delenv("MEM0_PGVECTOR_URL", raising=False)
    monkeypatch.setenv("MEM0_PGVECTOR_HOST", "stale-host")
    monkeypatch.setenv("MEM0_PGVECTOR_DBNAME", "stale-db")
    monkeypatch.setenv("MEM0_PGVECTOR_USER", "stale-user")
    monkeypatch.setenv("MEM0_PGVECTOR_PASSWORD", "stale-password")

    import ai.memory.config as mem_cfg

    config = mem_cfg.get_mem0_config(_memory_request_config())

    assert config is not None
    pg_cfg = config["vector_store"]["config"]
    assert pg_cfg["host"] == "db.internal"
    assert pg_cfg["port"] == 6543
    assert pg_cfg["dbname"] == "main_db"
    assert pg_cfg["user"] == "main_user"
    assert pg_cfg["password"] == "main pass"


def test_mem0_pgvector_allows_complete_explicit_dsn(monkeypatch):
    """A dedicated pgvector database is accepted only through one complete explicit DSN."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://main_user:main_pass@main-db:5432/main_db",
    )
    monkeypatch.setenv(
        "MEM0_PGVECTOR_URL",
        "postgresql://memory_user:memory%20pass@memory-db:6432/memory_db",
    )

    import ai.memory.config as mem_cfg

    config = mem_cfg.get_mem0_config(_memory_request_config())

    assert config is not None
    pg_cfg = config["vector_store"]["config"]
    assert pg_cfg["host"] == "memory-db"
    assert pg_cfg["port"] == 6432
    assert pg_cfg["dbname"] == "memory_db"
    assert pg_cfg["user"] == "memory_user"
    assert pg_cfg["password"] == "memory pass"
