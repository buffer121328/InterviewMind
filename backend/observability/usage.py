"""提供后端逻辑相关后端功能。"""

from collections.abc import Mapping, Sequence
from hashlib import sha256
from math import ceil
from typing import Any


def _read_nested_usage_value(usage: Any, path: str) -> Any:
    """按点分路径读取各受支持 provider 的 usage 嵌套字段。"""
    current = usage
    for part in path.split("."):
        if current is None:
            return None
        current = current.get(part) if isinstance(current, Mapping) else getattr(current, part, None)
    return current


def _read_usage_value(usage: Any, *names: str) -> int | None:
    """从 dict 或 SDK 对象中按别名读取 token 计数；缺失时返回 None 而不是 0。"""
    for name in names:
        value = _read_nested_usage_value(usage, name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_token_usage(usage: Any) -> dict[str, int | None]:
    """把 OpenAI、LangChain 与 OpenAI-compatible provider 的 usage 规整为统一键。"""
    input_tokens = _read_usage_value(usage, "input_tokens", "prompt_tokens", "promptTokens")
    output_tokens = _read_usage_value(usage, "output_tokens", "completion_tokens", "completionTokens")
    total_tokens = _read_usage_value(usage, "total_tokens", "totalTokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": _read_usage_value(
            usage,
            "cache_read_tokens",
            "cached_tokens",
            "prompt_cache_hit_tokens",
            "cache_hit_tokens",
        ),
        "reasoning_tokens": _read_usage_value(
            usage,
            "reasoning_tokens",
            "completion_tokens_details.reasoning_tokens",
        ),
    }


def _merge_usage_result(usage: Any) -> dict[str, int | None]:
    """返回标准 token 结构，并在没有有效计数时保留统一的 unavailable 状态。"""
    result = _normalize_token_usage(usage)
    if any(value is not None for value in result.values()):
        return result
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cache_read_tokens": None,
        "reasoning_tokens": None,
    }


def extract_token_usage(value: Any) -> dict[str, int | None]:
    """从 LangChain/OpenAI 响应提取 token 数量，不读取或上报响应正文。"""
    usage = getattr(value, "usage_metadata", None)
    if isinstance(usage, Mapping):
        return _merge_usage_result(usage)
    response_metadata = getattr(value, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, Mapping):
            return _merge_usage_result(token_usage)
    raw_usage = getattr(value, "usage", None)
    if raw_usage is not None:
        return _merge_usage_result(raw_usage)
    llm_output = getattr(value, "llm_output", None)
    if isinstance(llm_output, Mapping):
        token_usage = llm_output.get("token_usage") or llm_output.get("usage")
        if isinstance(token_usage, Mapping):
            return _merge_usage_result(token_usage)
    generations = getattr(value, "generations", None)
    if generations:
        try:
            first = generations[0][0]
            message = getattr(first, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, Mapping):
                return _merge_usage_result(usage)
            metadata = getattr(message, "response_metadata", None)
            if isinstance(metadata, Mapping):
                token_usage = metadata.get("token_usage") or metadata.get("usage")
                if isinstance(token_usage, Mapping):
                    return _merge_usage_result(token_usage)
        except (IndexError, TypeError):
            pass
    return _merge_usage_result(None)


def _message_role(value: Any) -> str | None:
    """把消息对象映射到固定角色名，避免把任意用户字段名写入观测事件。"""
    role = getattr(value, "role", None) or getattr(value, "type", None)
    if not role and isinstance(value, Mapping):
        role = value.get("role") or value.get("type")
    normalized = str(role or "").lower()
    if normalized in {"system", "human", "user", "ai", "assistant", "tool", "function"}:
        return "human" if normalized == "user" else "ai" if normalized == "assistant" else normalized
    class_name = type(value).__name__.lower()
    for candidate in ("system", "human", "ai", "tool", "function"):
        if candidate in class_name:
            return candidate
    return None


def _content_char_count(value: Any) -> int:
    """递归统计模型可见字符串体积；只返回数量，不序列化或保留原文。"""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, Mapping):
        if "content" in value:
            return _content_char_count(value.get("content"))
        return sum(_content_char_count(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_content_char_count(item) for item in value)
    content = getattr(value, "content", None)
    if content is not None:
        return _content_char_count(content)
    return len(str(value)) if isinstance(value, (int, float, bool)) else 0


def _content_fingerprint(value: Any) -> str:
    """对模型可见内容做单向哈希；哈希过程不返回或保存原文。"""
    digest = sha256()

    def update(current: Any) -> None:
        """稳定遍历常见消息和结构化输入，加入类型与长度分隔符避免拼接碰撞。"""
        if current is None:
            digest.update(b"none;")
            return
        if isinstance(current, str):
            encoded = current.encode("utf-8")
            digest.update(f"str:{len(encoded)}:".encode("ascii"))
            digest.update(encoded)
            return
        if isinstance(current, bytes):
            digest.update(f"bytes:{len(current)}:".encode("ascii"))
            digest.update(current)
            return
        if isinstance(current, Mapping):
            digest.update(b"mapping{")
            for key in sorted(current, key=lambda item: str(item)):
                digest.update(sha256(str(key).encode("utf-8")).digest())
                update(current[key])
            digest.update(b"}")
            return
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            digest.update(b"sequence[")
            for item in current:
                update(item)
            digest.update(b"]")
            return
        content = getattr(current, "content", None)
        if content is not None:
            digest.update(f"message:{_message_role(current) or 'unknown'}:".encode("ascii"))
            update(content)
            return
        digest.update(f"scalar:{type(current).__name__}:{current!s}".encode("utf-8"))

    update(value)
    return digest.hexdigest()


def measure_model_input(value: Any, *, chars_per_token: float = 4.0) -> dict[str, Any]:
    """生成不含原文的模型输入体积、粗略 token 数、来源分布和指纹。"""
    input_chars = _content_char_count(value)
    source_breakdown: dict[str, int] = {}

    def iter_items(current: Any):
        """展平 LangChain 的批次消息外层，同时保留具体消息对象作为统计单元。"""
        if _message_role(current) is not None or isinstance(current, (str, bytes, Mapping)):
            yield current
            return
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for child in current:
                yield from iter_items(child)
            return
        yield current

    for item in iter_items(value):
        role = _message_role(item) or "input"
        source_breakdown[role] = source_breakdown.get(role, 0) + _content_char_count(item)
    if not source_breakdown:
        source_breakdown = {"input": input_chars}
    return {
        "input_chars": input_chars,
        "estimated_input_tokens": ceil(input_chars / max(chars_per_token, 0.1)),
        "source_breakdown": source_breakdown,
        "input_fingerprint": _content_fingerprint(value),
    }
