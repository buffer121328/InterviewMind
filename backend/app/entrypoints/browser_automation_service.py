"""宿主机现有 BOSS 标签页桥接 HTTP 服务。

运行示例：
    uv run uvicorn app.entrypoints.browser_automation_service:app --host 127.0.0.1 --port 8765

服务只在宿主机通过 Apple 事件访问用户已经打开的 Chrome/Edge 标签页，不启动浏览器、
创建 profile、读取 Cookie 或执行投递发送。主后端通过共享 Bearer Token 调用有限端点。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, NoReturn

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ROOT_ENV, override=False)

from app.schemas.job_schemas import BossTabCaptureRequest  # noqa: E402
from integrations.boss.existing_tab_bridge import (  # noqa: E402
    BossExistingTabError,
    get_boss_existing_tab_bridge,
)
from integrations.boss.security import is_allowed_boss_job_url  # noqa: E402
from integrations.browser_automation.host_auth import require_browser_service_token  # noqa: E402

app = FastAPI(title="Browser Tab Bridge Host Service", docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)


class EmptyRequest(BaseModel):
    """显式空请求体；健康检查拒绝误传字段。"""

    model_config = ConfigDict(extra="forbid")


class BossTabStatusRequest(BaseModel):
    """现有 BOSS 标签页状态检查请求；POST 空对象便于复用内部 Bearer 客户端。"""

    model_config = ConfigDict(extra="forbid")

    browser_channel: Literal["chrome", "msedge"] | None = None


class BossSendMessageHostRequest(BaseModel):
    """承载已审批文案和官方岗位 URL，不接收 Cookie 或任意页面脚本。"""

    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=8, max_length=2048)
    message_text: str = Field(min_length=20, max_length=500)
    browser_channel: Literal["chrome", "msedge"] | None = None


class BossOpenJobHostRequest(BaseModel):
    """承载一个已校验的 BOSS 岗位 URL，并限定为现有登录标签页导航。"""

    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=8, max_length=2048)
    browser_channel: Literal["chrome", "msedge"] | None = None


@app.get("/")
async def service_status() -> dict[str, str]:
    """返回不含凭据和浏览器 profile 信息的启动状态，供人工确认服务存活。"""

    return {
        "service": "browser_tab_bridge",
        "status": "running",
        "authenticated_health_endpoint": "/v1/health",
    }


@app.get("/favicon.ico", status_code=status.HTTP_204_NO_CONTENT)
async def favicon() -> Response:
    """对浏览器自动发起的 favicon 请求返回空响应，避免误报服务启动失败。"""

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/v1/health", dependencies=[Depends(require_browser_service_token)])
async def health(_: EmptyRequest) -> dict[str, object]:
    """返回标签页桥接能力和默认浏览器渠道，不探测 GUI 或暴露用户会话信息。"""

    channel = os.getenv("BOSS_BROWSER_CHANNEL", "msedge").strip().lower() or "msedge"
    if channel not in {"msedge", "chrome"}:
        channel = "msedge"
    return {
        "success": True,
        "service": "browser_tab_bridge",
        "default_browser_channel": channel,
        "browser_channels": {
            "msedge": "Microsoft Edge",
            "chrome": "Google Chrome",
        },
        "capabilities": ["status", "search_and_capture", "open_job", "send_message"],
    }


def _require_boss_job_url(source_url: str) -> None:
    """限制标签页导航端点只能访问 BOSS 官方岗位详情链接。"""

    if not is_allowed_boss_job_url(source_url):
        raise HTTPException(status_code=400, detail="仅允许 BOSS 直聘官方岗位详情链接")


def _raise_existing_tab_error(exc: BossExistingTabError) -> NoReturn:
    """把宿主机标签页桥接错误转换为稳定 HTTP detail，不暴露页面正文或凭据。"""

    raise HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.code,
            "message": exc.message,
            "request_may_have_run": exc.request_may_have_run,
        },
    ) from exc


@app.post("/v1/boss/browser-tab/status", dependencies=[Depends(require_browser_service_token)])
async def boss_browser_tab_status(request: BossTabStatusRequest) -> dict[str, object]:
    """检查宿主机已打开的 BOSS 标签页；主后端即使在 Docker 中也不会直接控制 GUI。"""

    try:
        status_result = await get_boss_existing_tab_bridge().inspect(request.browser_channel)
    except BossExistingTabError as exc:
        _raise_existing_tab_error(exc)
    return status_result.as_dict()


@app.post("/v1/boss/browser-tab/search-and-capture", dependencies=[Depends(require_browser_service_token)])
async def boss_browser_tab_search_and_capture(request: BossTabCaptureRequest) -> dict[str, object]:
    """复用宿主机现有登录标签页搜索并读取最多 20 张有限字段岗位卡片。"""

    try:
        return await get_boss_existing_tab_bridge().search_and_capture(
            query=request.query,
            city=request.city,
            max_cards=request.max_cards,
            browser_channel=request.browser_channel,
        )
    except BossExistingTabError as exc:
        _raise_existing_tab_error(exc)


@app.post("/v1/boss/browser-tab/send-message", dependencies=[Depends(require_browser_service_token)])
async def boss_browser_tab_send_message(
    request: BossSendMessageHostRequest,
) -> dict[str, object]:
    """在锁定的官方岗位标签页发送一次文案，并要求页面后置条件确认。"""

    _require_boss_job_url(request.source_url)
    try:
        return await get_boss_existing_tab_bridge().send_message(
            source_url=request.source_url,
            message_text=request.message_text,
            browser_channel=request.browser_channel,
        )
    except BossExistingTabError as exc:
        _raise_existing_tab_error(exc)


@app.post("/v1/boss/browser-tab/open-job", dependencies=[Depends(require_browser_service_token)])
async def boss_browser_tab_open_job(request: BossOpenJobHostRequest) -> dict[str, object]:
    """在现有用户浏览器标签页打开官方岗位链接，不填写或发送任何消息。"""

    _require_boss_job_url(request.source_url)
    try:
        return await get_boss_existing_tab_bridge().open_job(
            request.source_url,
            request.browser_channel,
        )
    except BossExistingTabError as exc:
        _raise_existing_tab_error(exc)
