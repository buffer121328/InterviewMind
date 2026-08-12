"""提供Langfuse提示词相关后端功能。"""

import asyncio
from collections.abc import Callable
from typing import Annotated
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from ai.workflows.prompts.management import (
    LangfusePromptManagementService,
    PromptManagementRemoteError,
    PromptManagementUnavailable,
)
from ai.workflows.evaluation import EvaluationUseCaseError, evaluation_use_cases
from app.api.deps import get_current_user_id
from app.schemas.langfuse_prompts import (
    PromptBuiltinSyncResponse,
    PromptCreateRequest,
    PromptLabelUpdateRequest,
    PromptListResponse,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptProductionPromotionRequest,
    PromptVersionResponse,
)


router = APIRouter(prefix="/api/langfuse/prompts", tags=["Prompt Management"])
T = TypeVar("T")


def _service() -> LangfusePromptManagementService:
    """处理服务相关后端逻辑。"""
    return LangfusePromptManagementService()


async def _remote(action: Callable[[], T]) -> T:
    """处理Langfuse提示词相关后端逻辑。"""
    try:
        return await asyncio.to_thread(action)
    except PromptManagementUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Langfuse Prompt Management 未启用或凭据不完整",
        ) from exc
    except PromptManagementRemoteError as exc:
        raise HTTPException(
            status_code=502,
            detail="Langfuse Prompt Management 暂时不可访问",
        ) from exc


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    _user_id: str = Depends(get_current_user_id),
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    label: Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] = None,
) -> PromptListResponse:
    """列出提示词相关后端逻辑。"""
    if label == "latest":
        raise HTTPException(status_code=422, detail="label cannot be 'latest'")
    result = await _remote(lambda: _service().list_prompts(page=page, limit=limit, label=label))
    return PromptListResponse(
        items=result.items,
        total=result.total,
        page=result.page,
        limit=result.limit,
    )


@router.get("/selected", response_model=PromptVersionResponse)
async def fetch_prompt(
    name: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    _user_id: str = Depends(get_current_user_id),
    version: Annotated[int | None, Query(ge=0)] = None,
    label: Annotated[str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] = None,
) -> PromptVersionResponse:
    """获取提示词相关后端逻辑。"""
    if (version is None) == (label is None):
        raise HTTPException(status_code=422, detail="provide exactly one of version or label")
    if label == "latest":
        raise HTTPException(status_code=422, detail="label cannot be 'latest'")
    return await _remote(
        lambda: _service().fetch_prompt(name=name, version=version, label=label)
    )


@router.post("", response_model=PromptVersionResponse, status_code=201)
async def create_prompt_version(
    request: PromptCreateRequest,
    _user_id: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """创建提示词版本相关后端逻辑。"""
    return await _remote(lambda: _service().create_version(request))


@router.put("/labels", response_model=PromptVersionResponse)
async def update_prompt_labels(
    request: PromptLabelUpdateRequest,
    name: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    version: Annotated[int, Query(ge=1)],
    _user_id: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """更新提示词标签相关后端逻辑。"""
    return await _remote(
        lambda: _service().update_labels(
            name=name,
            version=version,
            labels=request.labels,
        )
    )


@router.put("/production", response_model=PromptVersionResponse)
async def promote_prompt_to_production(
    request: PromptProductionPromotionRequest,
    user_id: str = Depends(get_current_user_id),
) -> PromptVersionResponse:
    """提升提示词生产相关后端逻辑。"""
    try:
        await evaluation_use_cases.validate_prompt_promotion(
            user_id=user_id,
            prompt_name=request.name,
            prompt_version=str(request.version),
            run_id=request.evaluation_run_id,
        )
    except EvaluationUseCaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return await _remote(
        lambda: _service().update_labels(
            name=request.name,
            version=request.version,
            labels=["production"],
        )
    )


@router.post("/sync-builtins", response_model=PromptBuiltinSyncResponse)
async def sync_builtin_prompts(
    _user_id: str = Depends(get_current_user_id),
) -> PromptBuiltinSyncResponse:
    """同步内置提示词相关后端逻辑。"""
    return await _remote(lambda: _service().sync_builtin_production_prompts())


@router.post("/preview", response_model=PromptPreviewResponse)
async def preview_prompt(
    request: PromptPreviewRequest,
    _user_id: str = Depends(get_current_user_id),
) -> PromptPreviewResponse:
    """预览提示词相关后端逻辑。"""
    return await _remote(
        lambda: _service().preview(
            name=request.name,
            version=request.version,
            label=request.label,
            values=request.values,
        )
    )
