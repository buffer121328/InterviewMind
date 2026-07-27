"""Docker 主后端访问宿主机 BOSS 自动化服务的 HTTP 客户端。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import AppSettings, get_settings
from app.security.security import safe_error_message


class BossAutomationError(RuntimeError):
    """宿主机自动化服务不可用或返回非法响应。"""

    def __init__(self, message: str, *, request_may_have_run: bool = False) -> None:
        """初始化 `BossAutomationError` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            message: 消息内容。
            request_may_have_run: 经过类型边界校验的 `request_may_have_run`；其格式和可选值由参数类型及调用流程约束。
        """
        super().__init__(message)
        self.request_may_have_run = request_may_have_run


class BossAutomationClient:
    """封装外部客户端访问能力。"""
    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """初始化 `BossAutomationClient` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            settings: 配置项。
            transport: 经过类型边界校验的 `transport`；其格式和可选值由参数类型及调用流程约束。
        """
        self._settings = settings or get_settings()
        self._transport = transport

    def _connection(self) -> tuple[str, str]:
        """返回 BOSS 自动化服务的连接信息，并集中处理配置缺失和安全边界。"""
        base_url = self._settings.boss_automation_service_url.strip().rstrip("/")
        token = self._settings.boss_automation_service_token.get_secret_value().strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BossAutomationError("BOSS 宿主机服务地址未配置或格式无效")
        if len(token) < 32:
            raise BossAutomationError("BOSS 宿主机服务令牌未配置或长度不足 32 字符")
        return base_url, token

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """向本地 BOSS 自动化宿主发起受控请求，统一处理超时、错误和响应脱敏。

        Args:
            path: 文件路径。
            payload: 请求载荷。
        """
        base_url, token = self._connection()
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.boss_automation_request_timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    path,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise BossAutomationError("BOSS 宿主机服务返回格式无效")
            return result
        except BossAutomationError:
            raise
        except httpx.HTTPStatusError as exc:
            raise BossAutomationError(
                f"BOSS 宿主机服务请求失败 (HTTP {exc.response.status_code})",
                request_may_have_run=exc.response.status_code >= 500,
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise BossAutomationError(
                f"无法连接 BOSS 宿主机服务: {safe_error_message(exc)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise BossAutomationError(
                f"BOSS 宿主机服务通信中断: {safe_error_message(exc)}",
                request_may_have_run=True,
            ) from exc
        except ValueError as exc:
            raise BossAutomationError("BOSS 宿主机服务返回格式无效") from exc

    async def health(self) -> dict[str, Any]:
        """返回健康检查状态。"""
        return await self._post("/v1/health", {})

    async def scrape(
        self,
        source_url: str,
        *,
        headless: bool,
        manual_wait_seconds: int,
    ) -> dict[str, Any]:
        """执行受控的 BOSS 页面采集请求，返回脱敏结果并保持人工登录和投递确认边界。

        Args:
            source_url: source URL。
            headless: 是否隐藏浏览器界面；不改变人工登录和投递确认要求。
            manual_wait_seconds: 等待人工登录或页面稳定的最长时长，超时后必须安全退出。
        """
        return await self._post(
            "/v1/pages/scrape",
            {
                "source_url": source_url,
                "headless": headless,
                "manual_wait_seconds": manual_wait_seconds,
            },
        )

    async def preview(self, source_url: str, greeting_text: str) -> dict[str, Any]:
        """生成 BOSS 投递预览并返回一次性审批所需的摘要；不执行实际投递，也不泄露完整职位或候选人敏感内容。

        Args:
            source_url: source URL。
            greeting_text: greeting 文本内容。
        """
        return await self._post(
            "/v1/applications/preview",
            {"source_url": source_url, "greeting_text": greeting_text},
        )

    async def send(self, source_url: str, greeting_text: str) -> dict[str, Any]:
        """在审批许可、owner 和限流校验通过后发送 BOSS 投递请求；外部调用结果写入审计边界，失败不得伪装为成功。

        Args:
            source_url: source URL。
            greeting_text: greeting 文本内容。
        """
        return await self._post(
            "/v1/applications/send",
            {
                "source_url": source_url,
                "greeting_text": greeting_text,
                "confirmed": True,
            },
        )


def get_boss_automation_client() -> BossAutomationClient:
    """返回受配置控制的 BOSS 自动化客户端；客户端只允许白名单页面，并要求审批后才执行投递副作用。"""
    return BossAutomationClient()
