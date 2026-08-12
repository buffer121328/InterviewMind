"""提供模型凭据相关后端功能。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.security.model_credentials import ModelCredentialStore, StoredCredentialStatus


def _serialize_status(status: StoredCredentialStatus) -> dict[str, object]:
    """序列化状态相关后端逻辑。"""

    return {
        "model_name": status.model_name,
        "stored": status.stored,
        "expires_at": status.expires_at.isoformat() if isinstance(status.expires_at, datetime) else None,
    }


class ModelCredentialUseCases:
    """定义模型凭据用例案例相关后端数据结构或服务组件。"""

    def __init__(self, store: ModelCredentialStore) -> None:
        self._store = store

    async def put(
        self,
        user_id: str,
        model_name: str,
        *,
        api_key: str | None,
        source_model: str | None,
        legacy_id: str | None,
    ) -> dict[str, object]:
        """写入模型凭据相关后端逻辑。"""

        if api_key and api_key.strip():
            status = await self._store.put(
                user_id,
                model_name,
                api_key,
                legacy_id=legacy_id,
            )
        elif source_model:
            status = await self._store.move(
                user_id,
                source_model,
                model_name,
                legacy_id=legacy_id,
            )
        else:
            raise ValueError("必须提供 API Key 或原模型名称")
        return _serialize_status(status)

    async def delete(
        self,
        user_id: str,
        model_name: str,
        *,
        legacy_id: str | None = None,
    ) -> dict[str, object]:
        """删除模型凭据相关后端逻辑。"""

        deleted = await self._store.delete(user_id, model_name, legacy_id=legacy_id)
        return {"model_name": model_name, "deleted": deleted}

    async def statuses(
        self,
        user_id: str,
        models: list[tuple[str, str | None]],
    ) -> dict[str, object]:
        """处理状态相关后端逻辑。"""

        statuses = await self._store.statuses(user_id, models)
        return {"credentials": [_serialize_status(status) for status in statuses]}

    async def hydrate_request(
        self,
        payload: Any,
        user_id: str,
        *,
        allowed_channels: frozenset[str] | None = None,
    ) -> Any:
        """处理请求相关后端逻辑。"""

        await self._walk(
            payload,
            user_id,
            inside_api_config=False,
            allowed_channels=allowed_channels,
        )
        return payload

    async def _walk(
        self,
        value: Any,
        user_id: str,
        *,
        inside_api_config: bool,
        allowed_channels: frozenset[str] | None,
    ) -> None:
        """处理模型凭据相关后端逻辑。"""

        if isinstance(value, list):
            for item in value:
                await self._walk(
                    item,
                    user_id,
                    inside_api_config=inside_api_config,
                    allowed_channels=allowed_channels,
                )
            return
        if not isinstance(value, dict):
            return
        if inside_api_config and isinstance(value.get("model"), str):
            model_name = value["model"]
            legacy_id = value.get("legacy_credential_id")
            api_key = await self._store.get(
                user_id,
                model_name,
                legacy_id=legacy_id if isinstance(legacy_id, str) else None,
            )
            if api_key is None:
                raise ModelCredentialErrorForRequest(model_name)
            value["api_key"] = api_key
        for key, child in value.items():
            if key == "api_config" and isinstance(child, dict) and allowed_channels is not None:
                for channel, channel_config in child.items():
                    if channel in allowed_channels:
                        await self._walk(
                            channel_config,
                            user_id,
                            inside_api_config=True,
                            allowed_channels=allowed_channels,
                        )
                continue
            await self._walk(
                child,
                user_id,
                inside_api_config=inside_api_config or key == "api_config",
                allowed_channels=allowed_channels,
            )


class ModelCredentialErrorForRequest(RuntimeError):
    """定义模型凭据错误请求相关后端数据结构或服务组件。"""

    def __init__(self, model_name: str) -> None:
        super().__init__(f"模型 {model_name} 的 API Key 未保存，请在模型设置中填写")
        self.credential_id = model_name
