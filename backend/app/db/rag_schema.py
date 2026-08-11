"""提供RAG模式相关后端功能。"""

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
    """定义RAG向量模式错误相关后端数据结构或服务组件。"""


def configured_embedding_dimension() -> int:
    """处理已配置嵌入维度相关后端逻辑。"""

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
    """校验RAG向量类型相关后端逻辑。"""

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
    """校验RAG向量连接相关后端逻辑。"""

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
    """校验RAG向量模式相关后端逻辑。"""

    async with engine.connect() as connection:
        return await validate_rag_vector_connection(
            connection,
            expected_dimension=expected_dimension,
        )


def read_rag_vector_type(connection: Any) -> str | None:
    """读取RAG向量类型相关后端逻辑。"""

    row = connection.execute(RAG_VECTOR_TYPE_SQL).fetchone()
    return str(row[0]) if row and row[0] is not None else None
