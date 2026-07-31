"""Bounded server-side Langfuse Prompt Management integration."""

import logging
import re
from dataclasses import dataclass
from typing import Any

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
    """Raised when the opt-in prompt-management client is not safely available."""


class PromptManagementRemoteError(Exception):
    """Raised for a Langfuse API failure without exposing remote response content."""


@dataclass(frozen=True)
class PromptListPage:
    """Safe metadata page returned by the Langfuse Prompt Management service."""

    items: list[PromptMetadataResponse]
    total: int
    page: int
    limit: int


class LangfusePromptManagementService:
    """Expose only prompt CRUD-like operations backed by the installed Langfuse SDK.

    This service never accepts remote URLs, credentials, arbitrary SDK resource names,
    or model-execution instructions. SDK exceptions are logged only by type so prompt
    templates and credentials cannot enter application logs.
    """

    def _client(self) -> Any:
        """Return a configured SDK client or raise a safe, feature-level error."""
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

    def list_prompts(self, *, page: int, limit: int, label: str | None = None) -> PromptListPage:
        """List only prompt metadata through Langfuse's explicit public API resource."""
        try:
            response = self._client().api.prompts.list(page=page, limit=limit, label=label)
            items = [self._metadata(item) for item in getattr(response, "data", [])]
            meta = getattr(response, "meta", None)
            total = int(getattr(meta, "total_items", len(items)))
            return PromptListPage(items=items, total=total, page=page, limit=limit)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("list", error)
            raise PromptManagementRemoteError() from error

    def fetch_prompt(self, *, name: str, version: int | None, label: str | None) -> PromptVersionResponse:
        """Fetch one explicitly selected prompt version or label without path interpolation."""
        if (version is None) == (label is None):
            raise ValueError("exactly one of version or label is required")
        try:
            # The official generated SDK owns its URL encoding; names are additionally
            # schema-restricted so encoded slashes cannot alter an application route.
            prompt = self._client().api.prompts.get(name, version=version, label=label, resolve=False)
            return self._version(prompt)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("fetch", error)
            raise PromptManagementRemoteError() from error

    def create_version(self, request: PromptCreateRequest) -> PromptVersionResponse:
        """Create a new immutable version using only validated content and labels."""
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
        """Promote or demote an immutable version by replacing its validated labels."""
        try:
            prompt = self._client().update_prompt(name=name, version=version, new_labels=labels)
            return self._version(prompt)
        except PromptManagementUnavailable:
            raise
        except Exception as error:
            self._log_remote_failure("update-labels", error)
            raise PromptManagementRemoteError() from error

    def sync_builtin_production_prompts(self) -> PromptBuiltinSyncResponse:
        """Create missing production prompts from the latest local registry versions.

        Existing production prompts are never overwritten. This makes the operation
        safe to retry after a partial remote failure and preserves cloud-owned edits.
        """
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
        """Compile simple mustache variables locally after fetching a selected prompt.

        Compilation is string substitution only: it neither invokes a model nor resolves
        Langfuse dependencies/placeholders. Unprovided variables remain visible to callers.
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
        """Substitute provided simple variables once and return variables left unresolved."""
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
        """Map SDK metadata to an explicit response model without template content."""
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
        """Map either a generated prompt object or SDK prompt client to a safe schema."""
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
        """Normalize generated prompt types and infer type for SDK prompt clients.

        The inspected SDK's ``create_prompt`` returns a prompt client with no ``type``
        attribute, while the generated public API returns a prompt object with one.
        Only those two response shapes are accepted.
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
        """Normalize a Langfuse chat message while retaining only role and content."""
        if isinstance(value, dict):
            role, content = value.get("role"), value.get("content")
        else:
            role, content = getattr(value, "role", None), getattr(value, "content", None)
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError("Langfuse returned an invalid chat message")
        return PromptChatMessage.model_validate({"role": role, "content": content})

    @staticmethod
    def _log_remote_failure(operation: str, error: Exception) -> None:
        """Log failure classification only, intentionally excluding templates and SDK details."""
        logger.warning("Langfuse prompt management %s failed: %s", operation, type(error).__name__)
