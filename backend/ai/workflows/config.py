"""API configuration validation use cases."""

from __future__ import annotations

import logging

from app.config import get_settings
from ai.llm.llms import create_llm_from_config
from app.security.url_security import UnsafeOutboundUrl
from app.schemas.schemas import ApiConfigValidateRequest

logger = logging.getLogger(__name__)


class ApiConfigUseCases:
    """Validate user-provided model API configuration outside the HTTP layer."""

    async def validate(self, request: ApiConfigValidateRequest) -> dict[str, object]:
        """Validate API credentials by issuing a minimal model request."""
        try:
            llm = create_llm_from_config(
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0,
                max_tokens=10,
                timeout=get_settings().api_config_validation_timeout_seconds,
            )
            await llm.ainvoke("Say 'OK' in one word.")
            logger.info("API 配置验证成功: %s", request.model)
            return {
                "success": True,
                "message": f"连接成功！模型 {request.model} 可用。",
            }
        except UnsafeOutboundUrl as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            error_msg = str(exc)
            logger.warning("API 配置验证失败: %s", error_msg)
            return {"success": False, "message": self._friendly_error_message(error_msg)}

    @staticmethod
    def _friendly_error_message(error_msg: str) -> str:
        if "401" in error_msg or "Unauthorized" in error_msg:
            return "API Key 无效，请检查是否正确"
        if "404" in error_msg or "Not Found" in error_msg:
            return "模型不存在或 API 地址错误"
        if "timeout" in error_msg.lower():
            return "连接超时，请检查网络或 API 地址"
        if "Connection" in error_msg:
            return "无法连接到 API 服务器，请检查 Base URL"
        return f"验证失败: {error_msg[:100]}"


api_config_use_cases = ApiConfigUseCases()
