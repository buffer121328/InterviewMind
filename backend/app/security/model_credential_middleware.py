"""提供模型凭据中间件相关后端功能。"""

from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai.workflows.configuration.model_credentials import (
    ModelCredentialErrorForRequest,
    ModelCredentialUseCases,
)
from app.security.model_credentials import (
    InvalidModelCredentialId,
    ModelCredentialError,
    get_model_credential_store,
)

MEMORY_CREDENTIAL_CHANNELS = frozenset({"mem0_llm", "mem0_embedder", "rag_embedding"})

_EXCLUDED_PATH_PREFIXES = (
    "/api/config/validate",
    "/api/config/credentials",
)


class ModelCredentialHydrationMiddleware:
    """定义模型凭据注入中间件相关后端数据结构或服务组件。"""

    def __init__(self, app: ASGIApp) -> None:
        """初始化模型凭据中间件相关状态。"""

        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """处理模型凭据中间件相关后端逻辑。"""

        if not self._should_inspect(scope):
            await self.app(scope, receive, send)
            return

        body = await self._read_body(receive)
        if b'"credential_id"' not in body:
            await self.app(scope, self._replacement_receive(body, receive), send)
            return
        try:
            payload: Any = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self.app(scope, self._replacement_receive(body, receive), send)
            return

        user_id = self._header(scope, b"x-user-id") or "default_user"
        try:
            use_cases = ModelCredentialUseCases(get_model_credential_store())
            allowed_channels = self._allowed_channels(scope, payload)
            await use_cases.hydrate_request(
                payload,
                user_id,
                allowed_channels=allowed_channels,
            )
        except ModelCredentialErrorForRequest as exc:
            response = JSONResponse(status_code=401, content={"detail": str(exc)})
            await response(scope, receive, send)
            return
        except InvalidModelCredentialId as exc:
            response = JSONResponse(status_code=400, content={"detail": str(exc)})
            await response(scope, receive, send)
            return
        except ModelCredentialError as exc:
            response = JSONResponse(status_code=503, content={"detail": str(exc)})
            await response(scope, receive, send)
            return

        hydrated_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        hydrated_scope = self._with_content_length(scope, len(hydrated_body))
        await self.app(hydrated_scope, self._replacement_receive(hydrated_body, receive), send)


    @staticmethod
    def _allowed_channels(scope: Scope, payload: Any) -> frozenset[str] | None:
        """处理渠道相关后端逻辑。"""

        path = str(scope.get("path", ""))
        if path == "/api/evaluations/interview-history/drafts" or (
            path.startswith("/api/evaluations/interview-history/drafts/")
            and path.endswith("/retry-failed")
        ):
            # 草稿任务必须把 credential references 原样加密入队；Worker 会按候选
            # 模型名逐个水合，避免无关过期凭据提前阻塞整个请求。
            return frozenset()
        if path != "/api/memory" and not path.startswith("/api/memory/"):
            return None
        channels = {"mem0_llm"}
        api_config = payload.get("api_config") if isinstance(payload, dict) else None
        if not isinstance(api_config, dict):
            return frozenset(channels)
        embedder = api_config.get("mem0_embedder")
        if isinstance(embedder, dict) and embedder.get("base_url") and embedder.get("model"):
            channels.add("mem0_embedder")
        else:
            channels.add("rag_embedding")
        return frozenset(channels) & MEMORY_CREDENTIAL_CHANNELS

    @staticmethod
    def _should_inspect(scope: Scope) -> bool:
        """处理是否应当检查相关后端逻辑。"""

        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        path = scope.get("path", "")
        if path.startswith(_EXCLUDED_PATH_PREFIXES):
            return False
        content_type = ModelCredentialHydrationMiddleware._header(scope, b"content-type") or ""
        return "application/json" in content_type.lower()

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        """读取模型凭据中间件相关后端逻辑。"""

        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        return b"".join(chunks)

    @staticmethod
    def _replacement_receive(body: bytes, original_receive: Receive) -> Receive:
        """处理接收相关后端逻辑。"""

        delivered = False

        async def receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await original_receive()

        return receive

    @staticmethod
    def _header(scope: Scope, name: bytes) -> str | None:
        """处理请求头相关后端逻辑。"""

        for key, value in scope.get("headers", []):
            if key.lower() == name:
                return value.decode("latin-1")
        return None

    @staticmethod
    def _with_content_length(scope: Scope, length: int) -> Scope:
        """处理内容相关后端逻辑。"""

        updated = dict(scope)
        headers = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"content-length"]
        headers.append((b"content-length", str(length).encode("ascii")))
        updated["headers"] = headers
        return updated
