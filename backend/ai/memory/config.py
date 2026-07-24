"""
mem0 配置构造模块

从环境变量读取配置，构造 mem0 初始化所需的 config 字典。
"""

import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    """读取环境变量，空字符串视为未设置。"""
    return os.getenv(key) or default


def _request_channel(api_config: Optional[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    """从前端 api_config 读取完整模型通道。"""
    if not isinstance(api_config, dict):
        return None
    channel = api_config.get(name)
    if not isinstance(channel, dict):
        return None
    if channel.get("api_key") and channel.get("base_url") and channel.get("model"):
        return channel
    return None


def get_mem0_config(api_config: Optional[dict[str, Any]] = None) -> Optional[dict]:
    """
    构造 mem0 配置字典

    从环境变量读取 LLM、embedding、pgvector 配置，
    返回 mem0 Memory.from_config() 所需的 config。

    Returns:
        dict: mem0 配置字典，如果 MEM0_ENABLED=false 则返回 None
    """
    request_llm = _request_channel(api_config, "mem0_llm")
    request_embedder = _request_channel(api_config, "mem0_embedder") or _request_channel(api_config, "rag_embedding")
    request_configured = bool(request_llm and request_embedder)

    # 检查是否启用：服务端 .env 可显式启用；前端请求携带完整 mem0 通道时也启用。
    enabled = _env("MEM0_ENABLED", "false").lower()
    if enabled not in ("true", "1", "yes") and not request_configured:
        logger.info("mem0 已禁用（MEM0_ENABLED=false 且请求未携带 mem0 前端配置）")
        return None

    # pgvector 配置 — 优先 MEM0_PGVECTOR_*，回退到 POSTGRES_*，再回退到硬编码默认值
    pgvector_config = {
        "provider": "pgvector",
        "config": {
            "collection_name": _env("MEM0_PGVECTOR_COLLECTION", "mem0_memories"),
            "host": _env("MEM0_PGVECTOR_HOST") or _env("POSTGRES_HOST", "localhost"),
            "port": int(_env("MEM0_PGVECTOR_PORT") or _env("POSTGRES_PORT", "5432")),
            "dbname": _env("MEM0_PGVECTOR_DBNAME") or _env("POSTGRES_DB", "agent_interview"),
            "user": _env("MEM0_PGVECTOR_USER") or _env("POSTGRES_USER", "agent_interview"),
            "password": _env("MEM0_PGVECTOR_PASSWORD") or _env("POSTGRES_PASSWORD", ""),
            "embedding_model_dims": int(_env("MEM0_EMBEDDING_DIMS", "1536")),
            "hnsw": True,
        },
    }

    mem0_llm_api_key = (request_llm or {}).get("api_key") or _env("MEM0_LLM_API_KEY") or _env("DEEPSEEK_API_KEY")
    mem0_llm_base_url = (request_llm or {}).get("base_url") or _env("MEM0_LLM_BASE_URL", "https://api.deepseek.com/v1")
    mem0_llm_model = (request_llm or {}).get("model") or _env("MEM0_LLM_MODEL", "deepseek-v4-flash")
    mem0_embedder_api_key = (request_embedder or {}).get("api_key") or _env("MEM0_EMBEDDER_API_KEY") or _env("OPENAI_API_KEY")
    mem0_embedder_base_url = (
        (request_embedder or {}).get("base_url")
        or _env("MEM0_EMBEDDER_BASE_URL")
        or _env("OPENAI_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    mem0_embedder_model = (request_embedder or {}).get("model") or _env("MEM0_EMBEDDER_MODEL", "text-embedding-v4")

    # LLM 配置（用于记忆提取和冲突判断）
    llm_config = {
        "provider": _env("MEM0_LLM_PROVIDER", "openai"),
        "config": {
            "model": mem0_llm_model,
            "api_key": mem0_llm_api_key,
            "openai_base_url": mem0_llm_base_url,
            "temperature": 0.1,
        },
    }

    # Embedding 配置（用于语义检索）
    embedder_config = {
        "provider": _env("MEM0_EMBEDDER_PROVIDER", "openai"),
        "config": {
            "model": mem0_embedder_model,
            "api_key": mem0_embedder_api_key,
            "openai_base_url": mem0_embedder_base_url,
            "embedding_dims": int(_env("MEM0_EMBEDDING_DIMS", "1536")),
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
