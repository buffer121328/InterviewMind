"""Use cases for encrypted Redis model credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.security.model_credentials import ModelCredentialStore, StoredCredentialStatus


def _serialize_status(status: StoredCredentialStatus) -> dict[str, object]:
    """Serialize non-sensitive status metadata for the API boundary."""

    return {
        "model_id": status.model_id,
        "stored": status.stored,
        "expires_at": status.expires_at.isoformat() if isinstance(status.expires_at, datetime) else None,
    }


class ModelCredentialUseCases:
    """Coordinate storage and request-time credential hydration."""

    def __init__(self, store: ModelCredentialStore) -> None:
        """Create use cases around an injected credential store."""

        self._store = store

    async def put(self, user_id: str, model_id: str, api_key: str) -> dict[str, object]:
        """Persist one key and return metadata only."""

        return _serialize_status(await self._store.put(user_id, model_id, api_key))

    async def delete(self, user_id: str, model_id: str) -> dict[str, object]:
        """Delete one credential without exposing prior content."""

        deleted = await self._store.delete(user_id, model_id)
        return {"model_id": model_id, "deleted": deleted}

    async def statuses(self, user_id: str, model_ids: list[str]) -> dict[str, object]:
        """Return secret-free status metadata for known local models."""

        statuses = await self._store.statuses(user_id, model_ids)
        return {"credentials": [_serialize_status(status) for status in statuses]}

    async def hydrate_request(self, payload: Any, user_id: str) -> Any:
        """Replace credential references inside every api_config object with Redis secrets."""

        await self._walk(payload, user_id, inside_api_config=False)
        return payload

    async def _walk(self, value: Any, user_id: str, *, inside_api_config: bool) -> None:
        """Recursively find api_config channels while leaving unrelated JSON untouched."""

        if isinstance(value, list):
            for item in value:
                await self._walk(item, user_id, inside_api_config=inside_api_config)
            return
        if not isinstance(value, dict):
            return
        if inside_api_config and isinstance(value.get("credential_id"), str):
            credential_id = value["credential_id"]
            api_key = await self._store.get(user_id, credential_id)
            if api_key is None:
                raise ModelCredentialErrorForRequest(credential_id)
            value["api_key"] = api_key
        for key, child in value.items():
            await self._walk(child, user_id, inside_api_config=inside_api_config or key == "api_config")


class ModelCredentialErrorForRequest(RuntimeError):
    """A request references a missing or expired credential."""

    def __init__(self, credential_id: str) -> None:
        """Record only the non-secret credential identifier."""

        super().__init__("模型 API Key 未保存或已过期，请在模型设置中重新填写")
        self.credential_id = credential_id
