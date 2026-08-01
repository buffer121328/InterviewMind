"""Read-only acceptance test for the real macOS BOSS browser bridge.

The test never navigates, captures cards, or sends a message.  It is skipped
unless both test-only service variables are explicitly configured:

    TEST_BOSS_BROWSER_SERVICE_URL=http://127.0.0.1:8765 \
    TEST_BOSS_BROWSER_SERVICE_TOKEN=... \
    uv run pytest -q -m "integration and requires_boss_browser" \
        tests/integration/test_boss_browser_service_integration.py
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
@pytest.mark.requires_boss_browser
def test_real_boss_bridge_authentication_and_tab_status_are_read_only() -> None:
    """Verify authenticated health and current-tab inspection without external side effects."""

    service_url = os.getenv("TEST_BOSS_BROWSER_SERVICE_URL", "").strip().rstrip("/")
    token = os.getenv("TEST_BOSS_BROWSER_SERVICE_TOKEN", "").strip()
    if not service_url or len(token) < 32:
        pytest.skip("需要有效的 TEST_BOSS_BROWSER_SERVICE_URL 和 32+ 字符测试 Token")

    httpx = pytest.importorskip("httpx")
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(
        base_url=service_url,
        headers=headers,
        timeout=10,
        follow_redirects=False,
    ) as client:
        health_response = client.post("/v1/health", json={})
        health_response.raise_for_status()
        status_response = client.post("/v1/boss/browser-tab/status", json={})
        status_response.raise_for_status()

    health = health_response.json()
    tab_status = status_response.json()
    assert health["success"] is True
    assert "send_message" in health["capabilities"]
    assert isinstance(tab_status.get("connected"), bool)
    assert token not in health_response.text
    assert token not in status_response.text
