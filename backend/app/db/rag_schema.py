"""RAG pgvector schema preflight helpers.

The configured embedding dimension is a runtime setting, while PostgreSQL stores
the dimension in the ``rag_chunks.embedding`` column typmod.  These helpers make
that contract explicit before an indexing request reaches pgvector.
"""

from __future__ import annotations

import os
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


RAG_VECTOR_TYPE_SQL = """
SELECT pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
FROM pg_catalog.pg_attribute AS attribute
JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname = 'rag_chunks'
  AND attribute.attname = 'embedding'
  AND NOT attribute.attisdropped
"""

_VECTOR_TYPE_PATTERN = re.compile(r"^vector\((\d+)\)$")


class RagVectorSchemaError(RuntimeError):
    """Signal that the RAG vector column is missing, malformed, or dimensionally incompatible."""


def configured_embedding_dimension() -> int:
    """Return the positive ``EMBEDDING_DIM`` setting or fail with a stable configuration error."""

    raw_value = os.getenv("EMBEDDING_DIM", "1536").strip()
    try:
        dimension = int(raw_value)
    except ValueError as exc:
        raise RagVectorSchemaError("EMBEDDING_DIM must be a positive integer") from exc
    if dimension <= 0:
        raise RagVectorSchemaError("EMBEDDING_DIM must be a positive integer")
    return dimension


def validate_rag_vector_type(
    database_type: str | None,
    *,
    expected_dimension: int | None = None,
) -> int:
    """Validate a PostgreSQL formatted type such as ``vector(1536)`` against configuration.

    Args:
        database_type: Value returned by PostgreSQL ``format_type`` for the embedding column.
        expected_dimension: Expected dimension; defaults to the current ``EMBEDDING_DIM``.

    Returns:
        The validated database vector dimension.

    Raises:
        RagVectorSchemaError: The column is missing, is not fixed-dimension pgvector, or mismatches.
    """

    expected = expected_dimension or configured_embedding_dimension()
    if expected <= 0:
        raise RagVectorSchemaError("expected embedding dimension must be positive")
    if database_type is None:
        raise RagVectorSchemaError("public.rag_chunks.embedding column is missing")

    match = _VECTOR_TYPE_PATTERN.fullmatch(database_type.strip().lower())
    if match is None:
        raise RagVectorSchemaError(
            "public.rag_chunks.embedding must use a fixed-dimension pgvector type"
        )

    actual = int(match.group(1))
    if actual != expected:
        raise RagVectorSchemaError(
            "RAG vector dimension mismatch: "
            f"database={actual}, configured={expected}; migrate and rebuild the RAG index"
        )
    return actual


async def validate_rag_vector_connection(
    connection: AsyncConnection,
    *,
    expected_dimension: int | None = None,
) -> int:
    """Read and validate the RAG vector type through an existing async SQLAlchemy connection."""

    result = await connection.execute(text(RAG_VECTOR_TYPE_SQL))
    return validate_rag_vector_type(
        result.scalar_one_or_none(),
        expected_dimension=expected_dimension,
    )


async def validate_rag_vector_schema(
    engine: AsyncEngine,
    *,
    expected_dimension: int | None = None,
) -> int:
    """Open a short-lived connection and fail startup before an incompatible pgvector write."""

    async with engine.connect() as connection:
        return await validate_rag_vector_connection(
            connection,
            expected_dimension=expected_dimension,
        )


def read_rag_vector_type(connection: Any) -> str | None:
    """Read the formatted vector type through a synchronous DB-API style connection."""

    row = connection.execute(RAG_VECTOR_TYPE_SQL).fetchone()
    return str(row[0]) if row and row[0] is not None else None
