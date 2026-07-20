"""Behavioral tests for Task 1 runtime rename behavior."""

import os
import importlib
from pathlib import Path
from unittest.mock import patch

# tests/ is under backend/, so parents[1] = backend/
BACKEND_ROOT = Path(__file__).resolve().parents[1]
LEGACY_NAME = "agent_interview".replace("agent", "ai")


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
            import app.infrastructure.db.config as cfg
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
            import app.infrastructure.db.config as cfg
            importlib.reload(cfg)
            config = cfg.get_postgres_config()

        assert config["password"] == "test_secret_42"

    def test_get_postgres_config_prefers_database_url(self):
        """When DATABASE_URL is set, it should take precedence."""
        env = {
            "DATABASE_URL": "postgresql://myuser:mypass@dbhost:5555/mydb",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.infrastructure.db.config as cfg
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
            import app.infrastructure.db.config as cfg
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
    """Verify mem0 pgvector defaults align with agent_interview naming."""

    def test_mem0_pgvector_defaults_use_agent_interview(self):
        """Default pgvector dbname/user should be agent_interview, not postgres."""
        env = {
            "MEM0_PGVECTOR_DBNAME": "",
            "MEM0_PGVECTOR_USER": "",
            "MEM0_PGVECTOR_PASSWORD": "",
            "POSTGRES_DB": "",
            "POSTGRES_USER": "",
            "POSTGRES_PASSWORD": "",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.infrastructure.memory.config as mem_cfg
            importlib.reload(mem_cfg)
            config = mem_cfg.get_mem0_config()

        assert config is not None
        pg_cfg = config["vector_store"]["config"]
        assert pg_cfg["dbname"] == "agent_interview"
        assert pg_cfg["user"] == "agent_interview"

    def test_mem0_pgvector_falls_back_to_postgres_env(self):
        """pgvector config should fall back to POSTGRES_* env vars."""
        env = {
            "MEM0_PGVECTOR_DBNAME": "",
            "MEM0_PGVECTOR_USER": "",
            "MEM0_PGVECTOR_PASSWORD": "",
            "POSTGRES_DB": "custom_db",
            "POSTGRES_USER": "custom_user",
            "POSTGRES_PASSWORD": "custom_pass",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.infrastructure.memory.config as mem_cfg
            importlib.reload(mem_cfg)
            config = mem_cfg.get_mem0_config()

        pg_cfg = config["vector_store"]["config"]
        assert pg_cfg["dbname"] == "custom_db"
        assert pg_cfg["user"] == "custom_user"
        assert pg_cfg["password"] == "custom_pass"

    def test_mem0_explicit_env_overrides_postgres_fallback(self):
        """MEM0_PGVECTOR_* env vars should take precedence over POSTGRES_*."""
        env = {
            "MEM0_PGVECTOR_DBNAME": "mem0专属",
            "MEM0_PGVECTOR_USER": "mem0user",
            "MEM0_PGVECTOR_PASSWORD": "mem0pass",
            "POSTGRES_DB": "agent_interview",
            "POSTGRES_USER": "agent_interview",
            "POSTGRES_PASSWORD": "cheng123",
        }
        with patch.dict(os.environ, env, clear=False):
            import app.infrastructure.memory.config as mem_cfg
            importlib.reload(mem_cfg)
            config = mem_cfg.get_mem0_config()

        pg_cfg = config["vector_store"]["config"]
        assert pg_cfg["dbname"] == "mem0专属"
        assert pg_cfg["user"] == "mem0user"
        assert pg_cfg["password"] == "mem0pass"


class TestAgentMemoryServiceRename:
    """Verify service.py metadata uses agent_interview."""

    def test_metadata_project_is_agent_interview(self):
        """service.py project metadata must reference agent_interview."""
        import re
        content = (BACKEND_ROOT / "app" / "services" / "agent_memory" / "service.py").read_text(encoding="utf-8")
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
