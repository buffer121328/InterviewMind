"""宿主机 BOSS 标签页桥接 HTTP 服务与客户端测试；不启动真实浏览器。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from app.config import AppSettings
from integrations.boss.automation_client import BossAutomationClient, BossAutomationError
from integrations.boss.existing_tab_bridge import BossExistingTabError, BossTabStatus

TOKEN = "t" * 32


@pytest.mark.asyncio
async def test_host_service_root_reports_running_without_credentials():
    """直接打开宿主机服务地址时应明确显示已运行，而不是返回 404。"""

    from app.entrypoints.browser_automation_service import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        root_response = await client.get("/")
        favicon_response = await client.get("/favicon.ico")

    assert root_response.status_code == 200
    assert root_response.json() == {
        "service": "browser_tab_bridge",
        "status": "running",
        "authenticated_health_endpoint": "/v1/health",
    }
    assert favicon_response.status_code == 204


@pytest.mark.asyncio
async def test_host_service_requires_bearer_token(monkeypatch):
    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/v1/health", json={})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_host_health_reports_selected_boss_browser_channel(monkeypatch):
    """健康检查只报告标签页桥接能力，不再暴露旧浏览器会话信息。"""

    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("BOSS_BROWSER_CHANNEL", "chrome")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "browser_tab_bridge"
    assert body["default_browser_channel"] == "chrome"
    assert body["capabilities"] == [
        "status",
        "search_and_capture",
        "open_job",
        "send_message",
    ]


@pytest.mark.asyncio
async def test_host_service_delegates_existing_tab_status_to_bridge(monkeypatch):
    """宿主进程负责 Apple 事件访问，并只返回有限标签页状态。"""

    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    status_result = BossTabStatus(
        success=True,
        browser_channel="msedge",
        browser_label="Microsoft Edge",
        connected=True,
        current_url="https://www.zhipin.com/web/geek/jobs?query=agent",
        page_status="search_ready",
        ready_state="complete",
        visible_card_count=3,
        message="connected",
    )
    bridge = MagicMock()
    bridge.inspect = AsyncMock(return_value=status_result)
    with patch(
        "app.entrypoints.browser_automation_service.get_boss_existing_tab_bridge",
        return_value=bridge,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/boss/browser-tab/status",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"browser_channel": "msedge"},
            )

    assert response.status_code == 200
    assert response.json()["visible_card_count"] == 3
    bridge.inspect.assert_awaited_once_with("msedge")


@pytest.mark.asyncio
async def test_host_service_preserves_actionable_existing_tab_errors(monkeypatch):
    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    bridge = MagicMock()
    bridge.inspect = AsyncMock(
        side_effect=BossExistingTabError(
            "browser_javascript_disabled",
            "请在浏览器中开启 Apple 事件 JavaScript",
            status_code=409,
        )
    )
    with patch(
        "app.entrypoints.browser_automation_service.get_boss_existing_tab_bridge",
        return_value=bridge,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/boss/browser-tab/status",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={},
            )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "error": "browser_javascript_disabled",
        "message": "请在浏览器中开启 Apple 事件 JavaScript",
        "request_may_have_run": False,
    }


@pytest.mark.asyncio
async def test_host_service_delegates_search_and_capture(monkeypatch):
    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    bridge = MagicMock()
    bridge.search_and_capture = AsyncMock(
        return_value={"success": True, "cards": [{"job_title": "Agent 工程师"}]}
    )
    with patch(
        "app.entrypoints.browser_automation_service.get_boss_existing_tab_bridge",
        return_value=bridge,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/boss/browser-tab/search-and-capture",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"query": "Agent", "city": "101280600", "max_cards": 20},
            )

    assert response.status_code == 200
    assert response.json()["success"] is True
    bridge.search_and_capture.assert_awaited_once_with(
        query="Agent",
        city="101280600",
        max_cards=20,
        browser_channel=None,
    )


@pytest.mark.asyncio
async def test_host_service_delegates_send_message_without_echoing_body(monkeypatch):
    """宿主端只委托一次受控发送，并且响应中不回显沟通正文。"""

    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    message = "您好，我希望基于自己的真实项目经验进一步沟通这个岗位和团队需求。"
    bridge = MagicMock()
    bridge.send_message = AsyncMock(
        return_value={
            "success": True,
            "status": "sent",
            "browser_channel": "chrome",
        }
    )
    with patch(
        "app.entrypoints.browser_automation_service.get_boss_existing_tab_bridge",
        return_value=bridge,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/boss/browser-tab/send-message",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "source_url": "https://www.zhipin.com/job_detail/card_1-real.html",
                    "message_text": message,
                    "browser_channel": "chrome",
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "status": "sent",
        "browser_channel": "chrome",
    }
    assert message not in response.text
    bridge.send_message.assert_awaited_once_with(
        source_url="https://www.zhipin.com/job_detail/card_1-real.html",
        message_text=message,
        browser_channel="chrome",
    )


@pytest.mark.asyncio
async def test_host_service_opens_job_in_existing_tab_after_token_and_url_guards(monkeypatch):
    """open-job 只把官方岗位链接交给现有标签页桥接。"""

    from app.entrypoints.browser_automation_service import app

    monkeypatch.setenv("BROWSER_AUTOMATION_SERVICE_TOKEN", TOKEN)
    bridge = MagicMock()
    bridge.open_job = AsyncMock(
        return_value={
            "success": True,
            "browser_channel": "msedge",
            "browser_label": "Microsoft Edge",
            "opened_url": "https://www.zhipin.com/job_detail/card_1-real.html",
            "message": "opened",
        }
    )
    with patch(
        "app.entrypoints.browser_automation_service.get_boss_existing_tab_bridge",
        return_value=bridge,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/boss/browser-tab/open-job",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "source_url": "https://www.zhipin.com/job_detail/card_1-real.html",
                    "browser_channel": "msedge",
                },
            )
            external = await client.post(
                "/v1/boss/browser-tab/open-job",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "source_url": "https://example.com/job_detail/card_1-real.html",
                    "browser_channel": "msedge",
                },
            )

    assert response.status_code == 200
    bridge.open_job.assert_awaited_once_with(
        "https://www.zhipin.com/job_detail/card_1-real.html",
        "msedge",
    )
    assert external.status_code == 400


@pytest.mark.asyncio
async def test_http_client_sends_bearer_token_without_exposing_it():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.url.path == "/v1/health"
        return httpx.Response(200, json={"success": True})

    settings = AppSettings(
        browser_automation_service_url="http://host.docker.internal:8765",
        browser_automation_service_token=SecretStr(TOKEN),
    )
    client = BossAutomationClient(settings, transport=httpx.MockTransport(handler))

    assert await client.health() == {"success": True}


@pytest.mark.asyncio
async def test_http_client_forwards_existing_tab_status_and_preserves_host_detail():
    """Docker 主后端通过 POST 调用宿主机桥接，并保留可操作的 409 文案。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            409,
            json={
                "detail": {
                    "error": "browser_javascript_disabled",
                    "message": "请在浏览器中开启 Apple 事件 JavaScript",
                }
            },
        )

    settings = AppSettings(
        browser_automation_service_url="http://host.docker.internal:8765",
        browser_automation_service_token=SecretStr(TOKEN),
    )
    client = BossAutomationClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(BossAutomationError) as caught:
        await client.browser_tab_status("msedge")

    assert caught.value.status_code == 409
    assert "Apple 事件" in str(caught.value)
    assert requests[0].url.path == "/v1/boss/browser-tab/status"
    assert requests[0].method == "POST"


@pytest.mark.asyncio
async def test_http_client_forwards_send_message_payload():
    """主后端客户端必须调用专用发送端点并完整转发受控字段。"""

    requests: list[httpx.Request] = []
    message = "您好，我希望基于自己的真实项目经验进一步沟通这个岗位和团队需求。"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"success": True, "status": "sent"})

    settings = AppSettings(
        browser_automation_service_url="http://host.docker.internal:8765",
        browser_automation_service_token=SecretStr(TOKEN),
    )
    client = BossAutomationClient(settings, transport=httpx.MockTransport(handler))

    result = await client.browser_tab_send_message(
        "https://www.zhipin.com/job_detail/card_1-real.html",
        message,
        "chrome",
    )

    assert result == {"success": True, "status": "sent"}
    assert requests[0].url.path == "/v1/boss/browser-tab/send-message"
    assert json.loads(requests[0].content) == {
        "source_url": "https://www.zhipin.com/job_detail/card_1-real.html",
        "message_text": message,
        "browser_channel": "chrome",
    }


@pytest.mark.asyncio
async def test_http_client_preserves_ambiguous_send_marker():
    """宿主机报告点击可能已发生时，客户端必须保留歧义标记供上层阻止重试。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boss/browser-tab/send-message"
        return httpx.Response(
            409,
            json={
                "detail": {
                    "error": "message_send_unverified",
                    "message": "发送后无法确认消息气泡，请人工复核。",
                    "request_may_have_run": True,
                }
            },
        )

    settings = AppSettings(
        browser_automation_service_url="http://host.docker.internal:8765",
        browser_automation_service_token=SecretStr(TOKEN),
    )
    client = BossAutomationClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(BossAutomationError) as caught:
        await client.browser_tab_send_message(
            "https://www.zhipin.com/job_detail/card_1-real.html",
            "您好，我希望基于自己的真实项目经验进一步沟通这个岗位和团队需求。",
        )

    assert caught.value.status_code == 409
    assert caught.value.request_may_have_run is True
    assert "人工复核" in str(caught.value)


@pytest.mark.asyncio
async def test_main_jobs_api_routes_browser_tab_calls_to_host_client(monkeypatch):
    """容器主 API 必须经应用层调用宿主机能力，不能直接实例化 Apple 事件桥接。"""

    from app.api.jobs import get_boss_browser_tab_status, search_and_capture_current_boss_tab
    from app.schemas.job_schemas import BossTabCaptureRequest

    use_cases = MagicMock()
    use_cases.get_boss_browser_tab_status = AsyncMock(
        return_value={"success": True, "browser_channel": "msedge"}
    )
    use_cases.search_and_capture_boss_tab = AsyncMock(
        return_value={"success": True, "cards": []}
    )
    monkeypatch.setattr("app.api.jobs.jobs_use_cases", use_cases)

    request = BossTabCaptureRequest(query="Agent")
    status_result = await get_boss_browser_tab_status("msedge", "user-1")
    capture_result = await search_and_capture_current_boss_tab(request, "user-1")

    assert status_result["success"] is True
    assert capture_result["success"] is True
    use_cases.get_boss_browser_tab_status.assert_awaited_once_with(browser_channel="msedge")
    use_cases.search_and_capture_boss_tab.assert_awaited_once_with(request=request)
