"""支持请求级配置的 RAG 向量维度（多维度共存）。

Revision ID: 20260815_16
Revises: 20260810_15
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260815_16"
down_revision: str | Sequence[str] | None = "20260810_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保留既有向量的同时，允许不同维度的向量行共存。"""

    # ① 新增维度记录列，并用 vector_dims 回填存量向量的真实维度。
    op.add_column(
        "rag_chunks",
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE rag_chunks "
        "SET embedding_dimension = vector_dims(embedding) "
        "WHERE embedding IS NOT NULL"
    )
    # ② 丢弃固定 1536 维的列类型与旧索引，改为不带维度的 vector 列。
    op.execute("DROP INDEX IF EXISTS idx_rag_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE rag_chunks "
        "ALTER COLUMN embedding TYPE vector USING embedding::vector"
    )
    # ③ 安全关卡：约束 embedding 与 embedding_dimension 必须同时为空或同时有效且一致。
    op.create_check_constraint(
        "ck_rag_chunks_embedding_dimension",
        "rag_chunks",
        "(embedding IS NULL AND embedding_dimension IS NULL) OR "
        "(embedding IS NOT NULL AND embedding_dimension BETWEEN 1 AND 16000 "
        "AND embedding_dimension = vector_dims(embedding))",
    )
    # ④ 按维度分别建部分 HNSW 索引，只覆盖已完成且激活的向量。
    for dimensions in (1024, 1536):
        op.execute(
            f"CREATE INDEX idx_rag_chunks_embedding_hnsw_{dimensions} "
            "ON rag_chunks USING hnsw "
            f"((embedding::vector({dimensions})) vector_cosine_ops) "
            f"WHERE embedding_dimension = {dimensions} "
            "AND embedding_status = 'completed' AND is_active = TRUE"
        )


def downgrade() -> None:
    """仅当所有向量都是 1536 维时，才回退为旧的固定维度列。"""

    # 安全关卡：存在非 1536 维向量时直接抛错，避免静默截断数据。
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "SELECT 1 FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND vector_dims(embedding) <> 1536"
        ") THEN "
        "RAISE EXCEPTION 'cannot downgrade rag_chunks: non-1536 vectors exist'; "
        "END IF; END $$"
    )
    # ① 删除按维度拆分的 HNSW 索引与一致性约束。
    for dimensions in (1024, 1536):
        op.execute(f"DROP INDEX IF EXISTS idx_rag_chunks_embedding_hnsw_{dimensions}")
    op.drop_constraint(
        "ck_rag_chunks_embedding_dimension",
        "rag_chunks",
        type_="check",
    )
    # ② 恢复固定 1536 维列类型，删除维度记录列并重建原部分索引。
    op.execute(
        "ALTER TABLE rag_chunks "
        "ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)"
    )
    op.drop_column("rag_chunks", "embedding_dimension")
    op.execute(
        "CREATE INDEX idx_rag_chunks_embedding_hnsw ON rag_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding_status = 'completed' AND is_active = TRUE"
    )
