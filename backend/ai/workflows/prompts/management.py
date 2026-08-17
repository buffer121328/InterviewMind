"""Langfuse 提示词管理服务（列出、获取、创建版本、更新标签、预览与内置同步）。"""

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
# 匹配 Mustache 模板变量 {{ name }}。
_TEMPLATE_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class PromptManagementUnavailable(Exception):
    """Langfuse 未启用或未配置，提示词管理不可用。"""


class PromptManagementRemoteError(Exception):
    """Langfuse 远端调用失败。"""


class PromptManagementRetiredPrompt(Exception):
    """请求试图读取或修改已经退役的内置提示词。"""


@dataclass(frozen=True)
class PromptListPage:
    """提示词列表分页结果。"""

    # 当前页提示词元数据列表。
    # 元素列表。
    items: list[PromptMetadataResponse]
    # 匹配提示词总数。
    # 总数。
    total: int
    # 页码（从 1 开始）。
    # 页码（从 1 开始）。
    page: int
    # 每页数量。
    # 返回数量上限。
    limit: int


class LangfusePromptManagementService:
    """封装对 Langfuse 的提示词管理调用。"""

    def _client(self) -> Any:
        """返回已配置的 Langfuse 客户端；未启用时抛 PromptManagementUnavailable。"""
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
        """分页列出提示词元数据，并在本地过滤已退役的内置名称。

        远端分页总数包含历史已退役记录，不能直接透传给 UI；因此以固定
        批量页读取、先过滤、再按调用方页码切片。

        Args:
            page: 页码（从 1 开始）。
            limit: 每页数量。
            label: 按标签过滤；None 表示不过滤。
        """
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
        """按版本或标签获取单个提示词（二者必须恰好提供其一）。

        Args:
            name: 提示词名称。
            version: 版本号。
            label: 标签名。
        """
        if (version is None) == (label is None):
            raise ValueError("exactly one of version or label is required")
        self._reject_retired_prompt(name)
        try:
            prompt = self._client().api.prompts.get(name, version=version, label=label, resolve=False)
            return self._version(prompt)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("fetch", error)
            raise PromptManagementRemoteError() from error

    def create_version(self, request: PromptCreateRequest) -> PromptVersionResponse:
        """创建提示词新版本。

        Args:
            request: 创建提示词请求。
        """
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
        """更新指定版本提示词的标签集。

        Args:
            name: 提示词名称。
            version: 版本号。
            labels: 新的标签列表。
        """
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
        """把内置生产提示词同步到 Langfuse（已存在的跳过）。"""
        from ai.prompts.management_catalog import latest_builtin_managed_prompts

        try:
            # ① 先收集远端已有的 production 标签提示词名。
            production_names: set[str] = set()
            page = 1
            limit = 100
            while True:
                result = self.list_prompts(page=page, limit=limit, label="production")
                production_names.update(item.name for item in result.items)
                if page * limit >= result.total or not result.items:
                    break
                page += 1

            # ② 逐个创建缺失的内置提示词。
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
        """用给定变量值渲染提示词并返回未解析变量列表。

        Args:
            name: 提示词名称。
            version: 版本号。
            label: 标签名。
            values: 模板变量取值。
        """
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
        """渲染 Mustache 模板；缺失变量保留原样并收集到未解析集合。

        Args:
            template: 模板文本。
            values: 变量取值字典。
        """
        unresolved: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            """replace 操作。

            Args:
                match: 匹配对象。
            """
            variable = match.group(1)
            if variable not in values:
                unresolved.add(variable)
                return match.group(0)
            return values[variable]

        return _TEMPLATE_VARIABLE.sub(replace, template), unresolved

    @staticmethod
    def _metadata(value: Any) -> PromptMetadataResponse:
        """把 Langfuse 提示词对象转换为元数据响应。

        Args:
            value: Langfuse 提示词对象。
        """
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
        """把 Langfuse 版本对象转换为版本响应。

        Args:
            value: Langfuse 提示词版本对象。
        """
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
        """推断提示词类型（text/chat）。

        Args:
            value: Langfuse 提示词对象。
            content: 可选的提示词内容，用于缺省类型判断。
        """
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
        """把 dict 或对象转换为聊天消息。

        Args:
            value: 消息字典或对象。
        """
        if isinstance(value, dict):
            role, content = value.get("role"), value.get("content")
        else:
            role, content = getattr(value, "role", None), getattr(value, "content", None)
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError("Langfuse returned an invalid chat message")
        return PromptChatMessage.model_validate({"role": role, "content": content})

    @staticmethod
    def _log_remote_failure(operation: str, error: Exception) -> None:
        """记录远端操作失败日志。

        Args:
            operation: 操作标识。
            error: 触发的异常。
        """
        logger.warning("Langfuse prompt management %s failed: %s", operation, type(error).__name__)
