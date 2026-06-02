"""
共享依赖项
提供跨 API 路由复用的依赖注入函数
"""

import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


# ============================================================================
# 用户身份解析
# ============================================================================

def get_current_user_id(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
) -> str:
    """
    统一的用户身份解析依赖
    
    所有需要用户身份的端点应使用此依赖，确保：
    1. 一致的 fallback 行为
    2. 未来可轻松接入真正的认证系统
    
    Args:
        x_user_id: 从请求头 X-User-ID 获取的用户 ID
        
    Returns:
        用户 ID 字符串
    """
    return x_user_id or "default_user"


def get_optional_user_id(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
) -> Optional[str]:
    """
    可选的用户身份解析（用于列表查询等场景）
    
    与 get_current_user_id 的区别：
    - 返回 None 时表示"不限制用户"
    - 适用于管理员查询等场景
    
    Args:
        x_user_id: 从请求头 X-User-ID 获取的用户 ID
        
    Returns:
        用户 ID 或 None
    """
    return x_user_id


# ============================================================================
# SSE 响应工厂
# ============================================================================

def create_sse_response(generator: AsyncGenerator[str, None]) -> StreamingResponse:
    """
    创建标准的 SSE 流式响应
    
    统一所有 SSE 端点的响应头配置
    
    Args:
        generator: 异步事件生成器
        
    Returns:
        StreamingResponse 实例
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "X-Accel-Buffering": "no",  # Nginx 禁用缓冲
        }
    )


def sse_event(data: dict) -> str:
    """
    格式化单个 SSE 事件
    
    Args:
        data: 事件数据字典
        
    Returns:
        SSE 格式字符串
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_event_model(model) -> str:
    """
    格式化 Pydantic 模型为 SSE 事件
    
    Args:
        model: Pydantic 模型实例
        
    Returns:
        SSE 格式字符串
    """
    return f"data: {model.model_dump_json()}\n\n"


# ============================================================================
# 错误响应标准化
# ============================================================================

def raise_http_error(status_code: int, error_type: str, message: str):
    """
    抛出标准化的 HTTP 错误
    
    Args:
        status_code: HTTP 状态码
        error_type: 错误类型标识
        message: 用户友好的错误消息
    """
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": error_type,
            "message": message
        }
    )


def raise_not_found(message: str = "资源不存在"):
    """抛出 404 错误"""
    raise_http_error(404, "NotFound", message)


def raise_bad_request(message: str):
    """抛出 400 错误"""
    raise_http_error(400, "BadRequest", message)


def raise_internal_error(message: str = "服务器内部错误"):
    """抛出 500 错误"""
    raise_http_error(500, "InternalServerError", message)
