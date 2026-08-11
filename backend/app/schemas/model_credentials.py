"""提供模型凭据相关后端功能。"""

from pydantic import BaseModel, Field, model_validator


class ModelCredentialPutRequest(BaseModel):
    """定义模型凭据写入请求相关后端数据结构或服务组件。"""

    model_name: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=16_384)
    source_model: str | None = Field(default=None, max_length=256)
    legacy_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_write_source(self):
        """校验写入来源相关后端逻辑。"""

        if not (self.api_key and self.api_key.strip()) and not (
            self.source_model and self.source_model.strip()
        ):
            raise ValueError("必须提供 API Key 或原模型名称")
        return self


class ModelCredentialLookup(BaseModel):
    """定义模型凭据查询相关后端数据结构或服务组件。"""

    model_name: str = Field(min_length=1, max_length=256)
    legacy_id: str | None = Field(default=None, max_length=128)


class ModelCredentialStatusRequest(BaseModel):
    """定义模型凭据状态请求相关后端数据结构或服务组件。"""

    models: list[ModelCredentialLookup] = Field(default_factory=list, max_length=200)


class ModelCredentialStatus(BaseModel):
    """定义模型凭据状态相关后端数据结构或服务组件。"""

    model_name: str
    stored: bool
    expires_at: str | None = None
