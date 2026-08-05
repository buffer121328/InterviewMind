"""
API 配置相关端点
用于验证用户的 API 配置是否有效
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.schemas.model_credentials import ModelCredentialPutRequest, ModelCredentialStatusRequest
from app.schemas.schemas import ApiConfigValidateRequest
from app.security.model_credentials import (
    InvalidModelCredentialId,
    ModelCredentialError,
    ModelCredentialStoreUnavailable,
    get_model_credential_store,
)
from ai.workflows.config import api_config_use_cases
from ai.workflows.model_credentials import ModelCredentialUseCases

router = APIRouter(prefix="/api/config", tags=["配置"])


@router.post("/validate")
async def validate_api_config(request: ApiConfigValidateRequest):
    """验证用户的 API 配置是否有效。"""
    return await api_config_use_cases.validate(request)


def _credential_use_cases() -> ModelCredentialUseCases:
    """Resolve credential use cases while keeping Redis construction out of route handlers."""

    return ModelCredentialUseCases(get_model_credential_store())


def _credential_error(exc: ModelCredentialError) -> HTTPException:
    """Map credential storage errors to non-sensitive HTTP responses."""

    status_code = 503 if isinstance(exc, ModelCredentialStoreUnavailable) else 400
    return HTTPException(status_code=status_code, detail=str(exc))


@router.put("/credentials")
async def put_model_credential(
    request: ModelCredentialPutRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Save one model-name to API-key Redis String."""

    try:
        return await _credential_use_cases().put(
            user_id,
            request.model_name,
            api_key=request.api_key,
            source_model=request.source_model,
            legacy_id=request.legacy_id,
        )
    except (InvalidModelCredentialId, ModelCredentialError) as exc:
        raise _credential_error(exc) from exc


@router.post("/credentials/status")
async def get_model_credential_statuses(
    request: ModelCredentialStatusRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Return local Redis availability without returning API keys."""

    try:
        return await _credential_use_cases().statuses(
            user_id,
            [(item.model_name, item.legacy_id) for item in request.models],
        )
    except (InvalidModelCredentialId, ModelCredentialError) as exc:
        raise _credential_error(exc) from exc


@router.delete("/credentials")
async def delete_model_credential(
    model_name: str,
    legacy_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
):
    """Delete one model-name API-key String from Redis."""

    try:
        return await _credential_use_cases().delete(
            user_id, model_name, legacy_id=legacy_id
        )
    except (InvalidModelCredentialId, ModelCredentialError) as exc:
        raise _credential_error(exc) from exc
