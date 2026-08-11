"""提供Langfuse提示词相关后端功能。"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PromptType = Literal["text", "chat"]
_PROMPT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class PromptChatMessage(BaseModel):
    """定义提示词聊天消息相关后端数据结构或服务组件。"""

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: Annotated[str, Field(min_length=1, max_length=20_000)]


class PromptCreateRequest(BaseModel):
    """定义提示词请求相关后端数据结构或服务组件。"""

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
        """校验名称相关后端逻辑。"""
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        """校验标签相关后端逻辑。"""
        if len(set(values)) != len(values):
            raise ValueError("labels must be unique")
        for value in values:
            if value in {"latest", "production"} or not _LABEL_PATTERN.fullmatch(value):
                raise ValueError("labels must be valid identifiers and cannot be 'latest' or 'production'")
        return values

    @model_validator(mode="after")
    def validate_prompt_for_type(self) -> "PromptCreateRequest":
        """校验提示词类型相关后端逻辑。"""
        if self.type == "text":
            if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt) > 40_000:
                raise ValueError("text prompts must be non-empty strings of at most 40000 characters")
        elif not isinstance(self.prompt, list) or not self.prompt or len(self.prompt) > 50:
            raise ValueError("chat prompts must contain between 1 and 50 messages")
        return self


class PromptLabelUpdateRequest(BaseModel):
    """定义提示词标签请求相关后端数据结构或服务组件。"""

    labels: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=8)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        """校验标签相关后端逻辑。"""
        if len(set(values)) != len(values):
            raise ValueError("labels must be unique")
        for value in values:
            if value in {"latest", "production"} or not _LABEL_PATTERN.fullmatch(value):
                raise ValueError("labels must be valid identifiers and cannot be 'latest' or 'production'")
        return values


class PromptProductionPromotionRequest(BaseModel):
    """定义提示词生产提升请求相关后端数据结构或服务组件。"""

    name: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[int, Field(ge=1)]
    evaluation_run_id: Annotated[str | None, Field(min_length=1, max_length=160)] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验名称相关后端逻辑。"""
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value


class PromptPreviewRequest(BaseModel):
    """定义提示词预览请求相关后端数据结构或服务组件。"""

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
        """校验名称相关后端逻辑。"""
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        """校验标签相关后端逻辑。"""
        if value is not None and (value == "latest" or not _LABEL_PATTERN.fullmatch(value)):
            raise ValueError("label must be a valid identifier and cannot be 'latest'")
        return value

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: dict[str, str]) -> dict[str, str]:
        """校验值相关后端逻辑。"""
        if any(not _VARIABLE_PATTERN.fullmatch(key) for key in values):
            raise ValueError("preview variable names must be valid identifiers")
        return values

    @model_validator(mode="after")
    def require_one_selector(self) -> "PromptPreviewRequest":
        """要求选择器相关后端逻辑。"""
        if (self.version is None) == (self.label is None):
            raise ValueError("provide exactly one of version or label")
        return self


class PromptVersionResponse(BaseModel):
    """定义提示词版本响应相关后端数据结构或服务组件。"""

    name: str
    display_name: str
    functional_group: str
    is_builtin: bool
    type: PromptType
    version: int
    labels: list[str] = Field(default_factory=list)
    prompt: str | list[PromptChatMessage]


class PromptMetadataResponse(BaseModel):
    """定义提示词元数据响应相关后端数据结构或服务组件。"""

    name: str
    display_name: str
    functional_group: str
    is_builtin: bool
    type: PromptType
    versions: list[int] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    last_updated_at: str | None = None


class PromptListResponse(BaseModel):
    """定义提示词列表响应相关后端数据结构或服务组件。"""

    items: list[PromptMetadataResponse]
    total: int = Field(ge=0)
    page: int
    limit: int


class PromptPreviewResponse(PromptVersionResponse):
    """定义提示词预览响应相关后端数据结构或服务组件。"""

    compiled_prompt: str | list[PromptChatMessage]
    unresolved_variables: list[str] = Field(default_factory=list)


class PromptBuiltinSyncResponse(BaseModel):
    """定义提示词内置同步响应相关后端数据结构或服务组件。"""

    discovered: int = Field(ge=0)
    created: int = Field(ge=0)
    skipped: int = Field(ge=0)
    created_names: list[str] = Field(default_factory=list)
