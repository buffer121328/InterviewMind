"""Project rewrite routes."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.schemas.project_rewrite_schemas import (
    ProjectRewriteDetailResponse,
    ProjectRewriteHistoryResponse,
    ProjectRewriteRequest,
    ProjectRewriteResponse,
)
from app.workflows.resume.project_rewrite import (
    ProjectRewriteBadRequest,
    ProjectRewriteNotFound,
    project_rewrite_use_cases,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/project-rewrite", response_model=ProjectRewriteResponse)
async def project_rewrite_endpoint(
    request: ProjectRewriteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Rewrite project experience with a selected rewrite mode."""
    try:
        return await project_rewrite_use_cases.rewrite(request=request, user_id=user_id)
    except ProjectRewriteBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("项目重写失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重写失败: {exc}") from exc


@router.get("/project-rewrite", response_model=ProjectRewriteHistoryResponse)
async def list_project_rewrite_results(
    rewrite_mode: Optional[str] = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
):
    """List project rewrite history."""
    return await project_rewrite_use_cases.list_results(
        user_id=user_id,
        rewrite_mode=rewrite_mode,
        limit=limit,
    )


@router.get("/project-rewrite/{rewrite_id}", response_model=ProjectRewriteDetailResponse)
async def get_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Get one project rewrite result."""
    try:
        return await project_rewrite_use_cases.get_result(rewrite_id=rewrite_id, user_id=user_id)
    except ProjectRewriteNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取项目重写详情失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/project-rewrite/{rewrite_id}")
async def delete_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Delete one project rewrite record."""
    try:
        return await project_rewrite_use_cases.delete_result(rewrite_id=rewrite_id, user_id=user_id)
    except ProjectRewriteNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除项目重写记录失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
