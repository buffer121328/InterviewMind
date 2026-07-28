"""Schemas for the bounded, server-side Langfuse Prompt Management API."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


PromptType = Literal["text", "chat"]
_PROMPT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class PromptChatMessage(BaseModel):
    """A bounded chat message accepted by and returned from prompt management."""

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: Annotated[str, Field(min_length=1, max_length=20_000)]


class PromptCreateRequest(BaseModel):
    """Request to create one immutable Langfuse prompt version.

    The request intentionally excludes arbitrary Langfuse configuration, tags, and
    transport parameters so this endpoint cannot become a generic Langfuse proxy.
    """

    name: Annotated[str, Field(min_length=1, max_length=128)]
    type: PromptType
    prompt: str | list[PromptChatMessage]
    labels: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list,
        max_length=8,
    )
    commit_message: Annotated[str | None, Field(max_length=500)] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Reject path-like and otherwise unsafe prompt names before SDK calls."""
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        """Validate bounded, unique labels while reserving production promotion."""
        if len(set(values)) != len(values):
            raise ValueError("labels must be unique")
        for value in values:
            if value in {"latest", "production"} or not _LABEL_PATTERN.fullmatch(value):
                raise ValueError("labels must be valid identifiers and cannot be 'latest' or 'production'")
        return values

    @model_validator(mode="after")
    def validate_prompt_for_type(self) -> "PromptCreateRequest":
        """Ensure text and chat prompt bodies use their matching content shape."""
        if self.type == "text":
            if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt) > 40_000:
                raise ValueError("text prompts must be non-empty strings of at most 40000 characters")
        elif not isinstance(self.prompt, list) or not self.prompt or len(self.prompt) > 50:
            raise ValueError("chat prompts must contain between 1 and 50 messages")
        return self


class PromptLabelUpdateRequest(BaseModel):
    """Request to atomically replace labels assigned to one immutable version."""

    labels: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=8)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        """Keep non-production labels bounded, unique, and SDK-compatible."""
        if len(set(values)) != len(values):
            raise ValueError("labels must be unique")
        for value in values:
            if value in {"latest", "production"} or not _LABEL_PATTERN.fullmatch(value):
                raise ValueError("labels must be valid identifiers and cannot be 'latest' or 'production'")
        return values


class PromptProductionPromotionRequest(BaseModel):
    """Explicit request to assign the runtime ``production`` label to one version."""

    name: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[int, Field(ge=1)]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Apply the same prompt-name boundary as all other prompt operations."""
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value


class PromptPreviewRequest(BaseModel):
    """Request to compile a fetched prompt locally without executing a model."""

    name: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[int | None, Field(ge=0)] = None
    label: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    values: dict[str, Annotated[str, Field(max_length=5_000)]] = Field(
        default_factory=dict,
        max_length=50,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Apply the same no-path-separator prompt-name boundary as mutations."""
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        """Validate an optional bounded label selector."""
        if value is not None and (value == "latest" or not _LABEL_PATTERN.fullmatch(value)):
            raise ValueError("label must be a valid identifier and cannot be 'latest'")
        return value

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: dict[str, str]) -> dict[str, str]:
        """Restrict substitutions to simple strings and non-path-like variable names."""
        if any(not _VARIABLE_PATTERN.fullmatch(key) for key in values):
            raise ValueError("preview variable names must be valid identifiers")
        return values

    @model_validator(mode="after")
    def require_one_selector(self) -> "PromptPreviewRequest":
        """Require exactly one explicit prompt version or label for a preview."""
        if (self.version is None) == (self.label is None):
            raise ValueError("provide exactly one of version or label")
        return self


class PromptVersionResponse(BaseModel):
    """Safe prompt-version representation returned by bounded operations."""

    name: str
    type: PromptType
    version: int
    labels: list[str] = Field(default_factory=list)
    prompt: str | list[PromptChatMessage]


class PromptMetadataResponse(BaseModel):
    """Prompt metadata without template content for list responses."""

    name: str
    type: PromptType
    versions: list[int] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    last_updated_at: str | None = None


class PromptListResponse(BaseModel):
    """Paginated list of safe prompt metadata."""

    items: list[PromptMetadataResponse]
    page: int
    limit: int


class PromptPreviewResponse(PromptVersionResponse):
    """Locally compiled output and unresolved variables, without model execution."""

    compiled_prompt: str | list[PromptChatMessage]
    unresolved_variables: list[str] = Field(default_factory=list)
