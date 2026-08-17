"""提供简历组装相关后端功能。"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from ai.workflows.resume.assembly import (
    ResumeAssemblyBadRequest,
    ResumeAssemblyNotFound,
    resume_assembly_use_cases,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/assemble")
async def assemble_resume(
    request: dict,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """组装简历并生成组装结果。

    Args:
        request: 组装请求体（简历内容与目标格式等）。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_assembly_use_cases.assemble_resume(request=request, user_id=user_id)
    except ResumeAssemblyBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("简历组装失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/assemble")
async def list_assembly_results(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """列出当前用户的简历组装结果。

    Args:
        limit: 返回结果条数上限，默认 20。
        user_id: 当前登录用户 ID。
    """
    return await resume_assembly_use_cases.list_assembly_results(user_id=user_id, limit=limit)


@router.get("/assemble/{result_id}")
async def get_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """获取单个简历组装结果的详情。

    Args:
        result_id: 组装结果 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_assembly_use_cases.get_assembly_result(result_id=result_id, user_id=user_id)
    except ResumeAssemblyNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取组装结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/assemble/{result_id}")
async def delete_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """删除指定的简历组装结果。

    Args:
        result_id: 组装结果 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_assembly_use_cases.delete_assembly_result(result_id=result_id, user_id=user_id)
    except ResumeAssemblyNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除组装结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
