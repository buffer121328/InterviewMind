"""Candidate material library routes."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from ai.workflows.resume.materials import (
    ResumeMaterialBadRequest,
    ResumeMaterialImportFormatError,
    ResumeMaterialNotFound,
    resume_material_use_cases,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/materials")
async def create_material(
    request: dict,
    user_id: str = Depends(get_current_user_id),
):
    """Create a candidate material entry."""
    try:
        return await resume_material_use_cases.create_material(request=request, user_id=user_id)
    except ResumeMaterialBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("创建素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/materials/import")
async def import_materials_from_resume(
    request: dict,
    user_id: str = Depends(get_current_user_id),
):
    """Import candidate materials from resume content."""
    try:
        return await resume_material_use_cases.import_materials_from_resume(request=request, user_id=user_id)
    except ResumeMaterialBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeMaterialImportFormatError as exc:
        logger.error("AI 提取结果解析失败: %s", exc)
        raise HTTPException(status_code=500, detail=exc.message) from exc
    except Exception as exc:
        logger.error("导入素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/materials")
async def list_materials(
    material_type: Optional[str] = None,
    is_verified: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    """List candidate materials."""
    return await resume_material_use_cases.list_materials(
        user_id=user_id,
        material_type=material_type,
        is_verified=is_verified,
        limit=limit,
        offset=offset,
    )


@router.get("/materials/{material_id}")
async def get_material(
    material_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Get one candidate material."""
    try:
        return await resume_material_use_cases.get_material(material_id=material_id, user_id=user_id)
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/materials/{material_id}")
async def update_material(
    material_id: int,
    request: dict,
    user_id: str = Depends(get_current_user_id),
):
    """Update one candidate material."""
    try:
        return await resume_material_use_cases.update_material(
            material_id=material_id,
            request=request,
            user_id=user_id,
        )
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("更新素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Delete one candidate material."""
    try:
        return await resume_material_use_cases.delete_material(material_id=material_id, user_id=user_id)
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
