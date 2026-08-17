"""提供简历项目改写相关后端功能。"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.schemas.resume.project_rewrite_schemas import (
    ProjectRewriteDetailResponse,
    ProjectRewriteHistoryResponse,
    ProjectRewriteRequest,
    ProjectRewriteResponse,
)
from ai.workflows.resume.project_rewrite import (
    ProjectRewriteBadRequest,
    ProjectRewriteNotFound,
    project_rewrite_use_cases,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/project-rewrite", response_model=ProjectRewriteResponse)
async def project_rewrite_endpoint(
    request: ProjectRewriteRequest,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """对简历中的项目经历进行 AI 改写。

    Args:
        request: 项目改写请求体（项目描述与改写要求）。
        user_id: 当前登录用户 ID。
    """
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """列出当前用户的项目改写记录，可按改写模式过滤。

    Args:
        rewrite_mode: 改写模式过滤，为空则全部。
        limit: 返回条数上限，默认 20。
        user_id: 当前登录用户 ID。
    """
    return await project_rewrite_use_cases.list_results(
        user_id=user_id,
        rewrite_mode=rewrite_mode,
        limit=limit,
    )


@router.get("/project-rewrite/{rewrite_id}", response_model=ProjectRewriteDetailResponse)
async def get_project_rewrite_result(
    rewrite_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """获取单条项目改写结果的详情。

    Args:
        rewrite_id: 项目改写记录 ID。
        user_id: 当前登录用户 ID。
    """
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """删除一条项目改写记录。

    Args:
        rewrite_id: 项目改写记录 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await project_rewrite_use_cases.delete_result(rewrite_id=rewrite_id, user_id=user_id)
    except ProjectRewriteNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除项目重写记录失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
