"""Provider-aware prompt-cache controls for the unified model gateway.

Business agents only mark a deterministic prefix as eligible.  This adapter
owns provider capability detection and request-shape changes so unsupported
models continue with the same semantic input and fallback behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptCacheCapability:
    """One model candidate's explicit prompt-cache support contract."""

    name: str
    supported: bool


@dataclass(frozen=True, slots=True)
class PreparedPromptCacheInput:
    """Gateway-owned prepared input and safe cache attribution fields."""

    value: Any
    applied: bool
    event_fields: dict[str, Any]


def detect_prompt_cache_capability(llm: object) -> PromptCacheCapability:
    """Detect native cache support without inferring it from a user endpoint.

    An explicit test/runtime attribute is supported for adapters. Anthropic
    receives its native ephemeral content-block control, while native DeepSeek
    keeps the request unchanged because its official prefix cache is automatic.
    Other OpenAI-compatible endpoints remain unsupported rather than receiving
    speculative provider fields.
    """
    explicit = str(getattr(llm, "_prompt_cache_capability", "") or "").strip()
    if explicit in {"anthropic_ephemeral", "deepseek_automatic"}:
        return PromptCacheCapability(name=explicit, supported=True)
    integration = str(getattr(llm, "_model_integration", "") or "").strip().lower()
    endpoint = str(getattr(llm, "_model_endpoint", "") or "").strip().lower()
    if integration == "deepseek" or "deepseek" in endpoint:
        return PromptCacheCapability(name="deepseek_automatic", supported=True)
    module_name = type(llm).__module__.lower()
    if "langchain_anthropic" in module_name:
        return PromptCacheCapability(name="anthropic_ephemeral", supported=True)
    return PromptCacheCapability(name="unsupported", supported=False)


def _cache_controlled_message(message: Any) -> Any | None:
    """Return a copy of a system message carrying Anthropic cache control."""
    content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
    role = str(message.get("role") if isinstance(message, Mapping) else getattr(message, "type", "") or "").lower()
    if role not in {"system", ""} or not isinstance(content, str):
        return None
    cached_content = [{
        "type": "text",
        "text": content,
        "cache_control": {"type": "ephemeral"},
    }]
    if isinstance(message, Mapping):
        return {**message, "content": cached_content}
    copier = getattr(message, "model_copy", None)
    if callable(copier):
        return copier(update={"content": cached_content})
    return None


def prepare_stable_prompt_cache(
    input_value: Any,
    *,
    llm: object,
    metadata: Mapping[str, Any] | None,
) -> PreparedPromptCacheInput:
    """Apply a cache control only to the declared stable message boundary."""
    audit = dict(metadata or {})
    eligible = bool(audit.get("prompt_cache_eligible"))
    base_fields = {
        "prompt_cache_eligible": eligible,
        "prompt_prefix_version": audit.get("prompt_prefix_version"),
        "prompt_prefix_fingerprint": audit.get("prompt_prefix_fingerprint"),
        "stable_input_chars": audit.get("stable_input_chars"),
        "dynamic_input_chars": audit.get("dynamic_input_chars"),
    }
    if not eligible:
        return PreparedPromptCacheInput(
            value=input_value,
            applied=False,
            event_fields={**base_fields, "prompt_cache_status": "unreported"},
        )

    capability = detect_prompt_cache_capability(llm)
    if not capability.supported:
        return PreparedPromptCacheInput(
            value=input_value,
            applied=False,
            event_fields={**base_fields, "prompt_cache_status": "unsupported"},
        )

    # DeepSeek's official disk cache is automatic and matches complete input
    # prefixes. Keep the original request unchanged instead of injecting
    # another provider's cache-control fields.
    if capability.name == "deepseek_automatic":
        return PreparedPromptCacheInput(
            value=input_value,
            applied=True,
            event_fields={**base_fields, "prompt_cache_status": "unreported"},
        )

    if not isinstance(input_value, Sequence) or isinstance(
        input_value, (str, bytes, bytearray)
    ):
        return PreparedPromptCacheInput(
            value=input_value,
            applied=False,
            event_fields={**base_fields, "prompt_cache_status": "unsupported"},
        )

    stable_index = int(audit.get("prompt_cache_stable_message_index") or 0)
    messages = list(input_value)
    if stable_index < 0 or stable_index >= len(messages):
        return PreparedPromptCacheInput(
            value=input_value,
            applied=False,
            event_fields={**base_fields, "prompt_cache_status": "unsupported"},
        )
    controlled = _cache_controlled_message(messages[stable_index])
    if controlled is None:
        return PreparedPromptCacheInput(
            value=input_value,
            applied=False,
            event_fields={**base_fields, "prompt_cache_status": "unsupported"},
        )
    messages[stable_index] = controlled
    return PreparedPromptCacheInput(
        value=messages,
        applied=True,
        event_fields={**base_fields, "prompt_cache_status": "unreported"},
    )


def is_prompt_cache_control_rejection(error: BaseException) -> bool:
    """Detect only explicit cache-control rejections eligible for safe retry."""
    message = str(error).lower()
    return any(marker in message for marker in (
        "cache_control", "cache control", "prompt cache", "prompt_cache",
    ))
