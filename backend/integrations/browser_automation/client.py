"""主后端访问宿主机浏览器自动化服务的安全 HTTP 客户端。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import AppSettings, get_settings
from app.security.security import safe_error_message
from observability import record_external_io_event
from observability.runtime_events import ExternalIOObservationEvent


def _extract_host_error_message(response: httpx.Response) -> str:
    """从宿主机服务错误响应中提取脱敏可操作文案，忽略凭据和原始 payload。"""
    try:
        body = response.json()
    except ValueError:
        return ""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("error")
    else:
        message = detail
    return safe_error_message(message) if isinstance(message, str) else ""


def _host_request_may_have_run(response: httpx.Response) -> bool:
    """读取宿主机明确返回的歧义标记；缺失或非法时采用安全默认 false。"""

    try:
        body = response.json()
    except ValueError:
        return False
    detail = body.get("detail") if isinstance(body, dict) else None
    return bool(detail.get("request_may_have_run")) if isinstance(detail, dict) else False


class BrowserAutomationError(RuntimeError):
    """宿主机浏览器服务不可用、响应非法或执行状态不明确。"""

    def __init__(
        self,
        message: str,
        *,
        request_may_have_run: bool = False,
        status_code: int = 503,
    ) -> None:
        """保存脱敏错误、建议 HTTP 状态和外部操作是否可能已执行的保守判断。"""
        super().__init__(message)
        self.request_may_have_run = request_may_have_run
        self.status_code = status_code


class BrowserAutomationClient:
    """统一处理宿主机连接配置、Bearer Token、超时与错误脱敏。"""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """初始化客户端；构造阶段不连接宿主机，也不暴露服务令牌。"""
        self._settings = settings or get_settings()
        self._transport = transport

    def _connection(self) -> tuple[str, str]:
        """读取并校验宿主机服务地址和至少 32 字符的共享令牌。"""
        base_url = self._settings.browser_automation_service_url.strip().rstrip("/")
        token = self._settings.browser_automation_service_token.get_secret_value().strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserAutomationError("宿主机浏览器服务地址未配置或格式无效")
        if len(token) < 32:
            raise BrowserAutomationError("宿主机浏览器服务令牌未配置或长度不足 32 字符")
        return base_url, token

    @staticmethod
    def _record_io(
        *,
        event_type: str,
        operation: str,
        started_at: float,
        item_count: int | None = None,
        error: BaseException | None = None,
    ) -> None:
        """记录宿主机 IO 耗时和错误类型，不记录 URL、路径、payload 或认证信息。"""

        status = "completed" if error is None else "failed"
        error_category = None
        if error is not None:
            error_category = (
                "external_io_timeout"
                if isinstance(error, (TimeoutError, httpx.TimeoutException))
                else "external_io_error"
            )
        record_external_io_event(
            ExternalIOObservationEvent(
                event_type=event_type,
                operation=operation,
                status=status,
                call_id=f"io_{operation.replace('.', '_')}_{int(started_at * 1_000_000)}",
                dependency="browser_automation",
                duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
                item_count=item_count,
                error_type=type(error).__name__ if error is not None else None,
                error_category=error_category,
            )
        )

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送受控 JSON 请求并将网络、HTTP 和反序列化错误转换为脱敏异常。"""
        base_url, token = self._connection()
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.browser_automation_request_timeout_seconds,
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
                raise BrowserAutomationError("宿主机浏览器服务返回格式无效")
            self._record_io(
                event_type="external_io.completed",
                operation="browser_automation.post",
                started_at=started_at,
                item_count=1,
            )
            return result
        except BrowserAutomationError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.post",
                started_at=started_at,
                error=exc,
            )
            raise
        except httpx.HTTPStatusError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.post",
                started_at=started_at,
                error=exc,
            )
            status_code = exc.response.status_code
            detail = _extract_host_error_message(exc.response)
            message = detail or f"宿主机浏览器服务请求失败 (HTTP {status_code})"
            raise BrowserAutomationError(
                message,
                request_may_have_run=(
                    status_code >= 500 or _host_request_may_have_run(exc.response)
                ),
                status_code=status_code,
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.post",
                started_at=started_at,
                error=exc,
            )
            raise BrowserAutomationError(
                f"无法连接宿主机浏览器服务: {safe_error_message(exc)}"
            ) from exc
        except httpx.HTTPError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.post",
                started_at=started_at,
                error=exc,
            )
            raise BrowserAutomationError(
                f"宿主机浏览器服务通信中断: {safe_error_message(exc)}",
                request_may_have_run=True,
            ) from exc
        except ValueError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.post",
                started_at=started_at,
                error=exc,
            )
            raise BrowserAutomationError("宿主机浏览器服务返回格式无效") from exc

    async def stream(self, path: str, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """流式读取 NDJSON 事件；连接中断时关闭响应并返回脱敏异常。"""
        base_url, token = self._connection()
        started_at = perf_counter()
        item_count = 0
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.browser_automation_request_timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST",
                    path,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise BrowserAutomationError("宿主机浏览器服务流事件格式无效")
                        item_count += 1
                        yield value
            self._record_io(
                event_type="external_io.completed",
                operation="browser_automation.stream",
                started_at=started_at,
                item_count=item_count,
            )
        except BrowserAutomationError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.stream",
                started_at=started_at,
                item_count=item_count,
                error=exc,
            )
            raise
        except httpx.HTTPStatusError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.stream",
                started_at=started_at,
                item_count=item_count,
                error=exc,
            )
            raise BrowserAutomationError(
                f"宿主机浏览器服务请求失败 (HTTP {exc.response.status_code})",
                request_may_have_run=exc.response.status_code >= 500,
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.stream",
                started_at=started_at,
                item_count=item_count,
                error=exc,
            )
            raise BrowserAutomationError(f"无法连接宿主机浏览器服务: {safe_error_message(exc)}") from exc
        except httpx.HTTPError as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.stream",
                started_at=started_at,
                item_count=item_count,
                error=exc,
            )
            raise BrowserAutomationError(
                f"宿主机浏览器服务通信中断: {safe_error_message(exc)}",
                request_may_have_run=True,
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            self._record_io(
                event_type="external_io.failed",
                operation="browser_automation.stream",
                started_at=started_at,
                item_count=item_count,
                error=exc,
            )
            raise BrowserAutomationError("宿主机浏览器服务流事件格式无效") from exc

    async def health(self) -> dict[str, Any]:
        """读取宿主机现有浏览器标签页桥接服务的健康状态。"""
        return await self.post("/v1/health", {})
