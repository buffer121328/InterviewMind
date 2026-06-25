"""
Root conftest: adds backend/ to sys.path so `app.*` imports work in tests.
Also pre-mocks heavy optional dependencies (pgvector, asyncpg, etc.) that are
not needed for unit/eval tests but are imported transitively by app modules.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

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
        self.dim = dim

    def get_col_spec(self, **kw):
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
