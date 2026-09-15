"""
统一的 LLM 调用工具
提供结构化输出、重试、统一调用等能力
"""

import asyncio
import json
import logging
import re
from hashlib import sha256
from time import perf_counter
from typing import Any, Mapping, Optional, Type, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from ai.llm import llms
from ai.runtime.execution.deadlines import (
    TaskDeadline,
    TaskDeadlineExceeded,
    get_current_task_deadline,
)
from ai.runtime.models.prompt_cache import (
    is_prompt_cache_control_rejection,
    prepare_stable_prompt_cache,
)
from ai.runtime.safety.errors import FailureType, classify_exception
from app.config import get_settings
from app.security.security import redact_secret_text, redact_secrets
from observability import (
    filter_model_call_metadata,
    measure_model_input,
    model_call_metadata_scope,
    record_model_event,
)

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

_REPAIRABLE_STRUCTURED_FAILURES = frozenset({
    FailureType.JSON_PARSE_ERROR,
    FailureType.SCHEMA_VALIDATION_ERROR,
})
_FAST_FAILOVER_FAILURES = frozenset({
    FailureType.NETWORK_ERROR,
    FailureType.TIMEOUT,
    FailureType.PROVIDER_REJECTION,
})
_STRUCTURED_REPAIR_TIMEOUT_SECONDS = 90.0
_STRUCTURED_REPAIR_MINIMUM_SECONDS = 2.0
_REPAIR_SECRET_FIELD_PATTERN = re.compile(
    r'(["\']?(?:api[_-]?key|apikey|authorization|token|secret|password)["\']?\s*:\s*["\']?)([^,}\s"\']+)',
    re.IGNORECASE,
)


def _resolve_deadline(deadline: TaskDeadline | None) -> TaskDeadline | None:
    """解析显式/上下文 deadline；未迁移流程默认保留原有 attempt 超时语义。

    Args:
        deadline: 任务时间预算。
    """
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
    """记录 wrapper 捕获的稳定失败类型，覆盖 wait_for 将超时表现为取消的问题。

    Args:
        input_value: 输入内容。
        current_llm: 传入的 current_llm 值。
        channel: 模型通道名称。
        candidate_count: candidate 的数量。
        candidate_index: 候选序号。
        error: 异常实例。
        duration_ms: 耗时（毫秒）。
        runtime_metadata: 运行时元数据。
        audit_metadata: 传入的 audit_metadata 值。
    """
    settings = get_settings()
    classified = classify_exception(error)
    identity = getattr(current_llm, "_model_pool_identity", "") or ""
    response_received = bool(_redacted_failed_model_output(error))
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
        "response_received": response_received,
        "validation_fields": _safe_validation_fields(error),
        "usage_status": "unavailable",
        "timeout_scope": "model" if classified.failure_type.value == "timeout" else None,
        "duration_ms": duration_ms,
        "model_duration_ms": duration_ms,
        "total_duration_ms": duration_ms,
    }
    record_model_event(**payload)


def _redacted_failed_model_output(error: BaseException) -> str:
    """提取失败输出并仅脱敏凭据，供同候选修复请求在内存中重放。"""
    raw_output = next(
        (
            value
            for attr in ("llm_output", "output", "raw_output")
            if isinstance((value := getattr(error, attr, None)), str) and value.strip()
        ),
        "",
    )
    if not raw_output:
        return ""
    try:
        parsed = json.loads(raw_output)
    except (TypeError, ValueError):
        redacted = redact_secret_text(raw_output)
        return _REPAIR_SECRET_FIELD_PATTERN.sub(r"\1***REDACTED***", redacted)
    return json.dumps(redact_secrets(parsed), ensure_ascii=False, separators=(",", ":"))


def _raw_structured_output_text(raw: object) -> str:
    """Extract one model response from raw structured output without persisting it."""

    content = getattr(raw, "content", raw)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple, dict)):
        try:
            return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(content)
    return str(content or "")


def _safe_validation_fields(error: BaseException | None) -> list[str]:
    """Return field paths only, never rejected values or provider error text."""

    seen: set[int] = set()
    pending: list[BaseException] = [error] if error is not None else []
    fields: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        existing = getattr(current, "_safe_validation_fields", None)
        if isinstance(existing, (list, tuple)):
            fields.extend(str(item) for item in existing)
        if isinstance(current, ValidationError):
            for item in current.errors():
                location = item.get("loc") or ()
                path = ".".join(
                    str(part) for part in location
                    if isinstance(part, str) and part and len(str(part)) <= 64
                )
                if path:
                    fields.append(path)
        for related in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(related, BaseException):
                pending.append(related)
    return list(dict.fromkeys(fields))[:16]


def _structured_output_error(
    message: str,
    *,
    raw: object,
    validation_error: ValidationError | None = None,
) -> OutputParserException:
    """Keep a returned invalid response in memory for exactly one repair request."""

    error = OutputParserException(message, llm_output=_raw_structured_output_text(raw) or None)
    if validation_error is not None:
        setattr(error, "_safe_validation_fields", _safe_validation_fields(validation_error))
        raise error from validation_error
    return error


def _unwrap_structured_result(result: object, output_model: Type[T]) -> T:
    """Return parsed structured output or preserve the raw failed response for one repair attempt."""

    if not isinstance(result, Mapping) or "parsed" not in result:
        return result  # type: ignore[return-value]
    parsed = result.get("parsed")
    if isinstance(parsed, output_model):
        return parsed
    if parsed is not None:
        try:
            return output_model.model_validate(parsed)
        except ValidationError as exc:
            raise _structured_output_error(
                "structured output validation failed",
                raw=result.get("raw"),
                validation_error=exc,
            )
    parsing_error = result.get("parsing_error")
    error = _structured_output_error(
        "structured output parsing failed",
        raw=result.get("raw"),
    )
    if isinstance(parsing_error, ValidationError):
        setattr(error, "_safe_validation_fields", _safe_validation_fields(parsing_error))
    raise error from parsing_error if isinstance(parsing_error, BaseException) else None


def _build_structured_repair_messages(
    *,
    input_value: object,
    output_model: Type[T],
    error: BaseException,
    classified_failure: FailureType,
) -> list[object] | None:
    """以原始输入、失败输出和修复指令重建同候选聊天上下文。"""
    failed_output = _redacted_failed_model_output(error)
    if not failed_output:
        return None
    if isinstance(input_value, (list, tuple)):
        messages = list(input_value)
    else:
        messages = [HumanMessage(content=str(input_value))]
    schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    messages.extend((
        AIMessage(content=failed_output),
        HumanMessage(
            content=(
                "The preceding assistant response failed structured validation. "
                "Repair it using the original context above. Return ONLY valid JSON matching the JSON Schema below. "
                "Do not add prose, markdown, explanations, or unsupported facts.\n\n"
                f"JSON Schema:\n{schema}\n\n"
                f"Validation failure category: {classified_failure.value}"
            )
        ),
    ))
    return messages


def _record_structured_repair_event(
    *,
    event_type: str,
    repair_input: object,
    current_llm: object,
    channel: str,
    candidate_count: int,
    candidate_index: int,
    duration_ms: int | None = None,
    error: BaseException | None = None,
    runtime_metadata: dict[str, Any],
    audit_metadata: dict[str, Any],
) -> None:
    """记录不携带修复提示或模型输出正文的结构化修复观测事件。"""
    settings = get_settings()
    payload: dict[str, Any] = {
        **runtime_metadata,
        **measure_model_input(repair_input, chars_per_token=settings.llm_estimated_chars_per_token),
        **audit_metadata,
        "event_type": event_type,
        "channel": channel,
        "model_name": getattr(current_llm, "model_name", None) or getattr(current_llm, "model", None),
        "candidate_count": candidate_count,
        "candidate_index": candidate_index + 1,
        "fallback_index": candidate_index,
        "repair_attempt": 1,
        "repair_outcome": event_type.rsplit(".", 1)[-1],
        "repair_timeout_seconds": _STRUCTURED_REPAIR_TIMEOUT_SECONDS,
        "response_received": True,
        "validation_fields": _safe_validation_fields(error),
        "usage_status": "unavailable" if error is not None else None,
    }
    if duration_ms is not None:
        payload.update({
            "duration_ms": duration_ms,
            "model_duration_ms": duration_ms,
            "total_duration_ms": duration_ms,
        })
    if error is not None:
        classified = classify_exception(error)
        payload.update({
            "error_type": type(error).__name__,
            "error_category": classified.category.value,
            "error_code": classified.code,
            "failure_type": classified.failure_type.value,
        })
    record_model_event(**payload)


async def _invoke_with_fallback(
    input_value: object,
    output_model: Type[T],
    api_config: Optional[dict],
    channel: str,
    max_retries: int,
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float | None = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> T:
    """主通道有限重试后 fallback；迁移流程的所有 attempt 共享总 deadline。

    Args:
        input_value: 输入内容。
        output_model: 传入的 output_model 值。
        api_config: 前端请求携带的模型通道配置。
        channel: 模型通道名称。
        max_retries: 最大重试次数。
        temperature: 采样温度。
        deadline: 任务时间预算。
        call_metadata: 调用元数据。
    """
    settings = get_settings()
    attempt_timeout = timeout or settings.llm_request_timeout_seconds
    task_deadline = _resolve_deadline(deadline)
    # ``max_retries`` remains source-compatible, but structured calls no longer
    # resend the original prompt to a candidate. A returned invalid response may
    # use the dedicated repair branch once instead.
    effective_max_retries = 0
    last_error: Optional[Exception] = None
    audit_metadata = filter_model_call_metadata(call_metadata)
    candidates = llms.model_gateway.get_chat_candidates(
        api_config,
        channel,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    for candidate_index, current_llm in enumerate(candidates):
        # DeepSeek 兼容端点支持 JSON 输出（`json_object`），
        # 但 LangChain 默认的 `json_schema` 模式并非所有
        # OpenAI 兼容提供方都可用；保留本地模式校验，
        # 同时通过更通用的 JSON 模式引导生成。
        structured_options = llms.structured_output_options(current_llm)
        structured_llm = current_llm.with_structured_output(output_model, include_raw=True, **structured_options)
        # A returned invalid structured response may receive one repair request below.
        # Never resend the original full context to the same candidate.
        attempts = 1
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
                        "max_retries": effective_max_retries,
                        "deadline_ms": task_deadline.deadline_ms,
                        "deadline_remaining_ms": task_deadline.remaining_ms,
                        "failure_type": "timeout",
                        "timeout_scope": "task",
                        "error_type": "TaskDeadlineExceeded",
                    })
                    last_error = TaskDeadlineExceeded("task deadline exhausted before next model attempt")
                    break
            runtime_metadata = {
                "attempt": attempt + 1,
                "max_retries": effective_max_retries,
                "deadline_ms": task_deadline.deadline_ms if task_deadline else None,
                "deadline_remaining_ms": task_deadline.remaining_ms if task_deadline else None,
                "queue_wait_ms": 0,
                "wrapper_managed": True,
                "structured_output_method": structured_options["method"],
                "structured_output_strict": structured_options.get("strict", False),
            }
            prepared_cache = prepare_stable_prompt_cache(
                input_value,
                llm=current_llm,
                metadata=audit_metadata,
            )
            metadata = {
                **runtime_metadata,
                **audit_metadata,
                **prepared_cache.event_fields,
            }
            started_at = perf_counter()
            try:
                with model_call_metadata_scope(**metadata):
                    result = _unwrap_structured_result(
                        await asyncio.wait_for(
                            structured_llm.ainvoke(prepared_cache.value),
                            timeout=effective_timeout,
                        ),
                        output_model,
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
                if prepared_cache.applied and is_prompt_cache_control_rejection(exc):
                    fallback_metadata = {
                        **runtime_metadata,
                        **audit_metadata,
                        **prepared_cache.event_fields,
                        "prompt_cache_status": "unsupported",
                    }
                    try:
                        with model_call_metadata_scope(**fallback_metadata):
                            result = _unwrap_structured_result(
                                await asyncio.wait_for(
                                    structured_llm.ainvoke(input_value),
                                    timeout=effective_timeout,
                                ),
                                output_model,
                            )
                        llms.model_gateway.record_chat_success(current_llm)
                        return result
                    except Exception as retry_exc:
                        exc = retry_exc
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
                repair_messages = (
                    _build_structured_repair_messages(
                        input_value=input_value,
                        output_model=output_model,
                        error=exc,
                        classified_failure=classified.failure_type,
                    )
                    if classified.failure_type in _REPAIRABLE_STRUCTURED_FAILURES
                    else None
                )
                if repair_messages is not None:
                    repair_timeout = _STRUCTURED_REPAIR_TIMEOUT_SECONDS
                    if task_deadline is not None:
                        repair_timeout = task_deadline.timeout_for_next_attempt(
                            _STRUCTURED_REPAIR_TIMEOUT_SECONDS,
                            minimum_required=_STRUCTURED_REPAIR_MINIMUM_SECONDS,
                        )
                    if repair_timeout > 0:
                        repair_metadata = {
                            **runtime_metadata,
                            "repair": True,
                            "repair_timeout_seconds": repair_timeout,
                        }
                        _record_structured_repair_event(
                            event_type="llm.request.repair.started",
                            repair_input=repair_messages,
                            current_llm=current_llm,
                            channel=channel,
                            candidate_count=len(candidates),
                            candidate_index=candidate_index,
                            runtime_metadata=repair_metadata,
                            audit_metadata=audit_metadata,
                        )
                        repair_started_at = perf_counter()
                        try:
                            with model_call_metadata_scope(**repair_metadata):
                                result = _unwrap_structured_result(
                                    await asyncio.wait_for(
                                        structured_llm.ainvoke(repair_messages),
                                        timeout=repair_timeout,
                                    ),
                                    output_model,
                                )
                            repair_duration_ms = max(0, int((perf_counter() - repair_started_at) * 1000))
                            _record_structured_repair_event(
                                event_type="llm.request.repair.completed",
                                repair_input=repair_messages,
                                current_llm=current_llm,
                                channel=channel,
                                candidate_count=len(candidates),
                                candidate_index=candidate_index,
                                duration_ms=repair_duration_ms,
                                runtime_metadata=repair_metadata,
                                audit_metadata=audit_metadata,
                            )
                            llms.model_gateway.record_chat_success(current_llm)
                            return result
                        except asyncio.CancelledError:
                            raise
                        except Exception as repair_error:
                            last_error = repair_error
                            repair_duration_ms = max(0, int((perf_counter() - repair_started_at) * 1000))
                            _record_structured_repair_event(
                                event_type="llm.request.repair.failed",
                                repair_input=repair_messages,
                                current_llm=current_llm,
                                channel=channel,
                                candidate_count=len(candidates),
                                candidate_index=candidate_index,
                                duration_ms=repair_duration_ms,
                                error=repair_error,
                                runtime_metadata=repair_metadata,
                                audit_metadata=audit_metadata,
                            )
                    break
                has_fallback_candidate = candidate_index + 1 < len(candidates)
                if (
                    has_fallback_candidate
                    and classified.failure_type in _FAST_FAILOVER_FAILURES
                ):
                    logger.warning(
                        "结构化输出通道失败，跳过同通道重试并切换备用通道: candidate=%s failure=%s",
                        candidate_index + 1,
                        classified.failure_type.value,
                    )
                    break
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

    Args:
        messages: 消息列表。
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
    max_retries: int = 0,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float | None = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
) -> T:
    """
    统一的 LLM 结构化调用，候选内仅一次原始请求并允许一次格式修复

    Args:
        prompt: 用户 prompt
        output_model: Pydantic 输出模型类
        api_config: API 配置
        channel: LLM 通道 (smart/fast/general 等)
        max_retries: 兼容参数；结构化调用不会重复原始请求。
        temperature: 温度参数
        max_tokens: 单次输出 Token 上限。

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
        max_tokens=max_tokens,
        timeout=timeout,
        deadline=deadline,
        call_metadata=call_metadata,
    )


async def invoke_structured_with_messages(
    messages: list,
    output_model: Type[T],
    api_config: Optional[dict] = None,
    channel: str = "smart",
    max_retries: int = 0,
    max_tokens: int | None = None,
    timeout: float | None = None,
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
        max_retries: 兼容参数；结构化调用不会重复原始请求。
        max_tokens: 单次输出 Token 上限。

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
        max_tokens=max_tokens,
        timeout=timeout,
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
