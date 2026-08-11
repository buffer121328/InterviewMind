"""提供提供方相关后端功能。"""

import logging
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

_MODEL_PRICE_ENV = "MODEL_PRICE_REGISTRY"
logger = logging.getLogger(__name__)


def _normalize_model_provider(value: Any) -> str | None:
    """把前端供应商 ID 归一到观测维度，避免 aliyun 与 qwen 混用。"""
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"aliyun", "dashscope", "bailian", "qwen", "qwq"}:
        return "qwen"
    if raw in {"deepseek", "openai", "openai_compatible", "custom"}:
        return "openai_compatible" if raw == "custom" else raw
    return raw


def provider_observability_metadata(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """从模型通道配置生成不含凭据的 Provider 元数据，供 Langfuse 和本地事件统一使用。"""
    cfg = dict(config or {})
    base_url = str(cfg.get("base_url") or "")
    endpoint = None
    if base_url:
        parsed = urlsplit(base_url)
        endpoint = parsed.netloc or None
    provider = _normalize_model_provider(cfg.get("provider")) or infer_model_provider(cfg.get("model"), base_url)
    return {
        "model_provider": provider,
        "model_integration": cfg.get("integration") or infer_model_integration(cfg.get("model"), base_url, provider),
        "model_endpoint": endpoint,
        "pricing_key": cfg.get("pricing_key") or cfg.get("model"),
    }


def infer_model_provider(model: Any, base_url: str | None = None) -> str:
    """根据显式配置缺失时的模型名和端点推断 Provider，只返回可公开观测的归一化名称。"""
    text = f"{model or ''} {base_url or ''}".lower()
    if "deepseek" in text:
        return "deepseek"
    if any(marker in text for marker in ("dashscope", "aliyun", "bailian", "qwen", "qwq")):
        return "qwen"
    if "openai" in text:
        return "openai"
    return "openai_compatible"


def infer_model_integration(model: Any, base_url: str | None = None, provider: Any = None) -> str:
    """推断模型客户端集成类型；原生服务商优先，网关和自定义端点保持 generic 兜底。"""
    explicit = _normalize_model_provider(provider) or ""
    inferred = infer_model_provider(model, base_url)
    base = (base_url or "").lower()
    if explicit in {"deepseek", "qwen", "openai", "openai_compatible"}:
        inferred = explicit
    if inferred == "deepseek" and (not base or "deepseek" in base):
        return "deepseek"
    if inferred in {"qwen", "aliyun"} and (not base or any(marker in base for marker in ("dashscope", "aliyun"))):
        return "qwen"
    if inferred == "openai" and (not base or "openai" in base):
        return "openai"
    return "openai_compatible"


def _load_price_registry() -> dict[str, dict[str, Any]]:
    """从 JSON 环境变量读取本地模型价格表；解析失败时禁用成本估算但不阻断业务。"""
    raw = os.getenv(_MODEL_PRICE_ENV, "").strip()
    if not raw:
        return {}
    try:
        import json

        parsed = json.loads(raw)
    except Exception as error:
        logger.warning("模型价格表解析失败，跳过成本估算: %s", type(error).__name__)
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if isinstance(value, Mapping):
            registry[str(key).lower()] = dict(value)
    return registry


def estimate_model_cost(
    *,
    pricing_key: Any = None,
    model_name: Any = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> dict[str, Any]:
    """按本地价格表估算模型成本，默认支持人民币；缺 token 或价格时明确返回 unavailable。"""
    if input_tokens is None or output_tokens is None:
        return {"usage_status": "unavailable", "cost_status": "unavailable"}
    registry = _load_price_registry()
    key_candidates = [str(item).lower() for item in (pricing_key, model_name) if item]
    price = next((registry[key] for key in key_candidates if key in registry), None)
    if not price:
        return {"usage_status": "available", "cost_status": "unpriced"}
    currency = str(price.get("currency") or "CNY").upper()
    try:
        input_per_1m = float(price.get("input_per_1m", 0) or 0)
        output_per_1m = float(price.get("output_per_1m", 0) or 0)
    except (TypeError, ValueError):
        return {"usage_status": "available", "cost_status": "unpriced"}
    estimated = (input_tokens * input_per_1m + output_tokens * output_per_1m) / 1_000_000
    result: dict[str, Any] = {
        "usage_status": "available",
        "cost_status": "estimated",
        "cost_currency": currency,
        "cost_source": "local_pricelist",
    }
    if currency == "CNY":
        result["estimated_cost_cny"] = round(estimated, 8)
    elif currency == "USD":
        result["estimated_cost_usd"] = round(estimated, 8)
    return result
