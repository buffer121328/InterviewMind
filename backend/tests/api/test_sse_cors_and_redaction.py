"""SSE CORS 收口与错误脱敏回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import create_sse_response

_SSE_ROUTE_FILES = (
    Path(__file__).resolve().parents[2] / "app" / "api" / "interview" / "chat.py",
    Path(__file__).resolve().parents[2] / "app" / "api" / "resume" / "optimization.py",
    Path(__file__).resolve().parents[2] / "app" / "api" / "deps.py",
)


async def _events() -> str:
    yield "data: {\"ok\": true}\n\n"


def test_sse_factory_keeps_transport_headers_without_cors() -> None:
    """SSE 工厂只保留传输必要头，不再手写任何 CORS 放行头。"""

    response = create_sse_response(_events())
    headers = response.headers
    assert response.media_type == "text/event-stream"
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-headers" not in headers


def test_sse_routes_do_not_handwrite_cors_headers() -> None:
    """聊天/简历优化 SSE 与 SSE 工厂源码不回潮手写 Access-Control 头。"""

    for path in _SSE_ROUTE_FILES:
        source = path.read_text(encoding="utf-8")
        assert "Access-Control" not in source, f"{path.name} 不应手写 CORS 头"


@pytest.mark.asyncio
async def test_chat_stream_log_redacts_fixture_key(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """聊天流初始化异常中的 fixture Key 不进入日志。"""

    from app.api.interview import chat as chat_api
    from app.schemas.interview.schemas import ChatRequest

    fixture_key = "fixture-sk-sse-log-246810"

    async def failing_stream(*_args, **_kwargs):
        raise RuntimeError(f"connect failed with key {fixture_key}")

    monkeypatch.setattr(
        chat_api.chat_stream_use_cases,
        "stream_chat",
        failing_stream,
    )
    request = ChatRequest(
        thread_id="thread-1",
        message="你好",
        resume_context="resume",
        job_description="jd",
        api_config=None,
    )

    with caplog.at_level("ERROR"):
        try:
            await chat_api.stream_chat(request, user_id="user-1")
        except Exception:
            pass

    assert fixture_key not in caplog.text


def test_global_cors_allows_local_frontend_origin_only() -> None:
    """真实应用 preflight：本地前端 Origin 放行，外部 Origin 不获放行头。"""

    from app.main import app

    client = TestClient(app)

    allowed = client.options(
        "/api/config/validate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    denied = client.options(
        "/api/config/validate",
        headers={
            "Origin": "http://evil.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.headers.get("access-control-allow-origin") != "http://evil.example.test"
    assert denied.headers.get("access-control-allow-origin") is None
