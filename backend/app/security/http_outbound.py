"""出站 HTTP 重定向防护：为模型调用构建每跳复验 URL 的 httpx client。

openai SDK 默认 ``follow_redirects=True``，公网端点可通过 3xx 重定向绕过
初始 Base URL 校验访问私网。此模块在每个 3xx 响应上对 ``Location``
重新执行 ``validate_outbound_url``（含 metadata/链路本地始终拒绝），
开关语义与初始 Base URL 校验一致。
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.security.url_security import validate_outbound_url

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _reject_unsafe_redirect(response: httpx.Response) -> None:
    """响应钩子：重定向响应的目标地址必须再次通过出站校验。"""

    if response.status_code not in REDIRECT_STATUSES:
        return
    location = response.headers.get("location")
    if not location:
        return
    # 相对 Location 以当前响应 URL 解析为绝对地址后再校验。
    absolute = str(httpx.URL(response.url).join(location))
    validate_outbound_url(
        absolute,
        allow_private=get_settings().allow_private_model_base_urls,
    )


def build_guarded_async_client(
    *,
    timeout: float | None = None,
    verify: bool = True,
) -> httpx.AsyncClient:
    """构建跟随重定向但每跳复验出站策略的异步 client。"""

    return httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=True,
        event_hooks={"response": [_reject_unsafe_redirect]},
    )
