"""HTTP endpoints for optional, bounded Langfuse Prompt Management."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ai.workflows.langfuse_prompt_management import (
    LangfusePromptManagementService,
    PromptManagementRemoteError,
    PromptManagementUnavailable,
)
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


router = APIRouter(prefix="/api/langfuse/prompts", tags=["Langfuse Prompt Management"])


def _service() -> LangfusePromptManagementService:
    """Create the small stateless service that owns bounded SDK access."""
    return LangfusePromptManagementService()


def _raise_service_error(error: Exception) -> NoReturn:
    """Convert service failures to redacted, stable API error responses."""
    if isinstance(error, PromptManagementUnavailable):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "PromptManagementUnavailable",
                "message": "Langfuse prompt management is not enabled or configured",
            },
        ) from error
    raise HTTPException(
        status_code=502,
        detail={"error": "PromptManagementFailed", "message": "Langfuse prompt management request failed"},
    ) from error


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    _: str = Depends(get_current_user_id),
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    label: Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] = None,
) -> PromptListResponse:
    """List prompt metadata; user identity uses the existing API dependency boundary."""
    if label == "latest":
        raise HTTPException(status_code=422, detail="label cannot be 'latest'")
    try:
        result = await run_in_threadpool(_service().list_prompts, page=page, limit=limit, label=label)
        return PromptListResponse(items=result.items, page=result.page, limit=result.limit)
    except (PromptManagementUnavailable, PromptManagementRemoteError) as error:
        _raise_service_error(error)


@router.get("/selected", response_model=PromptVersionResponse)
async def fetch_prompt(
    name: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    _: str = Depends(get_current_user_id),
    version: Annotated[int | None, Query(ge=1)] = None,
    label: Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] = None,
) -> PromptVersionResponse:
    """Fetch a name selected by a query value, never by an unsafe catch-all path."""
    if (version is None) == (label is None):
        raise HTTPException(status_code=422, detail="provide exactly one of version or label")
    if label == "latest":
        raise HTTPException(status_code=422, detail="label cannot be 'latest'")
    try:
        return await run_in_threadpool(_service().fetch_prompt, name=name, version=version, label=label)
    except (PromptManagementUnavailable, PromptManagementRemoteError) as error:
        _raise_service_error(error)


@router.post("", response_model=PromptVersionResponse, status_code=201)
async def create_prompt_version(
    request: PromptCreateRequest,
    _: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """Create a validated immutable prompt version for the single-user workspace."""
    try:
        return await run_in_threadpool(_service().create_version, request)
    except (PromptManagementUnavailable, PromptManagementRemoteError) as error:
        _raise_service_error(error)


@router.put("/labels", response_model=PromptVersionResponse)
async def update_prompt_labels(
    request: PromptLabelUpdateRequest,
    name: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    version: Annotated[int, Query(ge=1)],
    _: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """Replace non-production labels for one selected immutable prompt version."""
    try:
        return await run_in_threadpool(
            _service().update_labels, name=name, version=version, labels=request.labels
        )
    except (PromptManagementUnavailable, PromptManagementRemoteError) as error:
        _raise_service_error(error)


@router.put("/production", response_model=PromptVersionResponse)
async def promote_prompt_to_production(
    request: PromptProductionPromotionRequest,
    _: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """Assign the runtime production label through an explicit single-user action."""
    try:
        return await run_in_threadpool(
            _service().update_labels, name=request.name, version=request.version, labels=["production"]
        )
    except (PromptManagementUnavailable, PromptManagementRemoteError) as error:
        _raise_service_error(error)


@router.post("/preview", response_model=PromptPreviewResponse)
async def preview_prompt(
    request: PromptPreviewRequest,
    _: str = Depends(get_current_user_id),
) -> PromptPreviewResponse:
    """Locally preview substitutions for one selected prompt without model execution."""
    try:
        return await run_in_threadpool(
            _service().preview,
            name=request.name,
            version=request.version,
            label=request.label,
            values=request.values,
        )
    except (PromptManagementUnavailable, PromptManagementRemoteError) as error:
        _raise_service_error(error)
