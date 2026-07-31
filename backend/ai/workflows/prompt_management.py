"""Deprecated database-backed Prompt Management retained for stored-data compatibility.

Production Prompt Management now reads and writes Langfuse Cloud through
``LangfusePromptManagementService``. Existing rows remain untouched so a later
data-retention decision can be made explicitly.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from ai.prompts.management_catalog import prompt_presentation
from ai.prompts.registry import prompt_registry
from app.db.models import PromptVersionModel, async_session
from app.schemas.langfuse_prompts import (
    PromptChatMessage,
    PromptCreateRequest,
    PromptMetadataResponse,
    PromptPreviewResponse,
    PromptType,
    PromptVersionResponse,
)

_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class DatabasePromptManagementService:
    """Persist immutable prompt versions and resolve only owner-scoped production templates."""

    @staticmethod
    def _now() -> datetime:
        """Return the timestamp shared by prompt version write operations."""
        return datetime.now()

    @staticmethod
    def _response(row: PromptVersionModel) -> PromptVersionResponse:
        """Map a database row to the bounded prompt API contract."""
        presentation = prompt_presentation(row.name)
        prompt: str | list[PromptChatMessage]
        if row.prompt_type == "chat":
            prompt = [PromptChatMessage.model_validate(item) for item in row.prompt["messages"]]
        else:
            prompt = str(row.prompt["text"])
        labels = list(row.labels or [])
        if row.is_production:
            labels.append("production")
        prompt_type: PromptType = "chat" if row.prompt_type == "chat" else "text"
        return PromptVersionResponse(
            name=row.name,
            display_name=presentation.display_name,
            functional_group=presentation.functional_group,
            is_builtin=presentation.is_builtin,
            type=prompt_type,
            version=row.version,
            labels=labels,
            prompt=prompt,
        )

    @staticmethod
    def _to_mustache(template: str) -> str:
        """Expose local LangChain variables in the database editor's stable mustache syntax."""
        return re.sub(r"(?<!{){([A-Za-z_][A-Za-z0-9_]*)}(?!})", r"{{\1}}", template)

    @classmethod
    def _builtin_prompt(cls, name: str) -> PromptVersionResponse | None:
        """Return a read-only v0 view of a registered backend prompt without rendering user data."""
        presentation = prompt_presentation(name)
        try:
            spec = prompt_registry.get(name, "1")
        except KeyError:
            return None
        template = spec.template
        raw_template = getattr(template, "template", None)
        if isinstance(raw_template, str):
            return PromptVersionResponse(
                name=name,
                display_name=presentation.display_name,
                functional_group=presentation.functional_group,
                is_builtin=presentation.is_builtin,
                type="text",
                version=0,
                labels=["builtin"],
                prompt=cls._to_mustache(raw_template),
            )
        messages: list[PromptChatMessage] = []
        for message in getattr(template, "messages", []):
            content = getattr(getattr(message, "prompt", None), "template", None)
            role = getattr(message, "role", None)
            if isinstance(content, str) and isinstance(role, str) and role in {"system", "developer", "user", "assistant", "tool"}:
                messages.append(PromptChatMessage.model_validate({"role": role, "content": cls._to_mustache(content)}))
        if messages:
            return PromptVersionResponse(
                name=name,
                display_name=presentation.display_name,
                functional_group=presentation.functional_group,
                is_builtin=presentation.is_builtin,
                type="chat",
                version=0,
                labels=["builtin"],
                prompt=messages,
            )
        return None

    async def list_prompts(
        self,
        *,
        user_id: str,
        page: int,
        limit: int,
    ) -> tuple[list[PromptMetadataResponse], int]:
        """List one page of registered prompts and return the full owner-scoped total."""
        async with async_session() as session:
            rows = (await session.execute(
                select(PromptVersionModel.name, PromptVersionModel.prompt_type, PromptVersionModel.version,
                       PromptVersionModel.labels, PromptVersionModel.is_production, PromptVersionModel.updated_at)
                .where(PromptVersionModel.user_id == user_id)
                .order_by(PromptVersionModel.name, PromptVersionModel.version.desc())
            )).all()
        grouped: dict[str, dict[str, Any]] = {}
        for name in prompt_registry.names():
            builtin = self._builtin_prompt(name)
            if builtin:
                grouped[name] = {"type": builtin.type, "versions": [0], "labels": ["builtin"], "updated_at": None}
        for name, prompt_type, version, labels, is_production, updated_at in rows:
            item = grouped.setdefault(name, {"type": prompt_type, "versions": [], "labels": [], "updated_at": updated_at})
            item["versions"].append(version)
            item["labels"] = sorted(set(item["labels"]) | set(labels or []) | ({"production"} if is_production else set()))
        all_values = list(grouped.items())
        values = all_values[(page - 1) * limit:page * limit]
        items: list[PromptMetadataResponse] = []
        for name, item in values:
            presentation = prompt_presentation(name)
            items.append(PromptMetadataResponse(
                name=name,
                display_name=presentation.display_name,
                functional_group=presentation.functional_group,
                is_builtin=presentation.is_builtin,
                type=item["type"],
                versions=item["versions"],
                labels=item["labels"],
                last_updated_at=item["updated_at"].isoformat() if item["updated_at"] else None,
            ))
        return items, len(all_values)

    async def fetch_prompt(self, *, user_id: str, name: str, version: int | None, label: str | None) -> PromptVersionResponse | None:
        """Fetch one explicit version or production label under the owner boundary."""
        if version == 0:
            return self._builtin_prompt(name)
        async with async_session() as session:
            statement = select(PromptVersionModel).where(PromptVersionModel.user_id == user_id, PromptVersionModel.name == name)
            if version is not None:
                statement = statement.where(PromptVersionModel.version == version)
            elif label == "production":
                statement = statement.where(PromptVersionModel.is_production.is_(True))
            else:
                statement = statement.where(PromptVersionModel.labels.contains([label]))
            row = await session.scalar(statement)
        return self._response(row) if row else None

    async def create_version(self, *, user_id: str, request: PromptCreateRequest) -> PromptVersionResponse:
        """Append an immutable prompt version for one owner and never mutate past content."""
        async with async_session() as session:
            next_version = int(await session.scalar(select(func.coalesce(func.max(PromptVersionModel.version), 0)).where(PromptVersionModel.user_id == user_id, PromptVersionModel.name == request.name)) or 0) + 1
            payload = {"messages": [item.model_dump() for item in request.prompt]} if isinstance(request.prompt, list) else {"text": request.prompt}
            now = self._now()
            row = PromptVersionModel(user_id=user_id, name=request.name, version=next_version, prompt_type=request.type, prompt=payload, labels=request.labels, is_production=False, commit_message=request.commit_message, created_at=now, updated_at=now)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._response(row)

    async def update_labels(self, *, user_id: str, name: str, version: int, labels: list[str], production: bool = False) -> PromptVersionResponse | None:
        """Update display labels or atomically move the production pointer for one prompt name."""
        async with async_session() as session:
            row = await session.scalar(select(PromptVersionModel).where(PromptVersionModel.user_id == user_id, PromptVersionModel.name == name, PromptVersionModel.version == version).with_for_update())
            if not row:
                return None
            if production:
                previous = await session.scalars(select(PromptVersionModel).where(PromptVersionModel.user_id == user_id, PromptVersionModel.name == name, PromptVersionModel.is_production.is_(True)).with_for_update())
                for item in previous:
                    item.is_production = False
                    item.updated_at = self._now()
                row.is_production = True
            else:
                row.labels = labels
            row.updated_at = self._now()
            await session.commit()
            await session.refresh(row)
            return self._response(row)

    async def preview(self, *, user_id: str, name: str, version: int | None, label: str | None, values: dict[str, str]) -> PromptPreviewResponse | None:
        """Render a selected template locally; this endpoint never invokes an LLM."""
        fetched = await self.fetch_prompt(user_id=user_id, name=name, version=version, label=label)
        if not fetched:
            return None
        def compile_text(text: str) -> tuple[str, set[str]]:
            missing: set[str] = set()
            def replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in values:
                    missing.add(key)
                    return match.group(0)
                return values[key]
            return _VARIABLE.sub(replace, text), missing
        if isinstance(fetched.prompt, str):
            compiled, unresolved = compile_text(fetched.prompt)
        else:
            unresolved = set()
            compiled = []
            for message in fetched.prompt:
                content, missing = compile_text(message.content)
                unresolved.update(missing)
                compiled.append(PromptChatMessage(role=message.role, content=content))
        return PromptPreviewResponse(**fetched.model_dump(), compiled_prompt=compiled, unresolved_variables=sorted(unresolved))

    async def resolve_text(self, *, user_id: str, name: str, values: dict[str, str], fallback: str) -> tuple[str, int | None]:
        """Resolve a production text template with a built-in fallback for service continuity."""
        selected = await self.fetch_prompt(user_id=user_id, name=name, version=None, label="production")
        if not selected or not isinstance(selected.prompt, str):
            return fallback, None
        return _VARIABLE.sub(lambda match: values.get(match.group(1), match.group(0)), selected.prompt), selected.version
