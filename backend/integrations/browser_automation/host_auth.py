"""宿主机浏览器服务的共享 Bearer Token 鉴权。"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def require_browser_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    """校验内部服务令牌；响应和日志均不得包含令牌内容。"""
    expected = os.getenv("BROWSER_AUTOMATION_SERVICE_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="宿主机浏览器服务令牌未配置或长度不足 32 字符",
        )
    supplied = credentials.credentials if credentials else ""
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="鉴权失败")
