"""
mem0 配置构造模块

从请求级模型配置与部署基础设施配置构造 mem0 初始化所需的 config 字典。
"""

import os
import logging
from typing import Optional, Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    """读取环境变量，空字符串视为未设置。

    Args:
        key: 键名。
        default: 默认值。
    """
    return os.getenv(key) or default


def _request_channel(api_config: Optional[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    """从前端 api_config 读取完整模型通道。

    Args:
        api_config: 前端请求携带的模型通道配置。
        name: 名称。
    """
    if not isinstance(api_config, dict):
        return None
    channel = api_config.get(name)
    if not isinstance(channel, dict):
        return None
    if channel.get("api_key") and channel.get("base_url") and channel.get("model"):
        return channel
    return None


def _embedding_dimensions(channel: dict[str, Any]) -> int:
    """解析并校验请求级 Embedding 维度。

    Args:
        channel: 模型通道名称。
    """
    value: object = channel.get("dimensions")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16_000:
        raise ValueError("mem0 embedding dimensions must be an integer between 1 and 16000")
    return value


def _pgvector_connection_config() -> dict[str, Any]:
    """解析 pgvector 连接配置：优先 MEM0_PGVECTOR_URL，否则回退主库 DATABASE_URL。"""
    explicit_url = _env("MEM0_PGVECTOR_URL")
    database_url = _env("DATABASE_URL")
    fallback_url = "postgresql://{user}:{password}@{host}:{port}/{database}".format(
        user=_env("POSTGRES_USER", "agent_interview"),
        password=_env("POSTGRES_PASSWORD", ""),
        host=_env("POSTGRES_HOST", "localhost"),
        port=_env("POSTGRES_PORT", "5432"),
        database=_env("POSTGRES_DB", "agent_interview"),
    )

    def parse_dsn(value: str) -> dict[str, Any] | None:
        """解析 PostgreSQL DSN 为连接参数字典；无效时返回 None。

        Args:
            value: 形如 postgresql://user:pass@host:port/db 的 DSN 字符串。
        """
        parsed = urlparse(value.replace("postgresql+asyncpg://", "postgresql://", 1))
        database = parsed.path.lstrip("/")
        if parsed.scheme not in {"postgresql", "postgres"}:
            return None
        if not (parsed.hostname and parsed.username and database):
            return None
        return {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "dbname": unquote(database),
            "user": unquote(parsed.username),
            "password": unquote(parsed.password or ""),
        }

    if explicit_url:
        explicit = parse_dsn(explicit_url)
        if explicit is not None:
            return explicit
        logger.warning("MEM0_PGVECTOR_URL 无效，已回退到 DATABASE_URL")

    authoritative = parse_dsn(database_url or fallback_url)
    if authoritative is None:
        raise ValueError("DATABASE_URL is not a valid PostgreSQL DSN")
    return authoritative


def get_mem0_database_mode() -> str:
    """返回 mem0 数据库模式：显式分离的专用库返回 dedicated，否则 shared。"""
    explicit_url = _env("MEM0_PGVECTOR_URL")
    if not explicit_url:
        return "shared"
    parsed = urlparse(explicit_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if (
        parsed.scheme in {"postgresql", "postgres"}
        and parsed.hostname
        and parsed.username
        and parsed.path.lstrip("/")
    ):
        return "dedicated"
    return "shared"


def get_mem0_config(api_config: Optional[dict[str, Any]] = None) -> Optional[dict]:
    """
    构造 mem0 配置字典

    从请求级 LLM、Embedding 配置和部署级 pgvector 配置读取，
    返回 mem0 Memory.from_config() 所需的 config。

    Returns:
        dict: mem0 配置字典；未启用或请求模型通道不完整时返回 None。

    Args:
        api_config: 前端请求携带的模型通道配置。
    """
    request_llm = _request_channel(api_config, "mem0_llm")
    request_embedder = _request_channel(api_config, "mem0_embedder") or _request_channel(api_config, "rag_embedding")
    request_configured = bool(request_llm and request_embedder)
    if not request_configured:
        logger.info("mem0 等待请求级模型配置与 Redis 凭据水合")
        return None

    assert request_llm is not None
    assert request_embedder is not None
    embedding_dimensions = _embedding_dimensions(request_embedder)
    collection_name = _env("MEM0_PGVECTOR_COLLECTION", "mem0_memories")
    if request_embedder is not None:
        collection_name = f"{collection_name}_d{embedding_dimensions}"

    # mem0 是部署级功能开关；模型连接本身只接受请求级配置。
    enabled = _env("MEM0_ENABLED", "true").lower()
    if enabled not in ("true", "1", "yes"):
        logger.info("mem0 已禁用（MEM0_ENABLED=false）")
        return None

    # pgvector 默认与主数据库共用 DATABASE_URL；只有完整的 MEM0_PGVECTOR_URL 才能显式分离。
    pgvector_config = {
        "provider": "pgvector",
        "config": {
            "collection_name": collection_name,
            **_pgvector_connection_config(),
            "embedding_model_dims": embedding_dimensions,
            "hnsw": True,
        },
    }

    mem0_llm_api_key = request_llm["api_key"]
    mem0_llm_base_url = request_llm["base_url"]
    mem0_llm_model = request_llm["model"]
    mem0_embedder_api_key = request_embedder["api_key"]
    mem0_embedder_base_url = request_embedder["base_url"]
    mem0_embedder_model = request_embedder["model"]
    llm_provider = str(request_llm.get("provider") or "openai")
    embedder_provider = str(request_embedder.get("provider") or "openai")

    # LLM 配置（用于记忆提取和冲突判断）
    llm_config = {
        "provider": llm_provider,
        "config": {
            "model": mem0_llm_model,
            "api_key": mem0_llm_api_key,
            "openai_base_url": mem0_llm_base_url,
            "temperature": 0.1,
        },
    }

    # Embedding 配置（用于语义检索）
    embedder_config = {
        "provider": embedder_provider,
        "config": {
            "model": mem0_embedder_model,
            "api_key": mem0_embedder_api_key,
            "openai_base_url": mem0_embedder_base_url,
            "embedding_dims": embedding_dimensions,
        },
    }

    config = {
        "llm": llm_config,
        "embedder": embedder_config,
        "vector_store": pgvector_config,
        "version": "v1.1",
    }

    logger.info("mem0 配置构造完成")
    return config


def get_mem0_search_limit() -> int:
    """获取搜索结果限制"""
    return int(_env("MEM0_SEARCH_LIMIT", "5"))


def get_mem0_context_char_limit() -> int:
    """获取上下文字符数限制"""
    return int(_env("MEM0_CONTEXT_CHAR_LIMIT", "1200"))


def is_mem0_background_write() -> bool:
    """是否启用后台写入"""
    return _env("MEM0_BACKGROUND_WRITE", "true").lower() in ("true", "1", "yes")


def get_mem0_retention_days() -> int:
    """长期记忆默认有效期，默认 180 天。"""
    return max(1, int(_env("MEM0_RETENTION_DAYS", "180")))
