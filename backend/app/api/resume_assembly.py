"""Resume assembly routes."""

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
    user_id: str = Depends(get_current_user_id),
):
    """Assemble a tailored resume from selected candidate materials."""
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
    user_id: str = Depends(get_current_user_id),
):
    """List resume assembly results."""
    return await resume_assembly_use_cases.list_assembly_results(user_id=user_id, limit=limit)


@router.get("/assemble/{result_id}")
async def get_assembly_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Get one resume assembly result."""
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
    user_id: str = Depends(get_current_user_id),
):
    """Delete one resume assembly result."""
    try:
        return await resume_assembly_use_cases.delete_assembly_result(result_id=result_id, user_id=user_id)
    except ResumeAssemblyNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除组装结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
