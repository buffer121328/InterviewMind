"""Schemas for the minimal local model-name to API-key Redis store."""

from pydantic import BaseModel, Field, model_validator


class ModelCredentialPutRequest(BaseModel):
    """Save a new API key or move an existing model-name key without exposing it."""

    model_name: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=16_384)
    source_model: str | None = Field(default=None, max_length=256)
    legacy_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_write_source(self):
        """Require either a newly entered API key or an existing source model."""

        if not (self.api_key and self.api_key.strip()) and not (
            self.source_model and self.source_model.strip()
        ):
            raise ValueError("必须提供 API Key 或原模型名称")
        return self


class ModelCredentialLookup(BaseModel):
    """Identify one technical model name and its previous UI UUID for migration."""

    model_name: str = Field(min_length=1, max_length=256)
    legacy_id: str | None = Field(default=None, max_length=128)


class ModelCredentialStatusRequest(BaseModel):
    """Request API-key availability for locally configured technical model names."""

    models: list[ModelCredentialLookup] = Field(default_factory=list, max_length=200)


class ModelCredentialStatus(BaseModel):
    """Expose API-key availability without returning the secret."""

    model_name: str
    stored: bool
    expires_at: str | None = None
