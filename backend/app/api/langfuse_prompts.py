"""HTTP endpoints for bounded, database-backed Prompt Management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from ai.workflows.prompt_management import DatabasePromptManagementService
from ai.workflows.evaluation import EvaluationUseCaseError, evaluation_use_cases
from app.api.deps import get_current_user_id
from app.schemas.langfuse_prompts import (
    PromptCreateRequest,
    PromptLabelUpdateRequest,
    PromptListResponse,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptProductionPromotionRequest,
    PromptVersionResponse,
)


router = APIRouter(prefix="/api/langfuse/prompts", tags=["Prompt Management"])


def _service() -> DatabasePromptManagementService:
    """Create the stateless database prompt service used by API and runtime boundaries."""
    return DatabasePromptManagementService()


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    user_id: str = Depends(get_current_user_id),
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    label: Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] = None,
) -> PromptListResponse:
    """List prompt metadata; user identity uses the existing API dependency boundary."""
    if label == "latest":
        raise HTTPException(status_code=422, detail="label cannot be 'latest'")
    items = await _service().list_prompts(user_id=user_id, page=page, limit=limit)
    return PromptListResponse(items=items, page=page, limit=limit)


@router.get("/selected", response_model=PromptVersionResponse)
async def fetch_prompt(
    name: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    user_id: str = Depends(get_current_user_id),
    version: Annotated[int | None, Query(ge=0)] = None,
    label: Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] = None,
) -> PromptVersionResponse:
    """Fetch a name selected by a query value, never by an unsafe catch-all path."""
    if (version is None) == (label is None):
        raise HTTPException(status_code=422, detail="provide exactly one of version or label")
    if label == "latest":
        raise HTTPException(status_code=422, detail="label cannot be 'latest'")
    result = await _service().fetch_prompt(user_id=user_id, name=name, version=version, label=label)
    if not result:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return result


@router.post("", response_model=PromptVersionResponse, status_code=201)
async def create_prompt_version(
    request: PromptCreateRequest,
    user_id: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """Create a validated immutable prompt version for the single-user workspace."""
    return await _service().create_version(user_id=user_id, request=request)


@router.put("/labels", response_model=PromptVersionResponse)
async def update_prompt_labels(
    request: PromptLabelUpdateRequest,
    name: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    version: Annotated[int, Query(ge=1)],
    user_id: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """Replace non-production labels for one selected immutable prompt version."""
    result = await _service().update_labels(user_id=user_id, name=name, version=version, labels=request.labels)
    if not result:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return result


@router.put("/production", response_model=PromptVersionResponse)
async def promote_prompt_to_production(
    request: PromptProductionPromotionRequest,
    user_id: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """Assign production only after the configured evaluation release gate allows it."""
    try:
        await evaluation_use_cases.validate_prompt_promotion(
            user_id=user_id,
            prompt_name=request.name,
            prompt_version=str(request.version),
            run_id=request.evaluation_run_id,
        )
    except EvaluationUseCaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    result = await _service().update_labels(user_id=user_id, name=request.name, version=request.version, labels=[], production=True)
    if not result:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return result


@router.post("/preview", response_model=PromptPreviewResponse)
async def preview_prompt(
    request: PromptPreviewRequest,
    user_id: str = Depends(get_current_user_id),
) -> PromptPreviewResponse:
    """Locally preview substitutions for one selected prompt without model execution."""
    result = await _service().preview(user_id=user_id, name=request.name, version=request.version, label=request.label, values=request.values)
    if not result:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return result
