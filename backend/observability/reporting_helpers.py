"""面向报告/展示层的 Langfuse 辅助函数：Trace URL 与托管 Prompt 渲染。

Trace URL 只暴露已校验的公开链接，不向调用方透出 Langfuse 凭据；托管
Prompt 渲染失败时回退到本地模板，生产流量不依赖 Langfuse 可用性。
"""

import logging
from typing import Any
from urllib.parse import urlsplit

from observability.callbacks import _current_config, get_langfuse_client
from observability.events import record_model_event

logger = logging.getLogger(__name__)


def get_langfuse_trace_url(trace_id: str) -> str | None:
    """返回已配置项目中的 Trace URL，不向前端暴露 Langfuse 凭据。"""
    normalized_trace_id = trace_id.strip()
    if not normalized_trace_id:
        return None

    client = get_langfuse_client()
    if client is None:
        return None
    try:
        url = client.get_trace_url(trace_id=normalized_trace_id)
    except Exception as error:
        logger.warning("Langfuse Trace URL 获取失败: %s", type(error).__name__)
        return None

    if not isinstance(url, str) or len(url) > 2048:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        logger.warning("Langfuse 返回了无效的 Trace URL")
        return None
    return url


def render_managed_prompt(
    *,
    name: str,
    fallback: str,
    values: dict[str, Any],
    version: str | int | None = None,
    prompt_type: str = "text",
) -> str:
    """Render a Langfuse-managed prompt with a local fallback.

    Prompt management is opt-in via LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true.
    When disabled, unavailable, or failing, this returns the already-rendered local
    fallback so production traffic is not coupled to Langfuse availability.
    """
    import observability

    if not observability._configured:
        observability.configure_langfuse()
    config = _current_config()
    if observability._client is None or not config.prompt_management_enabled:
        return fallback

    prompt_kwargs: dict[str, Any] = {
        "type": prompt_type,
        "cache_ttl_seconds": config.prompt_cache_ttl_seconds,
        "fallback": fallback,
        # Prompt Management is optional; the render path must not accumulate
        # Langfuse retries before a model-call deadline even starts.
        "max_retries": config.prompt_max_retries,
        "fetch_timeout_seconds": config.prompt_fetch_timeout_seconds,
    }
    if config.prompt_label:
        prompt_kwargs["label"] = config.prompt_label
    else:
        try:
            if version is not None:
                prompt_kwargs["version"] = int(version)
        except (TypeError, ValueError):
            pass

    try:
        prompt_client = observability._client.get_prompt(name, **prompt_kwargs)
        rendered = prompt_client.compile(**values)
        if isinstance(rendered, list):
            rendered_text = "\n".join(
                str(item.get("content", item)) if isinstance(item, dict) else str(item)
                for item in rendered
            )
        else:
            rendered_text = str(rendered)
        record_model_event(
            event_type="prompt.rendered",
            prompt_name=name,
            prompt_version=str(version) if version is not None else None,
            prompt_label=config.prompt_label,
            prompt_source=(
                "langfuse"
                if not getattr(prompt_client, "is_fallback", False)
                else "fallback"
            ),
        )
        return rendered_text
    except Exception as error:
        logger.warning("Langfuse prompt 获取失败，使用本地 Prompt: %s", type(error).__name__)
        record_model_event(
            event_type="prompt.rendered",
            prompt_name=name,
            prompt_version=str(version) if version is not None else None,
            prompt_label=config.prompt_label,
            prompt_source="fallback",
        )
        return fallback
