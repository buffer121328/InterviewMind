"""模型凭据（API Key）写入、查询与状态检查的 HTTP 数据模型。"""

from pydantic import BaseModel, Field, model_validator


class ModelCredentialPutRequest(BaseModel):
    """写入模型凭据的请求，api_key 与 source_model 至少提供一个。"""

    model_name: str = Field(min_length=1, max_length=256, description="模型名称")
    api_key: str | None = Field(default=None, max_length=16_384, description="API Key")
    source_model: str | None = Field(default=None, max_length=256, description="原模型名称（凭据继承来源）")
    legacy_id: str | None = Field(default=None, max_length=128, description="旧版凭据 ID")

    @model_validator(mode="after")
    def validate_write_source(self):
        """api_key 与 source_model 至少提供一个，否则拒绝写入。"""

        if not (self.api_key and self.api_key.strip()) and not (
            self.source_model and self.source_model.strip()
        ):
            raise ValueError("必须提供 API Key 或原模型名称")
        return self


class ModelCredentialLookup(BaseModel):
    """按模型名或 legacy_id 查询凭据的请求。"""

    model_name: str = Field(min_length=1, max_length=256, description="模型名称")
    legacy_id: str | None = Field(default=None, max_length=128, description="旧版凭据 ID")


class ModelCredentialStatusRequest(BaseModel):
    """批量查询模型凭据状态的请求。"""

    models: list[ModelCredentialLookup] = Field(default_factory=list, max_length=200, description="要查询的模型列表")


class ModelCredentialStatus(BaseModel):
    """单个模型凭据的存储状态。"""

    model_name: str = Field(description="模型名称")
    stored: bool = Field(description="凭据是否已存储")
    expires_at: str | None = Field(default=None, description="凭据过期时间")
