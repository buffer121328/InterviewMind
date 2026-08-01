"""Unit coverage for the RAG pgvector schema preflight boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_validate_rag_vector_type_accepts_matching_fixed_dimension() -> None:
    """A fixed pgvector column matching configuration is accepted."""

    from app.db.rag_schema import validate_rag_vector_type

    assert validate_rag_vector_type("vector(1536)", expected_dimension=1536) == 1536


@pytest.mark.parametrize("database_type", [None, "vector", "text", "vector(not-a-number)"])
def test_validate_rag_vector_type_rejects_missing_or_unbounded_column(
    database_type: str | None,
) -> None:
    """Missing and non-fixed vector columns fail before indexing."""

    from app.db.rag_schema import RagVectorSchemaError, validate_rag_vector_type

    with pytest.raises(RagVectorSchemaError):
        validate_rag_vector_type(database_type, expected_dimension=1536)


def test_validate_rag_vector_type_reports_dimension_mismatch_without_dsn() -> None:
    """Mismatch errors expose only dimensions and remediation, never database credentials."""

    from app.db.rag_schema import RagVectorSchemaError, validate_rag_vector_type

    with pytest.raises(RagVectorSchemaError) as exc_info:
        validate_rag_vector_type("vector(768)", expected_dimension=1536)

    message = str(exc_info.value)
    assert "database=768" in message
    assert "configured=1536" in message
    assert "postgresql://" not in message


@pytest.mark.asyncio
async def test_validate_rag_vector_connection_queries_catalog_before_writes() -> None:
    """The async preflight reads PostgreSQL catalog metadata and validates its scalar value."""

    from app.db.rag_schema import validate_rag_vector_connection

    calls: list[object] = []

    class Connection:
        async def execute(self, statement):
            calls.append(statement)
            return SimpleNamespace(scalar_one_or_none=lambda: "vector(1536)")

    assert (
        await validate_rag_vector_connection(  # type: ignore[arg-type]
            Connection(),
            expected_dimension=1536,
        )
        == 1536
    )
    assert "pg_catalog.pg_attribute" in str(calls[0])


def test_configured_embedding_dimension_rejects_invalid_environment(monkeypatch) -> None:
    """Invalid EMBEDDING_DIM values fail with a stable configuration error."""

    from app.db.rag_schema import RagVectorSchemaError, configured_embedding_dimension

    monkeypatch.setenv("EMBEDDING_DIM", "secret-invalid-value")
    with pytest.raises(RagVectorSchemaError, match="positive integer"):
        configured_embedding_dimension()


def test_deployment_readiness_reports_vector_mismatch_as_schema_failure(monkeypatch) -> None:
    """Deployment readiness keeps PostgreSQL reachable while exposing a safe schema mismatch."""

    from app.entrypoints import deployment

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, params=None):
            query_text = str(query)
            if "version_num" in query_text:
                return SimpleNamespace(fetchone=lambda: ("head-revision",))
            if "to_regclass" in query_text:
                assert params
                return SimpleNamespace(fetchone=lambda: (params[0],))
            if "format_type" in query_text:
                return SimpleNamespace(fetchone=lambda: ("vector(768)",))
            raise AssertionError(f"unexpected readiness query: {query_text}")

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/test")
    monkeypatch.setenv("REDIS_URL", "redis://cache.example/0")
    monkeypatch.setenv("EMBEDDING_DIM", "1536")
    monkeypatch.setattr(deployment, "expected_revision", lambda: "head-revision")
    monkeypatch.setattr(deployment.psycopg, "connect", lambda *_args, **_kwargs: Connection())
    monkeypatch.setattr(
        deployment.redis.Redis,
        "from_url",
        lambda *_args, **_kwargs: SimpleNamespace(ping=lambda: True),
    )

    ready, details = deployment.readiness()

    assert ready is False
    assert details["postgres"] == "ok"
    assert details["redis"] == "ok"
    assert "database=768" in details["schema"]
    assert "configured=1536" in details["schema"]
    assert "secret" not in str(details)
