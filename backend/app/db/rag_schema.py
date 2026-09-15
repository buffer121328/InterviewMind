"""RAG 向量模式校验：检查 rag_chunks.embedding 列类型与维度元数据列。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


# 查询 rag_chunks.embedding 列类型的 SQL。
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

# 查询 rag_chunks.embedding_dimension 列是否存在的 SQL。
RAG_VECTOR_DIMENSION_COLUMN_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'rag_chunks'
      AND attribute.attname = 'embedding_dimension'
      AND NOT attribute.attisdropped
)
"""

# 匹配 vector 类型（可选固定维度）的正则。
_VECTOR_TYPE_PATTERN = re.compile(r"^vector(?:\((\d+)\))?$")


class RagVectorSchemaError(RuntimeError):
    """RAG 向量模式不符合预期。"""


def validate_rag_vector_type(
    database_type: str | None,
    *,
    expected_dimension: int | None = None,
    has_dimension_column: bool = True,
) -> int | None:
    """校验 rag_chunks.embedding 使用无固定维度的 pgvector 类型。

    Args:
        database_type: 数据库中的列类型文本。
        expected_dimension: 调用方正在使用的请求级维度；缺省时仅校验动态向量 schema。
        has_dimension_column: 是否存在 embedding_dimension 维度元数据列。

    Raises:
        RagVectorSchemaError: 列缺失、类型不对或仍是固定维度。
    """
    if expected_dimension is not None and expected_dimension <= 0:
        raise RagVectorSchemaError("expected embedding dimension must be positive")
    if database_type is None:
        raise RagVectorSchemaError("public.rag_chunks.embedding column is missing")
    if not has_dimension_column:
        raise RagVectorSchemaError("public.rag_chunks.embedding_dimension column is missing")

    match = _VECTOR_TYPE_PATTERN.fullmatch(database_type.strip().lower())
    if match is None:
        raise RagVectorSchemaError(
            "public.rag_chunks.embedding must use the pgvector vector type"
        )
    fixed_dimension = match.group(1)
    if fixed_dimension is not None:
        raise RagVectorSchemaError(
            "RAG vector schema is still fixed-dimension: "
            f"database={fixed_dimension}; run the dynamic embedding dimension migration"
        )
    return expected_dimension


async def validate_rag_vector_connection(
    connection: AsyncConnection,
    *,
    expected_dimension: int | None = None,
) -> int | None:
    """在给定连接上校验 RAG 向量模式。

    Args:
        connection: 异步数据库连接。
        expected_dimension: 调用方正在使用的请求级维度；缺省时仅校验动态向量 schema。
    """
    result = await connection.execute(text(RAG_VECTOR_TYPE_SQL))
    dimension_result = await connection.execute(text(RAG_VECTOR_DIMENSION_COLUMN_SQL))
    return validate_rag_vector_type(
        result.scalar_one_or_none(),
        expected_dimension=expected_dimension,
        has_dimension_column=bool(dimension_result.scalar_one_or_none()),
    )


async def validate_rag_vector_schema(
    engine: AsyncEngine,
    *,
    expected_dimension: int | None = None,
) -> int | None:
    """连接数据库校验 RAG 向量模式。

    Args:
        engine: 异步数据库引擎。
        expected_dimension: 调用方正在使用的请求级维度；缺省时仅校验动态向量 schema。
    """
    async with engine.connect() as connection:
        return await validate_rag_vector_connection(
            connection,
            expected_dimension=expected_dimension,
        )


def read_rag_vector_type(connection: Any) -> str | None:
    """同步读取 rag_chunks.embedding 列类型。

    Args:
        connection: 数据库连接。
    """
    row = connection.execute(RAG_VECTOR_TYPE_SQL).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def has_rag_vector_dimension_column(connection: Any) -> bool:
    """返回是否存在灵活的向量维度元数据列。

    Args:
        connection: 数据库连接。
    """
    row = connection.execute(RAG_VECTOR_DIMENSION_COLUMN_SQL).fetchone()
    return bool(row and row[0])
