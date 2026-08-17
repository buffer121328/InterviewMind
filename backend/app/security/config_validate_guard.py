"""`/api/config/validate` 的输入边界守卫。

无登录本地模式下，该端点接受调用方指定的模型 Base URL 并发起真实出站
连接；在阶段 0 loopback 边界之上再施加请求体上限、频率与并发限制，
防止滥用与资源耗尽。限流为进程内实现，适配单进程 API 部署。
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PROTECTED_PATH = "/api/config/validate"
_MAX_BODY_BYTES = 8 * 1024
_RATE_WINDOW_SECONDS = 60.0
_RATE_MAX_REQUESTS = 20
_MAX_CONCURRENT = 4


class ConfigValidateGuardMiddleware:
    """/api/config/validate 的请求体大小、频率与并发守卫。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._inflight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") != _PROTECTED_PATH:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_id = client[0] if client else "unknown"
        allowed = await self._admit(client_id)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "验证请求过于频繁，请稍后再试"},
            )
            await response(scope, receive, send)
            return

        body = await self._read_bounded(receive)
        if body is None:
            response = JSONResponse(
                status_code=413,
                content={"detail": "请求体过大"},
            )
            await response(scope, receive, send)
            return

        if self._inflight >= _MAX_CONCURRENT:
            await self._release(client_id)
            response = JSONResponse(
                status_code=429,
                content={"detail": "验证请求繁忙，请稍后再试"},
            )
            await response(scope, receive, send)
            return

        self._inflight += 1
        try:
            await self.app(scope, self._replay(body, receive), send)
        finally:
            self._inflight -= 1

    async def _admit(self, client_id: str) -> bool:
        """滑动窗口限流：记录本次请求并判断窗口内是否超限。"""

        now = time.monotonic()
        async with self._lock:
            events = self._events[client_id]
            while events and now - events[0] > _RATE_WINDOW_SECONDS:
                events.popleft()
            if len(events) >= _RATE_MAX_REQUESTS:
                return False
            events.append(now)
            return True

    async def _release(self, client_id: str) -> None:
        """限流被并发分支拒绝时撤销刚记录的事件。"""

        async with self._lock:
            events = self._events.get(client_id)
            if events:
                events.pop()

    @staticmethod
    async def _read_bounded(receive: Receive) -> bytes | None:
        """读取请求体并在超过上限时返回 None（不缓冲超大输入）。"""

        chunks: list[bytes] = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > _MAX_BODY_BYTES:
                return None
            chunks.append(chunk)
            more_body = message.get("more_body", False)
        return b"".join(chunks)

    @staticmethod
    def _replay(body: bytes, original_receive: Receive) -> Receive:
        """把已读取的请求体重放给下游应用。"""

        delivered = False

        async def receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await original_receive()

        return receive
