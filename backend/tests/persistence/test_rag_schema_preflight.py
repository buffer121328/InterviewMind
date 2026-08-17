"""Unit coverage for the RAG pgvector schema preflight boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_validate_rag_vector_type_accepts_flexible_dimension() -> None:
    """The flexible pgvector column and explicit dimension metadata are accepted."""

    from app.db.rag_schema import validate_rag_vector_type

    assert validate_rag_vector_type("vector", expected_dimension=1536) == 1536


@pytest.mark.parametrize("database_type", [None, "text", "vector(not-a-number)", "vector(1536)"])
def test_validate_rag_vector_type_rejects_missing_invalid_or_legacy_column(
    database_type: str | None,
) -> None:
    """Missing and non-fixed vector columns fail before indexing."""

    from app.db.rag_schema import RagVectorSchemaError, validate_rag_vector_type

    with pytest.raises(RagVectorSchemaError):
        validate_rag_vector_type(database_type, expected_dimension=1536)


def test_validate_rag_vector_type_requires_dimension_metadata_without_dsn() -> None:
    """Missing dimension metadata is reported without database credentials."""

    from app.db.rag_schema import RagVectorSchemaError, validate_rag_vector_type

    with pytest.raises(RagVectorSchemaError) as exc_info:
        validate_rag_vector_type("vector", expected_dimension=1536, has_dimension_column=False)

    message = str(exc_info.value)
    assert "embedding_dimension" in message
    assert "postgresql://" not in message


@pytest.mark.asyncio
async def test_validate_rag_vector_connection_queries_catalog_before_writes() -> None:
    """The async preflight reads PostgreSQL catalog metadata and validates its scalar value."""

    from app.db.rag_schema import validate_rag_vector_connection

    calls: list[object] = []

    class Connection:
        async def execute(self, statement):
            calls.append(statement)
            value = "vector" if len(calls) == 1 else True
            return SimpleNamespace(scalar_one_or_none=lambda: value)

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

    from scripts import deployment

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
                return SimpleNamespace(fetchone=lambda: ("vector(1536)",))
            if "embedding_dimension" in query_text:
                return SimpleNamespace(fetchone=lambda: (False,))
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
    assert "embedding_dimension" in details["schema"] or "fixed-dimension" in details["schema"]
    assert "secret" not in str(details)
