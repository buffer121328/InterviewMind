"""模型出站 HTTP 重定向防护测试。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import app.security.http_outbound as http_outbound
from app.security.http_outbound import build_guarded_async_client
from app.security.url_security import UnsafeOutboundUrl


def _settings(allow_private: bool) -> SimpleNamespace:
    return SimpleNamespace(allow_private_model_base_urls=allow_private)


def _redirect_response(
    status: int,
    location: str,
    url: str = "https://api.example.test/v1",
) -> httpx.Response:
    return httpx.Response(status, headers={"location": location}, request=httpx.Request("GET", url))


def test_redirect_to_private_target_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_outbound, "get_settings", lambda: _settings(False))
    client = build_guarded_async_client()
    hook = client._event_hooks["response"][0]
    with pytest.raises(UnsafeOutboundUrl):
        hook(_redirect_response(302, "http://127.0.0.1:8080/admin"))
    with pytest.raises(UnsafeOutboundUrl):
        hook(_redirect_response(301, "http://10.0.0.5/v1"))


def test_redirect_to_metadata_is_rejected_even_when_private_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_outbound, "get_settings", lambda: _settings(True))
    client = build_guarded_async_client()
    hook = client._event_hooks["response"][0]
    with pytest.raises(UnsafeOutboundUrl):
        hook(_redirect_response(307, "http://169.254.169.254/latest/meta-data"))


def test_private_redirect_passes_only_with_explicit_local_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_outbound, "get_settings", lambda: _settings(True))
    client = build_guarded_async_client()
    hook = client._event_hooks["response"][0]
    hook(_redirect_response(302, "http://localhost:11434/v1"))


def test_public_redirect_and_relative_location_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_outbound, "get_settings", lambda: _settings(False))
    client = build_guarded_async_client()
    hook = client._event_hooks["response"][0]
    hook(_redirect_response(301, "https://cdn.example.test/v2"))
    # 相对 Location 解析为当前公网 host 后放行。
    hook(_redirect_response(302, "/v2/chat/completions"))
    # 非 3xx 或无 Location 的响应不触发校验。
    hook(httpx.Response(200, request=httpx.Request("GET", "https://api.example.test/v1")))


@pytest.mark.asyncio
async def test_guarded_client_blocks_live_redirect_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：302 跳私网时，钩子在请求到达私网目标前拒绝。"""

    monkeypatch.setattr(http_outbound, "get_settings", lambda: _settings(False))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.test":
            return httpx.Response(302, headers={"location": "http://192.168.0.10/secret"})
        raise AssertionError("private target must not be reached")

    client = build_guarded_async_client()
    client._transport = httpx.MockTransport(handler)  # type: ignore[assignment]
    with pytest.raises(UnsafeOutboundUrl):
        await client.get("https://public.example.test/v1")
