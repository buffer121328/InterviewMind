"""提供Langfuse提示词管理相关后端功能。"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from ai.prompts.management_catalog import is_retired_managed_prompt

from app.schemas.langfuse_prompts import (
    PromptBuiltinSyncResponse,
    PromptChatMessage,
    PromptCreateRequest,
    PromptMetadataResponse,
    PromptPreviewResponse,
    PromptType,
    PromptVersionResponse,
)
from observability import LangfuseConfig, get_langfuse_client

logger = logging.getLogger(__name__)
_TEMPLATE_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class PromptManagementUnavailable(Exception):
    """定义提示词管理不可用相关后端数据结构或服务组件。"""


class PromptManagementRemoteError(Exception):
    """定义提示词管理错误相关后端数据结构或服务组件。"""


class PromptManagementRetiredPrompt(Exception):
    """请求试图读取或修改已经退役的内置提示词。"""


@dataclass(frozen=True)
class PromptListPage:
    """定义提示词列表分页相关后端数据结构或服务组件。"""

    items: list[PromptMetadataResponse]
    total: int
    page: int
    limit: int


class LangfusePromptManagementService:
    """定义Langfuse提示词管理服务相关后端数据结构或服务组件。"""

    def _client(self) -> Any:
        """处理客户端相关后端逻辑。"""
        config = LangfuseConfig.from_env()
        if (
            not config.enabled
            or not config.prompt_management_enabled
            or not config.public_key
            or not config.secret_key
        ):
            raise PromptManagementUnavailable()
        client = get_langfuse_client()
        if client is None:
            raise PromptManagementUnavailable()
        return client

    @staticmethod
    def _reject_retired_prompt(name: str) -> None:
        """在远端调用前阻止已退役的内置提示词被复活。

        Args:
            name: 名称。
        """

        if is_retired_managed_prompt(name):
            raise PromptManagementRetiredPrompt()


    def list_prompts(self, *, page: int, limit: int, label: str | None = None) -> PromptListPage:
        """列出提示词相关后端逻辑。"""
        try:
            client = self._client()
            remote_page = 1
            remote_limit = 100
            items: list[PromptMetadataResponse] = []
            while True:
                response = client.api.prompts.list(
                    page=remote_page,
                    limit=remote_limit,
                    label=label,
                )
                raw_items = list(getattr(response, "data", []))
                items.extend(
                    self._metadata(item)
                    for item in raw_items
                    if not is_retired_managed_prompt(str(getattr(item, "name", "")))
                )
                meta = getattr(response, "meta", None)
                remote_total = int(getattr(meta, "total_items", len(raw_items)))
                if not raw_items or remote_page * remote_limit >= remote_total:
                    break
                remote_page += 1

            start = (page - 1) * limit
            return PromptListPage(
                items=items[start:start + limit],
                total=len(items),
                page=page,
                limit=limit,
            )
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("list", error)
            raise PromptManagementRemoteError() from error

    def fetch_prompt(self, *, name: str, version: int | None, label: str | None) -> PromptVersionResponse:
        """获取提示词相关后端逻辑。"""
        self._reject_retired_prompt(name)
        if (version is None) == (label is None):
            raise ValueError("exactly one of version or label is required")
        try:
            # 说明：保留这里的兼容性、安全性或流程约束。
            # 说明：schema-restricted so encoded slashes cannot alter an application route.
            prompt = self._client().api.prompts.get(name, version=version, label=label, resolve=False)
            return self._version(prompt)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("fetch", error)
            raise PromptManagementRemoteError() from error

    def create_version(self, request: PromptCreateRequest) -> PromptVersionResponse:
        """创建版本相关后端逻辑。"""
        self._reject_retired_prompt(request.name)
        try:
            prompt = self._client().create_prompt(
                name=request.name,
                prompt=[message.model_dump() for message in request.prompt]
                if isinstance(request.prompt, list)
                else request.prompt,
                labels=request.labels,
                type=request.type,
                commit_message=request.commit_message,
            )
            return self._version(prompt)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("create", error)
            raise PromptManagementRemoteError() from error

    def update_labels(self, *, name: str, version: int, labels: list[str]) -> PromptVersionResponse:
        """更新标签相关后端逻辑。"""
        self._reject_retired_prompt(name)
        try:
            prompt = self._client().update_prompt(name=name, version=version, new_labels=labels)
            return self._version(prompt)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("update-labels", error)
            raise PromptManagementRemoteError() from error

    def sync_builtin_production_prompts(self) -> PromptBuiltinSyncResponse:
        """同步内置生产提示词相关后端逻辑。"""
        from ai.prompts.management_catalog import latest_builtin_managed_prompts

        try:
            production_names: set[str] = set()
            page = 1
            limit = 100
            while True:
                result = self.list_prompts(page=page, limit=limit, label="production")
                production_names.update(item.name for item in result.items)
                if page * limit >= result.total or not result.items:
                    break
                page += 1

            builtins = latest_builtin_managed_prompts()
            created_names: list[str] = []
            client = self._client()
            for builtin in builtins:
                if builtin.name in production_names:
                    continue
                client.create_prompt(
                    name=builtin.name,
                    prompt=builtin.prompt,
                    labels=["production"],
                    type=builtin.prompt_type,
                    commit_message=(
                        f"Sync built-in {builtin.name}@{builtin.version}: "
                        f"{builtin.description}"
                    )[:500],
                )
                created_names.append(builtin.name)
            return PromptBuiltinSyncResponse(
                discovered=len(builtins),
                created=len(created_names),
                skipped=len(builtins) - len(created_names),
                created_names=created_names,
            )
        except PromptManagementUnavailable:
            raise
        except PromptManagementRemoteError:
            raise
        except Exception as error:
            self._log_remote_failure("sync-builtins", error)
            raise PromptManagementRemoteError() from error

    def preview(
        self, *, name: str, version: int | None, label: str | None, values: dict[str, str]
    ) -> PromptPreviewResponse:
        """预览Langfuse提示词管理相关后端逻辑。"""
        fetched = self.fetch_prompt(name=name, version=version, label=label)
        if isinstance(fetched.prompt, str):
            compiled, unresolved = self._compile_text(fetched.prompt, values)
        else:
            compiled_messages: list[PromptChatMessage] = []
            unresolved: set[str] = set()
            for message in fetched.prompt:
                content, missing = self._compile_text(message.content, values)
                compiled_messages.append(PromptChatMessage(role=message.role, content=content))
                unresolved.update(missing)
            compiled = compiled_messages
        return PromptPreviewResponse(
            **fetched.model_dump(),
            compiled_prompt=compiled,
            unresolved_variables=sorted(unresolved),
        )

    @staticmethod
    def _compile_text(template: str, values: dict[str, str]) -> tuple[str, set[str]]:
        """处理文本相关后端逻辑。"""
        unresolved: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in values:
                unresolved.add(variable)
                return match.group(0)
            return values[variable]

        return _TEMPLATE_VARIABLE.sub(replace, template), unresolved

    @staticmethod
    def _metadata(value: Any) -> PromptMetadataResponse:
        """处理元数据相关后端逻辑。"""
        from ai.prompts.management_catalog import prompt_presentation

        name = str(getattr(value, "name"))
        presentation = prompt_presentation(name)
        updated_at = getattr(value, "last_updated_at", None)
        return PromptMetadataResponse(
            name=name,
            display_name=presentation.display_name,
            functional_group=presentation.functional_group,
            is_builtin=presentation.is_builtin,
            type=LangfusePromptManagementService._prompt_type(value),
            versions=[int(item) for item in getattr(value, "versions", [])],
            labels=[str(item) for item in getattr(value, "labels", [])],
            last_updated_at=updated_at.isoformat() if updated_at is not None else None,
        )

    @staticmethod
    def _version(value: Any) -> PromptVersionResponse:
        """处理版本相关后端逻辑。"""
        from ai.prompts.management_catalog import prompt_presentation

        source = value
        name = str(getattr(source, "name"))
        presentation = prompt_presentation(name)
        content = getattr(source, "prompt", None)
        prompt_type = LangfusePromptManagementService._prompt_type(source, content)
        if prompt_type == "text":
            if not isinstance(content, str):
                raise ValueError("Langfuse returned an invalid text prompt")
            normalized_content: str | list[PromptChatMessage] = content
        else:
            if not isinstance(content, list):
                raise ValueError("Langfuse returned an invalid chat prompt")
            normalized_content = [LangfusePromptManagementService._chat_message(item) for item in content]
        return PromptVersionResponse(
            name=name,
            display_name=presentation.display_name,
            functional_group=presentation.functional_group,
            is_builtin=presentation.is_builtin,
            type=prompt_type,
            version=int(getattr(source, "version")),
            labels=[str(item) for item in getattr(source, "labels", [])],
            prompt=normalized_content,
        )

    @staticmethod
    def _prompt_type(value: Any, content: Any = None) -> PromptType:
        """处理提示词类型相关后端逻辑。"""
        raw = getattr(value, "type", "")
        normalized = str(getattr(raw, "value", raw)).lower()
        if not normalized and isinstance(content, str):
            return "text"
        if not normalized and isinstance(content, list):
            return "chat"
        if normalized not in {"text", "chat"}:
            raise ValueError("Langfuse returned an unsupported prompt type")
        return normalized  # type: ignore[return-value]

    @staticmethod
    def _chat_message(value: Any) -> PromptChatMessage:
        """处理聊天消息相关后端逻辑。"""
        if isinstance(value, dict):
            role, content = value.get("role"), value.get("content")
        else:
            role, content = getattr(value, "role", None), getattr(value, "content", None)
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError("Langfuse returned an invalid chat message")
        return PromptChatMessage.model_validate({"role": role, "content": content})

    @staticmethod
    def _log_remote_failure(operation: str, error: Exception) -> None:
        """处理日志失败相关后端逻辑。"""
        logger.warning("Langfuse prompt management %s failed: %s", operation, type(error).__name__)
