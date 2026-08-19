"""Langfuse 提示词（Prompt）管理相关的 HTTP 数据模型。"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PromptType = Literal["text", "chat"]  # 提示词类型：文本/聊天
PromptManagementTagCategory = Literal["业务领域", "工作职责", "处理阶段"]
_PROMPT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")  # 提示词名称：字母/数字开头，可含 . _ -，最长 128
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")  # 标签：字母/数字开头，可含 . _ -，最长 64
_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")  # 预览变量名：字母/下划线开头，可含数字与下划线，最长 64


class PromptChatMessage(BaseModel):
    """提示词中的一条聊天消息，role 限定 system/developer/user/assistant/tool。"""

    role: Literal["system", "developer", "user", "assistant", "tool"] = Field(description="消息角色")
    content: Annotated[str, Field(min_length=1, max_length=20_000)] = Field(description="消息内容")


class PromptCreateRequest(BaseModel):
    """创建提示词的请求体（名称/类型/正文/标签/提交信息）。"""

    name: Annotated[str, Field(min_length=1, max_length=128)] = Field(description="提示词名称")
    type: PromptType = Field(description="提示词类型：text/chat")
    prompt: str | list[PromptChatMessage] = Field(description="提示词正文：text 为字符串，chat 为消息列表")
    labels: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list,
        max_length=8,
        description="标签列表（最多 8 个）",
    )
    commit_message: Annotated[str | None, Field(max_length=500)] = Field(default=None, description="提交信息")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验提示词名称的字符集与长度。

        Args:
            value: 值。
        """
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        """校验标签唯一性、命名规则并禁止 latest/production。

        Args:
            values: 取值字典。
        """
        if len(set(values)) != len(values):
            raise ValueError("labels must be unique")
        for value in values:
            if value in {"latest", "production"} or not _LABEL_PATTERN.fullmatch(value):
                raise ValueError("labels must be valid identifiers and cannot be 'latest' or 'production'")
        return values

    @model_validator(mode="after")
    def validate_prompt_for_type(self) -> "PromptCreateRequest":
        """按 type 校验正文：text 非空字符串且≤40000 字符，chat 为 1-50 条消息。"""
        if self.type == "text":
            if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt) > 40_000:
                raise ValueError("text prompts must be non-empty strings of at most 40000 characters")
        elif not isinstance(self.prompt, list) or not self.prompt or len(self.prompt) > 50:
            raise ValueError("chat prompts must contain between 1 and 50 messages")
        return self


class PromptLabelUpdateRequest(BaseModel):
    """更新提示词标签集合的请求体。"""

    labels: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        max_length=8,
        description="新的标签集合（最多 8 个）",
    )

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: list[str]) -> list[str]:
        """校验标签唯一性、命名规则并禁止 latest/production。

        Args:
            values: 取值字典。
        """
        if len(set(values)) != len(values):
            raise ValueError("labels must be unique")
        for value in values:
            if value in {"latest", "production"} or not _LABEL_PATTERN.fullmatch(value):
                raise ValueError("labels must be valid identifiers and cannot be 'latest' or 'production'")
        return values


class PromptProductionPromotionRequest(BaseModel):
    """将指定版本提示词提升为 production 的请求体。"""

    name: Annotated[str, Field(min_length=1, max_length=128)] = Field(description="提示词名称")
    version: Annotated[int, Field(ge=1)] = Field(description="要提升的版本号（从 1 开始）")
    evaluation_run_id: Annotated[str | None, Field(min_length=1, max_length=160)] = Field(
        default=None,
        description="关联的评估运行 ID",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验提示词名称的字符集与长度。

        Args:
            value: 值。
        """
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value


class PromptPreviewRequest(BaseModel):
    """提示词预览请求，version 与 label 二选一。"""

    name: Annotated[str, Field(min_length=1, max_length=128)] = Field(description="提示词名称")
    version: Annotated[int | None, Field(ge=0)] = Field(default=None, description="要预览的版本号")
    label: Annotated[str | None, Field(min_length=1, max_length=64)] = Field(default=None, description="要预览的标签")
    values: dict[str, Annotated[str, Field(max_length=5_000)]] = Field(
        default_factory=dict,
        max_length=50,
        description="模板变量填充值（最多 50 个）",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验提示词名称的字符集与长度。

        Args:
            value: 值。
        """
        if not _PROMPT_NAME_PATTERN.fullmatch(value):
            raise ValueError("prompt name may contain only letters, digits, '.', '_', and '-'")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        """校验标签命名规则并禁止 latest。

        Args:
            value: 值。
        """
        if value is not None and (value == "latest" or not _LABEL_PATTERN.fullmatch(value)):
            raise ValueError("label must be a valid identifier and cannot be 'latest'")
        return value

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: dict[str, str]) -> dict[str, str]:
        """校验预览变量名必须为合法标识符。

        Args:
            values: 取值字典。
        """
        if any(not _VARIABLE_PATTERN.fullmatch(key) for key in values):
            raise ValueError("preview variable names must be valid identifiers")
        return values

    @model_validator(mode="after")
    def require_one_selector(self) -> "PromptPreviewRequest":
        """要求 version 与 label 恰好提供一个。"""
        if (self.version is None) == (self.label is None):
            raise ValueError("provide exactly one of version or label")
        return self


class PromptManagementTagResponse(BaseModel):
    """提示词管理中由后端注册表定义的功能标签。"""

    key: str = Field(description="稳定筛选标识")
    label: str = Field(description="中文展示名称")
    category: PromptManagementTagCategory = Field(description="标签分类")


class PromptVersionResponse(BaseModel):
    """提示词某个版本的完整响应。"""

    name: str = Field(description="提示词名称")
    display_name: str = Field(description="展示名称")
    functional_group: str = Field(description="功能分组")
    is_builtin: bool = Field(description="是否为内置提示词")
    management_tags: list[PromptManagementTagResponse] = Field(default_factory=list, description="后端功能标签")
    type: PromptType = Field(description="提示词类型：text/chat")
    version: int = Field(description="版本号")
    labels: list[str] = Field(default_factory=list, description="标签列表")
    prompt: str | list[PromptChatMessage] = Field(description="提示词正文")


class PromptMetadataResponse(BaseModel):
    """提示词元数据响应（不含正文）。"""

    name: str = Field(description="提示词名称")
    display_name: str = Field(description="展示名称")
    functional_group: str = Field(description="功能分组")
    is_builtin: bool = Field(description="是否为内置提示词")
    management_tags: list[PromptManagementTagResponse] = Field(default_factory=list, description="后端功能标签")
    type: PromptType = Field(description="提示词类型：text/chat")
    versions: list[int] = Field(default_factory=list, description="已有版本号列表")
    labels: list[str] = Field(default_factory=list, description="标签列表")
    last_updated_at: str | None = Field(default=None, description="最近更新时间")


class PromptListResponse(BaseModel):
    """提示词列表分页响应。"""

    items: list[PromptMetadataResponse] = Field(description="提示词元数据列表")
    total: int = Field(ge=0, description="总数量")
    page: int = Field(description="当前页码")
    limit: int = Field(description="每页条数")
    available_management_tags: list[PromptManagementTagResponse] = Field(
        default_factory=list,
        description="当前可管理提示词的完整功能标签集合",
    )


class PromptPreviewResponse(PromptVersionResponse):
    """提示词预览响应（含编译结果）。"""

    compiled_prompt: str | list[PromptChatMessage] = Field(description="编译后的提示词正文")
    unresolved_variables: list[str] = Field(default_factory=list, description="未填充的变量名列表")


class PromptBuiltinSyncResponse(BaseModel):
    """内置提示词同步结果。"""

    discovered: int = Field(ge=0, description="发现的提示词数量")
    created: int = Field(ge=0, description="新创建的提示词数量")
    skipped: int = Field(ge=0, description="跳过的提示词数量")
    created_names: list[str] = Field(default_factory=list, description="新创建的提示词名称列表")
