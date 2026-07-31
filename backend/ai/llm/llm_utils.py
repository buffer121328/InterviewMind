"""
统一的 LLM 调用工具
提供结构化输出、重试、统一调用等能力
"""

import asyncio
import logging
from hashlib import sha256
from time import perf_counter
from typing import Any, Optional, Type, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from ai.llm import llms
from ai.runtime.deadlines import (
    TaskDeadline,
    TaskDeadlineExceeded,
    get_current_task_deadline,
)
from ai.runtime.error_classification import classify_exception
from app.config import get_settings
from observability import (
    filter_model_call_metadata,
    measure_model_input,
    model_call_metadata_scope,
    record_model_event,
)

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


def _resolve_deadline(deadline: TaskDeadline | None) -> TaskDeadline | None:
    """解析显式/上下文 deadline；未迁移流程默认保留原有 attempt 超时语义。"""
    if deadline is not None:
        return deadline
    current = get_current_task_deadline()
    if current is not None:
        return current
    settings = get_settings()
    if settings.task_deadline_enabled:
        return TaskDeadline(settings.llm_task_timeout_seconds)
    return None


def _record_attempt_failure(
    *,
    input_value: object,
    current_llm: object,
    channel: str,
    candidate_count: int,
    candidate_index: int,
    error: BaseException,
    duration_ms: int,
    runtime_metadata: dict[str, Any],
    audit_metadata: dict[str, Any],
) -> None:
    """记录 wrapper 捕获的稳定失败类型，覆盖 wait_for 将超时表现为取消的问题。"""
    settings = get_settings()
    classified = classify_exception(error)
    identity = getattr(current_llm, "_model_pool_identity", "") or ""
    payload = {
        **runtime_metadata,
        **measure_model_input(
            input_value,
            chars_per_token=settings.llm_estimated_chars_per_token,
        ),
        **audit_metadata,
        "event_type": "llm.request.failed",
        "channel": channel,
        "model_name": getattr(current_llm, "model_name", None) or getattr(current_llm, "model", None),
        "model_member": sha256(str(identity).encode("utf-8")).hexdigest()[:16] if identity else None,
        "candidate_count": candidate_count,
        "candidate_index": candidate_index + 1,
        "fallback_index": candidate_index,
        "error_type": type(error).__name__,
        "error_category": classified.category.value,
        "error_code": classified.code,
        "failure_type": classified.failure_type.value,
        "duration_ms": duration_ms,
        "model_duration_ms": duration_ms,
        "total_duration_ms": duration_ms,
    }
    record_model_event(**payload)


async def _invoke_with_fallback(
    input_value: object,
    output_model: Type[T],
    api_config: Optional[dict],
    channel: str,
    max_retries: int,
    *,
    temperature: float = 0.7,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> T:
    """主通道有限重试后 fallback；迁移流程的所有 attempt 共享总 deadline。"""
    settings = get_settings()
    attempt_timeout = settings.llm_request_timeout_seconds
    task_deadline = _resolve_deadline(deadline)
    last_error: Optional[Exception] = None
    audit_metadata = filter_model_call_metadata(call_metadata)
    candidates = llms.model_gateway.get_chat_candidates(
        api_config,
        channel,
        temperature=temperature,
    )
    for candidate_index, current_llm in enumerate(candidates):
        # DeepSeek-compatible endpoints support JSON Output (`json_object`),
        # while LangChain's default `json_schema` mode is not available on
        # every OpenAI-compatible provider.  Keep schema validation local in
        # LangChain but steer generation through the portable JSON mode.
        structured_llm = current_llm.with_structured_output(
            output_model,
            method="json_mode",
        )
        attempts = max_retries + 1 if candidate_index == 0 else 1
        for attempt in range(attempts):
            effective_timeout = float(attempt_timeout)
            if task_deadline is not None:
                effective_timeout = task_deadline.timeout_for_next_attempt(
                    attempt_timeout,
                    minimum_required=settings.llm_min_attempt_timeout_seconds,
                )
                if effective_timeout <= 0:
                    metrics = measure_model_input(
                        input_value,
                        chars_per_token=settings.llm_estimated_chars_per_token,
                    )
                    record_model_event(**{
                        **metrics,
                        **audit_metadata,
                        "event_type": "llm.request.skipped",
                        "channel": channel,
                        "candidate_count": len(candidates),
                        "candidate_index": candidate_index + 1,
                        "fallback_index": candidate_index,
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "deadline_ms": task_deadline.deadline_ms,
                        "deadline_remaining_ms": task_deadline.remaining_ms,
                        "failure_type": "timeout",
                        "error_type": "TaskDeadlineExceeded",
                    })
                    last_error = TaskDeadlineExceeded("task deadline exhausted before next model attempt")
                    break
            runtime_metadata = {
                "attempt": attempt + 1,
                "max_retries": max_retries,
                "deadline_ms": task_deadline.deadline_ms if task_deadline else None,
                "deadline_remaining_ms": task_deadline.remaining_ms if task_deadline else None,
                "queue_wait_ms": 0,
                "wrapper_managed": True,
            }
            metadata = {
                **runtime_metadata,
                **audit_metadata,
            }
            started_at = perf_counter()
            try:
                with model_call_metadata_scope(**metadata):
                    result = await asyncio.wait_for(
                        structured_llm.ainvoke(input_value),
                        timeout=effective_timeout,
                    )
                llms.model_gateway.record_chat_success(current_llm)
                logger.debug("结构化输出成功: candidate=%s attempt=%s", candidate_index + 1, attempt + 1)
                return result
            except asyncio.CancelledError as exc:
                duration_ms = max(0, int((perf_counter() - started_at) * 1000))
                _record_attempt_failure(
                    input_value=input_value,
                    current_llm=current_llm,
                    channel=channel,
                    candidate_count=len(candidates),
                    candidate_index=candidate_index,
                    error=exc,
                    duration_ms=duration_ms,
                    runtime_metadata=runtime_metadata,
                    audit_metadata=audit_metadata,
                )
                raise
            except Exception as exc:
                last_error = exc
                classified = classify_exception(exc)
                duration_ms = max(0, int((perf_counter() - started_at) * 1000))
                _record_attempt_failure(
                    input_value=input_value,
                    current_llm=current_llm,
                    channel=channel,
                    candidate_count=len(candidates),
                    candidate_index=candidate_index,
                    error=exc,
                    duration_ms=duration_ms,
                    runtime_metadata=runtime_metadata,
                    audit_metadata=audit_metadata,
                )
                if attempt + 1 < attempts and classified.retryable:
                    logger.warning("结构化输出重试: candidate=%s attempt=%s", candidate_index + 1, attempt + 1)
                    continue
                break
        llms.model_gateway.record_chat_failure(current_llm)
        if isinstance(last_error, TaskDeadlineExceeded):
            break
        if last_error is not None and not classify_exception(last_error).fallback_allowed:
            break
        if candidate_index == 0 and candidate_index + 1 < len(candidates):
            logger.warning("主模型通道失败，尝试备用通道")
    if last_error:
        raise last_error
    raise RuntimeError("结构化输出调用失败：没有可用模型通道")


def _ensure_json_keyword_in_messages(messages: list) -> None:
    """
    DashScope API 的 json_object 模式要求 messages 中必须包含 "json" 字样。
    如果所有消息中都没有，则在最后一条消息的 content 末尾追加。
    """
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str) and "json" in content.lower():
            return
    # 在最后一条消息末尾追加
    if messages:
        last = messages[-1]
        if hasattr(last, "content") and isinstance(last.content, str):
            last.content = f"{last.content}\n\nRespond in JSON format."


async def invoke_structured(
    prompt: str,
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart",
    max_retries: int = 2,
    temperature: float = 0.7,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> T:
    """
    统一的 LLM 结构化调用，自动重试

    Args:
        prompt: 用户 prompt
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道 (smart/fast/general 等)
        max_retries: 最大重试次数
        temperature: 温度参数

    Returns:
        output_model 的实例

    Raises:
        Exception: 所有重试都失败后抛出最后一个异常
    """
    # DashScope API 的 json_object 模式要求 messages 中包含 "json" 字样
    # 参见: https://help.aliyun.com/zh/model-studio/json-mode
    if isinstance(prompt, str) and "json" not in prompt.lower():
        prompt = f"{prompt}\n\nRespond in JSON format."

    return await _invoke_with_fallback(
        prompt,
        output_model,
        api_config,
        channel,
        max_retries,
        temperature=temperature,
        deadline=deadline,
        call_metadata=call_metadata,
    )


async def invoke_structured_with_messages(
    messages: list,
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart",
    max_retries: int = 2,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> T:
    """
    使用消息列表的结构化调用

    Args:
        messages: 消息列表 (HumanMessage, SystemMessage 等)
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道
        max_retries: 最大重试次数

    Returns:
        output_model 的实例
    """
    # DashScope json_object 模式要求 messages 中包含 "json" 字样
    _ensure_json_keyword_in_messages(messages)

    return await _invoke_with_fallback(
        messages,
        output_model,
        api_config,
        channel,
        max_retries,
        deadline=deadline,
        call_metadata=call_metadata,
    )


def get_structured_llm(
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart"
) -> ChatOpenAI:
    """
    获取已绑定结构化输出的 LLM 实例

    Args:
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道

    Returns:
        绑定了结构化输出的 ChatOpenAI 实例
    """
    current_llm = llms.model_gateway.get_chat_model(api_config, channel=channel)
    return current_llm.with_structured_output(output_model, method="json_mode")


def clean_json_response(content: str) -> str:
    """
    清理 LLM 响应中的 markdown 标记（保留作为 fallback）

    Args:
        content: LLM 原始响应

    Returns:
        清理后的 JSON 字符串
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def clean_markdown_response(content: str) -> str:
    """
    清理 Markdown 响应中的代码块包裹（保留作为 fallback）

    Args:
        content: LLM 原始响应

    Returns:
        清理后的 Markdown 字符串
    """
    content = content.strip()
    if content.startswith("```markdown"):
        content = content[11:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()
