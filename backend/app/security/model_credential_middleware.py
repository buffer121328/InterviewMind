"""ASGI middleware that hydrates model credential references from Redis."""

from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai.workflows.model_credentials import ModelCredentialErrorForRequest, ModelCredentialUseCases
from app.security.model_credentials import InvalidModelCredentialId, ModelCredentialError, get_model_credential_store

_EXCLUDED_PATH_PREFIXES = (
    "/api/config/validate",
    "/api/config/credentials",
)


class ModelCredentialHydrationMiddleware:
    """Resolve request credential IDs before FastAPI schema validation and workflows."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap an ASGI application without buffering non-JSON requests."""

        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Hydrate JSON api_config nodes and preserve the original ASGI request contract."""

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
            await use_cases.hydrate_request(payload, user_id)
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
    def _should_inspect(scope: Scope) -> bool:
        """Return whether this request can contain a JSON business payload."""

        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return False
        path = scope.get("path", "")
        if path.startswith(_EXCLUDED_PATH_PREFIXES):
            return False
        content_type = ModelCredentialHydrationMiddleware._header(scope, b"content-type") or ""
        return "application/json" in content_type.lower()

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        """Read the complete ASGI HTTP body."""

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
        """Create a receive callable that replays the rewritten body exactly once."""

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
        """Read a case-insensitive ASCII request header."""

        for key, value in scope.get("headers", []):
            if key.lower() == name:
                return value.decode("latin-1")
        return None

    @staticmethod
    def _with_content_length(scope: Scope, length: int) -> Scope:
        """Clone an HTTP scope with the rewritten Content-Length header."""

        updated = dict(scope)
        headers = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"content-length"]
        headers.append((b"content-length", str(length).encode("ascii")))
        updated["headers"] = headers
        return updated
