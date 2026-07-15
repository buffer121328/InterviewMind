"""宿主机 BOSS HTTP 服务与客户端测试；不启动真实浏览器。"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from app.config import AppSettings
from app.services.jobs.boss_automation_client import (
    BossAutomationClient,
    BossAutomationError,
)


TOKEN = "t" * 32


@pytest.mark.asyncio
async def test_host_service_requires_bearer_token(monkeypatch):
    from boss_service import app

    monkeypatch.setenv("BOSS_AUTOMATION_SERVICE_TOKEN", TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/v1/health", json={})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_host_service_rejects_non_boss_url(monkeypatch):
    from boss_service import app

    monkeypatch.setenv("BOSS_AUTOMATION_SERVICE_TOKEN", TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/pages/scrape",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"source_url": "https://example.com/job/1"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_host_service_send_requires_confirmation(monkeypatch):
    from boss_service import app

    monkeypatch.setenv("BOSS_AUTOMATION_SERVICE_TOKEN", TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/applications/send",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "source_url": "https://www.zhipin.com/job_detail/1.html",
                "greeting_text": "您好",
                "confirmed": False,
            },
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_host_service_preview_delegates_after_guards(monkeypatch):
    from boss_service import app

    monkeypatch.setenv("BOSS_AUTOMATION_SERVICE_TOKEN", TOKEN)
    operation = AsyncMock(return_value={"success": True, "send_ready": True})
    with patch("boss_service.preview_boss_application", new=operation):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/applications/preview",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "source_url": "https://www.zhipin.com/job_detail/1.html",
                    "greeting_text": "您好",
                },
            )

    assert response.status_code == 200
    operation.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_operation_never_clicks_send_button():
    from app.services.jobs.boss_browser_operations import preview_boss_application

    page = AsyncMock()
    send_button = AsyncMock()
    session = MagicMock(context=AsyncMock(), close=AsyncMock())
    with (
        patch(
            "app.services.jobs.boss_browser_operations.open_boss_browser_session",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.services.jobs.boss_browser_operations.open_job_page",
            new=AsyncMock(return_value=page),
        ),
        patch(
            "app.services.jobs.boss_browser_operations.inspect_page_state",
            new=AsyncMock(return_value={"status": "ready", "reason": ""}),
        ),
        patch(
            "app.services.jobs.boss_browser_operations.locate_and_fill_greeting",
            new=AsyncMock(return_value={"filled": True, "selector_used": "textarea"}),
        ),
        patch(
            "app.services.jobs.boss_browser_operations.locate_and_click_send",
            new=AsyncMock(return_value={"found": True, "element": send_button}),
        ),
        patch(
            "app.services.jobs.boss_browser_operations.take_screenshot",
            new=AsyncMock(return_value="image-base64"),
        ),
    ):
        result = await preview_boss_application(
            "https://www.zhipin.com/job_detail/1.html",
            "您好",
        )

    assert result["send_ready"] is True
    send_button.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_client_sends_bearer_token_without_exposing_it():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.url.path == "/v1/health"
        return httpx.Response(200, json={"success": True})

    settings = AppSettings(
        boss_automation_service_url="http://host.docker.internal:8765",
        boss_automation_service_token=SecretStr(TOKEN),
    )
    client = BossAutomationClient(settings, transport=httpx.MockTransport(handler))

    assert await client.health() == {"success": True}


@pytest.mark.asyncio
async def test_http_client_marks_read_timeout_as_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    settings = AppSettings(
        boss_automation_service_url="http://host.docker.internal:8765",
        boss_automation_service_token=SecretStr(TOKEN),
    )
    client = BossAutomationClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(BossAutomationError) as caught:
        await client.send("https://www.zhipin.com/job_detail/1.html", "您好")

    assert caught.value.request_may_have_run is True
