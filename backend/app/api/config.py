"""
API 配置相关端点
用于验证用户的 API 配置是否有效
"""

from fastapi import APIRouter

from app.schemas.schemas import ApiConfigValidateRequest
from app.workflows.config import api_config_use_cases

router = APIRouter(prefix="/api/config", tags=["配置"])


@router.post("/validate")
async def validate_api_config(request: ApiConfigValidateRequest):
    """验证用户的 API 配置是否有效。"""
    return await api_config_use_cases.validate(request)
