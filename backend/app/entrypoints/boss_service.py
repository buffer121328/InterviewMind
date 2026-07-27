"""宿主机 BOSS Playwright HTTP 服务。

运行示例：
    uv run uvicorn app.entrypoints.boss_service:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ROOT_ENV, override=False)

from integrations.boss.browser_operations import (  # noqa: E402
    preview_boss_application,
    scrape_boss_page,
    send_boss_application,
)
from integrations.boss.security import is_allowed_apply_url  # noqa: E402
from integrations.boss.browser_runner import (  # noqa: E402
    async_playwright,
    resolve_boss_browser_profile_dir,
)

app = FastAPI(title="BOSS Host Automation Service", docs_url=None, redoc_url=None)
bearer = HTTPBearer(auto_error=False)


class EmptyRequest(BaseModel):
    """显式的空请求体模型；拒绝误传字段。"""

    model_config = ConfigDict(extra="forbid")


class ScrapeRequest(BaseModel):
    """API 请求数据对象，定义 `Scrape` 的字段校验和反序列化契约；只承载数据，不执行业务副作用。"""
    source_url: str = Field(min_length=1, max_length=2048)
    headless: bool = False
    manual_wait_seconds: int = Field(default=90, ge=1, le=300)


class ApplicationRequest(BaseModel):
    """API 请求数据对象，定义 `Application` 的字段校验和反序列化契约；只承载数据，不执行业务副作用。"""
    source_url: str = Field(min_length=1, max_length=2048)
    greeting_text: str = Field(min_length=1, max_length=2000)


class SendRequest(ApplicationRequest):
    """表示请求数据结构。"""
    confirmed: bool


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    """校验内部 BOSS 服务令牌；缺失或不匹配时立即拒绝请求，且日志和响应不得泄露令牌内容。

    Args:
        credentials: 经过类型边界校验的 `credentials`；其格式和可选值由参数类型及调用流程约束。
    """
    expected = os.getenv("BOSS_AUTOMATION_SERVICE_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="宿主机服务令牌未配置或长度不足 32 字符",
        )
    supplied = credentials.credentials if credentials else ""
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="鉴权失败")


def require_allowed_url(source_url: str) -> None:
    """校验 BOSS 页面 URL 是否属于服务白名单，阻止自动化入口访问任意外部或内部地址。

    Args:
        source_url: source URL。
    """
    if not is_allowed_apply_url(source_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅允许 BOSS 直聘官方 HTTPS 链接",
        )


@app.post("/v1/health", dependencies=[Depends(require_service_token)])
async def health(_: EmptyRequest) -> dict[str, object]:
    """返回健康检查状态。

    Args:
        _: 经过类型边界校验的 `_`；其格式和可选值由参数类型及调用流程约束。
    """
    return {
        "success": async_playwright is not None,
        "playwright_available": async_playwright is not None,
        "profile_configured": bool(resolve_boss_browser_profile_dir()),
    }


@app.post("/v1/pages/scrape", dependencies=[Depends(require_service_token)])
async def scrape(request: ScrapeRequest) -> dict[str, object]:
    """执行受控的 BOSS 页面采集请求，返回脱敏结果并保持人工登录和投递确认边界。

    Args:
        request: 请求对象。
    """
    require_allowed_url(request.source_url)
    return await scrape_boss_page(
        request.source_url,
        headless=request.headless,
        manual_wait_seconds=request.manual_wait_seconds,
    )


@app.post("/v1/applications/preview", dependencies=[Depends(require_service_token)])
async def preview(request: ApplicationRequest) -> dict[str, object]:
    """生成 BOSS 投递预览并返回一次性审批所需的摘要；不执行实际投递，也不泄露完整职位或候选人敏感内容。

    Args:
        request: 请求对象。
    """
    require_allowed_url(request.source_url)
    return await preview_boss_application(request.source_url, request.greeting_text)


@app.post("/v1/applications/send", dependencies=[Depends(require_service_token)])
async def send(request: SendRequest) -> dict[str, object]:
    """在审批许可、owner 和限流校验通过后发送 BOSS 投递请求；外部调用结果写入审计边界，失败不得伪装为成功。

    Args:
        request: 请求对象。
    """
    require_allowed_url(request.source_url)
    if not request.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="发送必须显式确认",
        )
    return await send_boss_application(request.source_url, request.greeting_text)
