"""Schemas for encrypted model credential persistence."""

from pydantic import BaseModel, Field


class ModelCredentialPutRequest(BaseModel):
    """Accept one model API key for encrypted Redis storage."""

    api_key: str = Field(min_length=1, max_length=16_384)


class ModelCredentialStatusRequest(BaseModel):
    """Request credential availability for locally known model IDs."""

    model_ids: list[str] = Field(default_factory=list, max_length=200)


class ModelCredentialStatus(BaseModel):
    """Expose credential metadata without ever returning the secret."""

    model_id: str
    stored: bool
    expires_at: str | None = None
