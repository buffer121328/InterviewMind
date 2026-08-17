"""提供简历材料相关后端功能。"""

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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """创建一条简历材料（如经历、技能、项目等）。

    Args:
        request: 材料创建请求体（类型与内容）。
        user_id: 当前登录用户 ID。
    """
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """从已有简历中提取并导入材料。

    Args:
        request: 导入请求体（简历来源信息）。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_material_use_cases.import_materials_from_resume(request=request, user_id=user_id)
    except ResumeMaterialBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeMaterialImportFormatError as exc:
        # AI 提取结果格式非法，属服务端处理问题 → 500
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """分页列出当前用户的简历材料，支持类型与审核状态过滤。

    Args:
        material_type: 材料类型过滤，为空则全部。
        is_verified: 是否只取已核实材料，为空则全部。
        limit: 分页大小，默认 100。
        offset: 分页偏移量，默认 0。
        user_id: 当前登录用户 ID。
    """
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """获取单条简历材料的详情。

    Args:
        material_id: 材料 ID。
        user_id: 当前登录用户 ID。
    """
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """更新一条简历材料。

    Args:
        material_id: 材料 ID。
        request: 更新请求体（要修改的字段）。
        user_id: 当前登录用户 ID。
    """
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
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """删除一条简历材料。

    Args:
        material_id: 材料 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_material_use_cases.delete_material(material_id=material_id, user_id=user_id)
    except ResumeMaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除素材失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
