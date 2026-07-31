"""
Embedding 服务
负责文本向量化，支持 OpenAI embedding 模型
"""

import asyncio
import hashlib
import logging
import os
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
    """Execute one embedding request within the external-I/O deadline."""
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
        embedding = response.data[0].embedding
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
    """在一个独立总 deadline 内分批生成 embedding。

    Args:
        texts: 文本列表。
        model: embedding 模型名称。
        dimensions: 输出维度。
        batch_size: 每批大小。
        api_config: 请求级 embedding 配置。

    Returns:
        与输入顺序一致的向量列表。

    Raises:
        RuntimeError: 任一批次失败或总 deadline 耗尽。
    """
    if not texts:
        return []

    selected_model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM
    deadline = TaskDeadline(get_settings().embedding_timeout_seconds)
    all_embeddings: List[List[float]] = []
    started_at = perf_counter()
    call_id = new_runtime_event_id("embedding_batch")

    try:
        for index in range(0, len(texts), batch_size):
            batch = texts[index:index + batch_size]
            response = await _embedding_call(
                batch,
                model=selected_model,
                dimensions=dims,
                api_config=api_config,
                deadline=deadline,
            )
            all_embeddings.extend(item.embedding for item in response.data)
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
