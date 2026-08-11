"""
Embedding 服务
负责文本向量化，支持 OpenAI embedding 模型
"""

import asyncio
import hashlib
import logging
import os
from collections import OrderedDict
from time import perf_counter
from typing import List, Optional

from ai.llm import llms
from ai.runtime.deadlines import TaskDeadline, TaskDeadlineExceeded
from app.config import get_settings
from observability import record_external_io_event
from observability.runtime_events import ExternalIOObservationEvent, new_runtime_event_id

logger = logging.getLogger(__name__)

# 配置（可通过环境变量覆盖）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
_EMBEDDING_CACHE_MAX_ITEMS = 512
_embedding_cache: "OrderedDict[str, List[float]]" = OrderedDict()


def _embedding_cache_key(text: str, *, model: str, dimensions: int, api_config: Optional[dict]) -> str:
    """处理嵌入缓存键相关后端逻辑。"""
    channel = (api_config or {}).get("rag_embedding") or {}
    provider = str(channel.get("base_url") or "environment")
    normalized = " ".join(text.split())
    payload = f"{provider}\0{model}\0{dimensions}\0{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clear_embedding_cache() -> None:
    """清理嵌入缓存相关后端逻辑。"""
    _embedding_cache.clear()


def _cache_get(key: str) -> List[float] | None:
    """处理缓存相关后端逻辑。"""
    value = _embedding_cache.get(key)
    if value is None:
        return None
    _embedding_cache.move_to_end(key)
    return list(value)


def _cache_put(key: str, value: List[float]) -> None:
    """处理缓存写入相关后端逻辑。"""
    _embedding_cache[key] = list(value)
    _embedding_cache.move_to_end(key)
    while len(_embedding_cache) > _EMBEDDING_CACHE_MAX_ITEMS:
        _embedding_cache.popitem(last=False)


def _validate_embedding_response(
    response: object,
    *,
    expected_count: int,
    expected_dimensions: int,
) -> List[List[float]]:
    """校验第三方 embedding 返回数量和维度，避免错误向量进入 pgvector 写入路径。"""

    data = list(getattr(response, "data", None) or [])
    if len(data) != expected_count:
        raise ValueError(
            f"embedding 响应数量不匹配: expected={expected_count}, actual={len(data)}"
        )

    embeddings: List[List[float]] = []
    for item in data:
        raw_embedding = getattr(item, "embedding", None)
        if not isinstance(raw_embedding, (list, tuple)):
            raise ValueError("embedding 响应缺少向量数组")
        embedding = [float(value) for value in raw_embedding]
        if len(embedding) != expected_dimensions:
            raise ValueError(
                "embedding 维度不匹配: "
                f"expected={expected_dimensions}, actual={len(embedding)}"
            )
        embeddings.append(embedding)
    return embeddings


def compute_content_hash(content: str) -> str:
    """计算内容的 SHA-256 哈希值，用于避免重复 embedding。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def _embedding_call(
    input_value: str | list[str],
    *,
    model: str,
    dimensions: int,
    api_config: Optional[dict],
    deadline: TaskDeadline,
):
    """处理嵌入相关后端逻辑。"""
    timeout = deadline.timeout_for_next_attempt(deadline.total_timeout)
    if timeout <= 0:
        raise TaskDeadlineExceeded("embedding deadline exhausted")
    return await asyncio.wait_for(
        llms.model_gateway.create_embeddings(
            input_value,
            model=model,
            dimensions=dimensions,
            api_config=api_config,
        ),
        timeout=timeout,
    )


def _record_embedding_failure(
    *,
    operation: str,
    call_id: str,
    started_at: float,
    item_count: int,
    exc: BaseException,
) -> None:
    """记录 embedding 依赖失败的耗时、计数和稳定错误类别。"""

    timed_out = isinstance(exc, (TimeoutError, TaskDeadlineExceeded))
    record_external_io_event(
        ExternalIOObservationEvent(
            event_type="external_io.failed",
            operation=operation,
            status="failed",
            call_id=call_id,
            dependency="embedding",
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            item_count=item_count,
            error_type=type(exc).__name__,
            error_category="external_io_timeout" if timed_out else "external_io_error",
        )
    )


async def generate_embedding(
    text: str,
    model: Optional[str] = None,
    dimensions: Optional[int] = None,
    api_config: Optional[dict] = None,
) -> List[float]:
    """为单条文本生成 embedding；外部 I/O 超时快速失败，由检索层降级为空结果。

    Args:
        text: 待向量化的文本。
        model: embedding 模型名称。
        dimensions: 输出维度。
        api_config: 请求级 embedding 配置。

    Returns:
        浮点数列表，长度由 embedding 服务决定。

    Raises:
        ValueError: 输入为空。
        RuntimeError: embedding 外部服务失败或超时。
    """
    if not text or not text.strip():
        raise ValueError("embedding 输入文本不能为空")

    selected_model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM
    started_at = perf_counter()
    call_id = new_runtime_event_id("embedding")
    try:
        response = await _embedding_call(
            text,
            model=selected_model,
            dimensions=dims,
            api_config=api_config,
            deadline=TaskDeadline(get_settings().embedding_timeout_seconds),
        )
        embedding = _validate_embedding_response(
            response,
            expected_count=1,
            expected_dimensions=dims,
        )[0]
        record_external_io_event(
            ExternalIOObservationEvent(
                event_type="external_io.completed",
                operation="embedding.generate",
                status="completed",
                call_id=call_id,
                dependency="embedding",
                duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
                item_count=1,
                result_count=1,
            )
        )
        return embedding
    except Exception as exc:
        _record_embedding_failure(
            operation="embedding.generate",
            call_id=call_id,
            started_at=started_at,
            item_count=1,
            exc=exc,
        )
        logger.warning("embedding 生成失败: model=%s, error=%s", selected_model, type(exc).__name__)
        raise RuntimeError(f"embedding 生成失败: {type(exc).__name__}") from exc


async def generate_embeddings_batch(
    texts: List[str],
    model: Optional[str] = None,
    dimensions: Optional[int] = None,
    batch_size: int = 20,
    api_config: Optional[dict] = None,
) -> List[List[float]]:
    """生成嵌入批量相关后端逻辑。"""
    if not texts:
        return []
    if any(not text or not text.strip() for text in texts):
        raise ValueError("embedding 输入文本不能为空")

    selected_model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM
    deadline = TaskDeadline(get_settings().embedding_timeout_seconds)
    started_at = perf_counter()
    call_id = new_runtime_event_id("embedding_batch")
    keys = [
        _embedding_cache_key(text, model=selected_model, dimensions=dims, api_config=api_config)
        for text in texts
    ]
    resolved: dict[str, List[float]] = {}
    misses: list[tuple[str, str]] = []
    seen_misses: set[str] = set()
    for key, text in zip(keys, texts):
        cached = _cache_get(key)
        if cached is not None:
            resolved[key] = cached
        elif key not in seen_misses:
            seen_misses.add(key)
            misses.append((key, text))

    try:
        for index in range(0, len(misses), max(1, batch_size)):
            batch_pairs = misses[index:index + max(1, batch_size)]
            batch = [text for _key, text in batch_pairs]
            response = await _embedding_call(
                batch,
                model=selected_model,
                dimensions=dims,
                api_config=api_config,
                deadline=deadline,
            )
            vectors = _validate_embedding_response(
                response,
                expected_count=len(batch),
                expected_dimensions=dims,
            )
            for (key, _text), vector in zip(batch_pairs, vectors):
                resolved[key] = vector
                _cache_put(key, vector)
        all_embeddings = [list(resolved[key]) for key in keys]
        record_external_io_event(
            ExternalIOObservationEvent(
                event_type="external_io.completed",
                operation="embedding.generate_batch",
                status="completed",
                call_id=call_id,
                dependency="embedding",
                duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
                item_count=len(texts),
                result_count=len(all_embeddings),
                cache_hit=not misses,
                strategy=f"batch_cache:misses={len(misses)}",
            )
        )
        return all_embeddings
    except Exception as exc:
        _record_embedding_failure(
            operation="embedding.generate_batch",
            call_id=call_id,
            started_at=started_at,
            item_count=len(texts),
            exc=exc,
        )
        logger.warning("批量 embedding 生成失败: model=%s, error=%s", selected_model, type(exc).__name__)
        raise RuntimeError(f"批量 embedding 生成失败: {type(exc).__name__}") from exc


def get_embedding_config() -> dict:
    """返回当前 embedding 配置。"""
    return {
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIM,
    }
