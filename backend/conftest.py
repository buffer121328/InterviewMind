"""
Root conftest: adds backend/ to sys.path so `app.*` imports work in tests.
Also pre-mocks heavy optional dependencies (pgvector, asyncpg, etc.) that are
not needed for unit/eval tests but are imported transitively by app modules.
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Test collection may import optional evaluation/memory SDKs before an autouse
# fixture can run.  Keep their vendor telemetry offline by default at process
# startup; process env values win over any .env loaded later by those SDKs.
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("DEEPEVAL_TELEMETRY_ENABLED", "false")
os.environ.setdefault("ERROR_REPORTING", "false")

# backend/ directory (where this conftest.py lives)
_BACKEND_DIR = str(Path(__file__).resolve().parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ---------------------------------------------------------------------------
# Pre-mock pgvector with a Vector class that SQLAlchemy accepts
# ---------------------------------------------------------------------------

from sqlalchemy.types import UserDefinedType


class _FakeVector(UserDefinedType):
    """Minimal pgvector.sqlalchemy.Vector stand-in for test-time imports."""

    cache_ok = True

    def __init__(self, dim=None):
        """初始化当前对象实例。

        Args:
            dim: 调用方传入的 `dim` 参数。
        """
        self.dim = dim

    def get_col_spec(self, **kw):
        """获取 `col spec`。

        Args:
            **kw: 调用方传入的 `kw` 参数。
        """
        return f"vector({self.dim})" if self.dim else "vector"


def _ensure_mock_module(name: str, attrs: dict | None = None):
    """Insert a mock module into sys.modules if not already present."""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if attrs:
            mod.__dict__.update(attrs)
        sys.modules[name] = mod


# pgvector
_pgvector_mod = types.ModuleType("pgvector")
_pgvector_mod.__path__ = []
_pgvector_sqlalchemy = types.ModuleType("pgvector.sqlalchemy")
_pgvector_sqlalchemy.Vector = _FakeVector
_pgvector_mod.sqlalchemy = _pgvector_sqlalchemy
sys.modules.setdefault("pgvector", _pgvector_mod)
sys.modules.setdefault("pgvector.sqlalchemy", _pgvector_sqlalchemy)

# asyncpg (not needed for tests)
_ensure_mock_module("asyncpg")
_ensure_mock_module("asyncpg.pool")

# langgraph-checkpoint-postgres
_ensure_mock_module("langgraph_checkpoint_postgres")
_ensure_mock_module("langgraph.checkpoint.postgres")


@pytest.fixture(autouse=True)
def disable_external_langfuse_by_default(monkeypatch):
    """Keep offline tests from using real Langfuse credentials loaded from `.env`."""

    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", "false")
    try:
        import observability

        observability._reset_langfuse_for_tests()
    except Exception:
        # Import-order edge cases should not fail collection; tests that need
        # Langfuse explicitly configure a fake client in their own fixture/body.
        pass
    yield
    try:
        import observability

        observability._reset_langfuse_for_tests()
    except Exception:
        pass


def pytest_collection_modifyitems(items):
    """Skip tests whose explicitly marked external dependencies are unavailable."""
    requirements = (
        ("requires_postgres", "TEST_POSTGRES_DSN", "requires TEST_POSTGRES_DSN"),
        ("requires_redis", "TEST_REDIS_URL", "requires TEST_REDIS_URL"),
        ("requires_dramatiq", "TEST_REDIS_URL", "requires TEST_REDIS_URL and a Dramatiq worker"),
        (
            "requires_boss_browser",
            "TEST_BOSS_BROWSER_SERVICE_URL",
            "requires TEST_BOSS_BROWSER_SERVICE_URL and TEST_BOSS_BROWSER_SERVICE_TOKEN",
        ),
        ("llm", "OPENAI_API_KEY", "requires OPENAI_API_KEY"),
    )
    for item in items:
        for marker, environment_variable, reason in requirements:
            if marker in item.keywords and not os.getenv(environment_variable):
                item.add_marker(pytest.mark.skip(reason=reason))
                break
