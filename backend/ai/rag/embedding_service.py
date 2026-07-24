"""
Embedding 服务
负责文本向量化，支持 OpenAI embedding 模型
"""

import hashlib
import logging
import os
from typing import List, Optional

from ai.llm import llms

logger = logging.getLogger(__name__)

# 配置（可通过环境变量覆盖）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

def compute_content_hash(content: str) -> str:
    """
    计算内容的 SHA-256 哈希值，用于避免重复 embedding
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def generate_embedding(
    text: str,
    model: Optional[str] = None,
    dimensions: Optional[int] = None,
    api_config: Optional[dict] = None,
) -> List[float]:
    """
    为单条文本生成 embedding 向量

    Args:
        text: 待向量化的文本
        model: embedding 模型名称（默认使用环境变量配置）
        dimensions: 输出维度（默认使用环境变量配置）

    Returns:
        浮点数列表，长度 = dimensions

    Raises:
        ValueError: text 为空
        RuntimeError: API 调用失败
    """
    if not text or not text.strip():
        raise ValueError("embedding 输入文本不能为空")

    model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM

    try:
        response = await llms.model_gateway.create_embeddings(
            text,
            model=model,
            dimensions=dims,
            api_config=api_config,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"embedding 生成失败: model={model}, error={e}")
        raise RuntimeError(f"embedding 生成失败: {e}") from e


async def generate_embeddings_batch(
    texts: List[str],
    model: Optional[str] = None,
    dimensions: Optional[int] = None,
    batch_size: int = 20,
    api_config: Optional[dict] = None,
) -> List[List[float]]:
    """
    批量生成 embedding（自动分批，避免超出 API 限制）

    Args:
        texts: 文本列表
        model: embedding 模型名称
        dimensions: 输出维度
        batch_size: 每批大小

    Returns:
        嵌入向量列表，与 texts 一一对应
    """
    if not texts:
        return []

    model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM

    all_embeddings: List[List[float]] = []

    try:
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await llms.model_gateway.create_embeddings(
                batch,
                model=model,
                dimensions=dims,
                api_config=api_config,
            )
            # response.data 按 input 顺序返回
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
    except Exception as e:
        logger.error(f"批量 embedding 生成失败: model={model}, error={e}")
        raise RuntimeError(f"批量 embedding 生成失败: {e}") from e


def get_embedding_config() -> dict:
    """返回当前 embedding 配置"""
    return {
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIM,
    }
