"""
投递追踪 API 路由
提供岗位投递记录及事件流水的增删改查接口
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

from fastapi import APIRouter, Header, HTTPException, Query

from app.workflows.applications import (
    ApplicationDeleteFailed,
    ApplicationNotFound,
    ApplicationUseCaseError,
    application_use_cases,
)
from app.schemas.job_application import (
    ApplicationCreateRequest,
    ApplicationDetailResponse,
    ApplicationListResponse,
    ApplicationUpdateRequest,
    EventCreateRequest,
    EventListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["投递追踪"])

T = TypeVar("T")

_ERROR_STATUS = {
    ApplicationNotFound: 404,
    ApplicationDeleteFailed: 500,
}


async def _call_use_case(action: Callable[[], Awaitable[T]], error_message: str) -> T:
    """异步执行 `_call_use_case` 相关逻辑。

    Args:
        action: 调用方传入的 `action` 参数。
        error_message: 调用方传入的 `error_message` 参数。
    """
    try:
        return await action()
    except ApplicationUseCaseError as exc:
        status_code = _ERROR_STATUS.get(type(exc), 400)
        raise HTTPException(
            status_code=status_code,
            detail={"error": exc.error, "message": exc.message},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("%s: %s", error_message, exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": error_message},
        ) from exc


@router.post("/", response_model=ApplicationDetailResponse)
async def create_application(
    request: ApplicationCreateRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """创建 `application`。

    Args:
        request: 请求对象。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.create_application(user_id=x_user_id, request=request),
        "创建投递记录失败",
    )


@router.get("/", response_model=ApplicationListResponse)
async def list_applications(
    status: Optional[str] = Query(None, description="筛选状态"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """列出 `applications`。

    Args:
        status: 调用方传入的 `status` 参数。
        limit: 返回数量上限。
        offset: 分页偏移量。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.list_applications(
            user_id=x_user_id,
            status=status,
            limit=limit,
            offset=offset,
        ),
        "获取投递列表失败",
    )


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
async def get_application(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    """获取 `application`。

    Args:
        application_id: 投递记录标识。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.get_application(application_id=application_id, user_id=x_user_id),
        "获取投递详情失败",
    )


# patch 是部分更新，put 是完整替换
@router.patch("/{application_id}", response_model=ApplicationDetailResponse)
async def update_application(
    application_id: int,
    request: ApplicationUpdateRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """更新 `application`。

    Args:
        application_id: 投递记录标识。
        request: 请求对象。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.update_application(
            application_id=application_id,
            user_id=x_user_id,
            request=request,
        ),
        "更新投递记录失败",
    )


@router.delete("/{application_id}")
async def delete_application(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    """删除 `application`。

    Args:
        application_id: 投递记录标识。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.delete_application(application_id=application_id, user_id=x_user_id),
        "删除投递记录失败",
    )


@router.post("/{application_id}/events")
async def add_event_to_application(
    application_id: int,
    request: EventCreateRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """新增 `event to application`。

    Args:
        application_id: 投递记录标识。
        request: 请求对象。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.add_event_to_application(
            application_id=application_id,
            user_id=x_user_id,
            request=request,
        ),
        "添加投递事件失败",
    )


@router.get("/{application_id}/events", response_model=EventListResponse)
async def list_application_events(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    """列出 `application events`。

    Args:
        application_id: 投递记录标识。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.list_application_events(application_id=application_id, user_id=x_user_id),
        "获取投递事件列表失败",
    )
