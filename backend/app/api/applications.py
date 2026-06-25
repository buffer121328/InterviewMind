"""
投递追踪 API 路由
提供岗位投递记录及事件流水的增删改查接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from app.repositories.application.job_application_repo import job_application_repo
from app.repositories.application.application_event_repo import application_event_repo
from app.schemas.job_application import (
    ApplicationCreateRequest,
    ApplicationUpdateRequest,
    ApplicationListResponse,
    ApplicationDetailResponse,
    EventCreateRequest,
    EventListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["投递追踪"])


async def _get_application_or_404(application_id: int, x_user_id: Optional[str]) -> object:
    application = await job_application_repo.get_application(application_id, user_id=x_user_id or "default_user")
    if application is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "NotFound",
                "message": f"投递记录 {application_id} 不存在或无权访问",
            },
        )
    return application


@router.post("/", response_model=ApplicationDetailResponse)
async def create_application(
    request: ApplicationCreateRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    try:
        application = await job_application_repo.create_application(
            user_id=x_user_id or "default_user",
            request=request,
        )
        return ApplicationDetailResponse(success=True, application=application)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建投递记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "创建投递记录失败"})


@router.get("/", response_model=ApplicationListResponse)
async def list_applications(
    status: Optional[str] = Query(None, description="筛选状态"),
    limit: int = Query(50, description="返回数量限制"),
    offset: int = Query(0, description="偏移量"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    try:
        applications = await job_application_repo.list_applications(
            user_id=x_user_id or "default_user",
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await job_application_repo.get_application_count(user_id=x_user_id or "default_user", status=status)
        return ApplicationListResponse(success=True, applications=applications, total=total)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取投递列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "获取投递列表失败"})


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
async def get_application(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    try:
        application = await job_application_repo.get_application(application_id, user_id=x_user_id or "default_user")
        if application is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"投递记录 {application_id} 不存在或无权访问"},
            )
        return ApplicationDetailResponse(success=True, application=application)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取投递详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "获取投递详情失败"})

# patch是部份更新，put是完整替换
@router.patch("/{application_id}", response_model=ApplicationDetailResponse)
async def update_application(
    application_id: int,
    request: ApplicationUpdateRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    try:
        application = await job_application_repo.update_application(
            application_id=application_id,
            user_id=x_user_id or "default_user",
            request=request,
        )
        if application is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"投递记录 {application_id} 不存在或无权访问"},
            )
        return ApplicationDetailResponse(success=True, application=application)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新投递记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "更新投递记录失败"})


@router.delete("/{application_id}")
async def delete_application(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    try:
        await _get_application_or_404(application_id, x_user_id)
        success = await job_application_repo.delete_application(application_id=application_id, user_id=x_user_id or "default_user")
        if not success:
            raise HTTPException(
                status_code=500,
                detail={"error": "InternalServerError", "message": f"无法删除投递记录 {application_id}"},
            )
        return {"success": True, "message": f"投递记录 {application_id} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除投递记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "删除投递记录失败"})


@router.post("/{application_id}/events")
async def add_event_to_application(
    application_id: int,
    request: EventCreateRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    try:
        await _get_application_or_404(application_id, x_user_id)
        event_row = await application_event_repo.add_event(application_id=application_id, request=request)
        return {"success": True, "event": event_row}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加投递事件失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "添加投递事件失败"})


@router.get("/{application_id}/events", response_model=EventListResponse)
async def list_application_events(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    try:
        await _get_application_or_404(application_id, x_user_id)
        events = await application_event_repo.list_events(application_id=application_id)
        return EventListResponse(success=True, events=events)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取投递事件列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": "InternalServerError", "message": "获取投递事件列表失败"})
