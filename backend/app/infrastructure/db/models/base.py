"""
SQLAlchemy 2.0 异步 ORM 基础设施
替代原 db/base.py 的 DatabaseManager
"""

import logging
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession, async_sessionmaker
from app.infrastructure.db.config import DATABASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLAlchemy 2.0 声明式基类
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 异步引擎（底层驱动 = asyncpg）
# ---------------------------------------------------------------------------

_async_db_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine: AsyncEngine = create_async_engine(
    _async_db_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
)


# ---------------------------------------------------------------------------
# 异步会话工厂
# ---------------------------------------------------------------------------

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI 依赖注入用"""
    async with async_session() as session:
        yield session


async def init_db():
    """创建所有表（仅开发用，生产用 Alembic）"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        # 启用 pgvector 和 pg_trgm 扩展
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)

        # 创建 HNSW 向量索引（需要 pgvector 扩展和表已存在）
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
            WHERE embedding_status = 'completed' AND is_active = TRUE
        """))

        # 创建 pg_trgm GIN 索引（用于模糊文本检索）
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_rag_chunks_content_trgm
            ON rag_chunks USING gin (content gin_trgm_ops)
        """))

        # 创建 metadata GIN 索引
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_rag_chunks_metadata_gin
            ON rag_chunks USING gin (metadata)
        """))

    logger.info("✓ SQLAlchemy ORM 表结构已同步 (含 pgvector / pg_trgm / HNSW 索引)")
