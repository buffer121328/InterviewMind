"""Real PostgreSQL RAG vector-dimension acceptance test.

The test is read-only and skipped unless ``TEST_POSTGRES_DSN`` is explicitly set:

    uv run pytest -q -m "integration and requires_postgres" \
        tests/integration/test_rag_vector_dimension_integration.py
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_real_rag_vector_column_supports_configured_embedding_dimensions() -> None:
    """Read the real pgvector schema and verify flexible dimension metadata."""

    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("需要 TEST_POSTGRES_DSN 才运行真实 PostgreSQL RAG 维度测试")

    psycopg = pytest.importorskip("psycopg")
    from app.db.rag_schema import (
        configured_embedding_dimension,
        has_rag_vector_dimension_column,
        read_rag_vector_type,
        validate_rag_vector_type,
    )

    sync_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    with psycopg.connect(sync_dsn, connect_timeout=10) as connection:
        database_type = read_rag_vector_type(connection)
        has_dimension_column = has_rag_vector_dimension_column(connection)

    assert validate_rag_vector_type(
        database_type,
        expected_dimension=configured_embedding_dimension(),
        has_dimension_column=has_dimension_column,
    ) == configured_embedding_dimension()
