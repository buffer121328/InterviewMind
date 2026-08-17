"""API 配置验证用例：连通性校验与 Embedding 维度校验。"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from app.config import get_settings
from app.security.security import safe_error_message
from ai.llm import llms
from ai.llm.llms import create_llm_from_config
from app.security.url_security import UnsafeOutboundUrl
from app.schemas.schemas import ApiConfigValidateRequest

logger = logging.getLogger(__name__)


def _audit_summary(request: ApiConfigValidateRequest) -> str:
    """构造脱敏审计摘要：只保留模型名与目标主机，不含凭据或查询串。"""

    host = urlparse(request.base_url).hostname or "unknown-host"
    return f"model={request.model} host={host} kind={request.kind}"


class ApiConfigUseCases:
    """API 配置验证用例：校验用户填写的模型/Embedding 配置真实可用。"""

    async def validate(self, request: ApiConfigValidateRequest) -> dict[str, object]:
        """验证模型/Embedding 配置可用性：实际调用远程服务并返回连接结果。

        Args:
            request: API 配置校验请求。
        """
        try:
            # 仅保留显式填写的可选字段，避免把 None 传给下游
            provider_config = {
                key: value
                for key, value in {
                    "provider": request.provider,
                    "integration": request.integration,
                }.items()
                if value is not None
            }
            if request.kind == "embedding":
                effective_dimensions = request.dimensions or int(os.getenv("EMBEDDING_DIM", "1536"))
                # ① 实际生成一条 Embedding，验证模型连通性
                response = await llms.model_gateway.create_embeddings(
                    "OK",
                    api_config={
                        "rag_embedding": {
                            "api_key": request.api_key,
                            "base_url": request.base_url,
                            "model": request.model,
                            **provider_config,
                            "dimensions": effective_dimensions,
                        }
                    },
                )
                data = list(getattr(response, "data", None) or [])
                embedding = getattr(data[0], "embedding", None) if len(data) == 1 else None
                if not isinstance(embedding, (list, tuple)):
                    raise ValueError("Embedding 响应缺少单条向量")
                # ② 校验返回维度与配置一致，防止下游向量索引错乱
                if len(embedding) != effective_dimensions:
                    raise ValueError(
                        "Embedding 维度不匹配: "
                        f"expected={effective_dimensions}, actual={len(embedding)}"
                    )
            else:
                # 创建 LLM 实例并发送一条极短测试消息，验证聊天模型连通性
                llm = create_llm_from_config(
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                    **provider_config,
                    temperature=0,
                    max_tokens=10,
                    timeout=get_settings().api_config_validation_timeout_seconds,
                )
                await llm.ainvoke("Say 'OK' in one word.")
            # 安全关卡：审计只记录模型名与脱敏主机，不输出 API Key / Base URL / 上游响应。
            audit = _audit_summary(request)
            logger.info("API 配置验证成功: %s", audit)
            result: dict[str, object] = {
                "success": True,
                "message": f"连接成功！模型 {request.model} 可用。",
            }
            if request.kind == "embedding":
                result["dimensions"] = effective_dimensions
            return result
        except UnsafeOutboundUrl as exc:
            logger.warning("API 配置验证拒绝出站地址: %s (%s)", exc, _audit_summary(request))
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            # 脱敏后再映射文案；日志与响应都不携带原始异常文本。
            safe_msg = safe_error_message(exc)
            logger.warning("API 配置验证失败: %s (%s)", safe_msg, _audit_summary(request))
            return {"success": False, "message": self._friendly_error_message(safe_msg)}

    @staticmethod
    def _friendly_error_message(error_msg: str) -> str:
        """把内部异常映射为不泄露密钥、Prompt 或完整输入的用户可读错误信息。"""
        if "401" in error_msg or "Unauthorized" in error_msg:
            return "API Key 无效，请检查是否正确"
        if "404" in error_msg or "Not Found" in error_msg:
            return "模型不存在或 API 地址错误"
        if "timeout" in error_msg.lower():
            return "连接超时，请检查网络或 API 地址"
        if "Connection" in error_msg:
            return "无法连接到 API 服务器，请检查 Base URL"
        return f"验证失败: {error_msg[:100]}"  # 兜底：截断内部错误，避免泄露密钥、Prompt 或完整输入


api_config_use_cases = ApiConfigUseCases()
