"""主后端访问宿主机现有 BOSS 标签页桥接端点的客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import AppSettings
from integrations.browser_automation.client import BrowserAutomationClient, BrowserAutomationError


class BossAutomationError(BrowserAutomationError):
    """BOSS 标签页桥接失败；保留通用客户端的状态码和歧义标记。"""


class BossAutomationClient:
    """封装现有标签页桥接路由，连接、令牌和错误脱敏由共享客户端处理。"""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """初始化平台客户端；构造阶段不连接宿主机。"""

        self._client = BrowserAutomationClient(settings, transport=transport)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用宿主机桥接端点并转换为 BOSS 领域异常。"""

        try:
            return await self._client.post(path, payload)
        except BrowserAutomationError as exc:
            raise BossAutomationError(
                str(exc),
                request_may_have_run=exc.request_may_have_run,
                status_code=exc.status_code,
            ) from exc

    async def health(self) -> dict[str, Any]:
        """返回宿主机标签页桥接服务的健康状态。"""

        try:
            return await self._client.health()
        except BrowserAutomationError as exc:
            raise BossAutomationError(
                str(exc),
                request_may_have_run=exc.request_may_have_run,
                status_code=exc.status_code,
            ) from exc

    async def browser_tab_status(self, browser_channel: str | None = None) -> dict[str, Any]:
        """通过宿主机服务检查已打开的 BOSS 标签页，不在主后端直接控制 GUI。"""

        payload: dict[str, Any] = {}
        if browser_channel is not None:
            payload["browser_channel"] = browser_channel
        return await self._post("/v1/boss/browser-tab/status", payload)

    async def browser_tab_search_and_capture(
        self,
        *,
        query: str,
        city: str | None = None,
        max_cards: int = 20,
        browser_channel: str | None = None,
    ) -> dict[str, Any]:
        """让宿主机服务复用现有 BOSS 标签页搜索并返回有限岗位卡片。"""

        payload: dict[str, Any] = {"query": query, "max_cards": max_cards}
        if city is not None:
            payload["city"] = city
        if browser_channel is not None:
            payload["browser_channel"] = browser_channel
        return await self._post("/v1/boss/browser-tab/search-and-capture", payload)

    async def browser_tab_open_job(
        self,
        source_url: str,
        browser_channel: str | None = None,
    ) -> dict[str, Any]:
        """请求宿主机把现有登录标签页导航到已持久化的 BOSS 岗位。"""

        payload: dict[str, Any] = {"source_url": source_url}
        if browser_channel is not None:
            payload["browser_channel"] = browser_channel
        return await self._post("/v1/boss/browser-tab/open-job", payload)


def get_boss_automation_client() -> BossAutomationClient:
    """返回现有 BOSS 标签页桥接客户端。"""

    return BossAutomationClient()
