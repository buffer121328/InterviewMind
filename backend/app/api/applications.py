"""
投递追踪 API 路由
提供岗位投递记录及事件流水的增删改查接口
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

from fastapi import APIRouter, Header, HTTPException, Query

from ai.workflows.applications.use_cases import (
    ApplicationDeleteFailed,
    ApplicationNotFound,
    ApplicationUseCaseError,
    application_use_cases,
)
from app.schemas.jobs.job_application import (
    ApplicationCreateRequest,
    ApplicationDetailResponse,
    ApplicationListResponse,
    ApplicationResumeLinkRequest,
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
    """执行路由传入的 use-case，并将预期业务错误映射为统一的 HTTP 响应。

    Args:
        action: 待执行的异步 use-case；异常由本函数统一转换，动作本身的副作用仍由 use-case 负责。
        error_message: 对外或日志使用的错误语义；必须保持脱敏，不包含凭据和完整输入。
    """
    try:
        return await action()
    except ApplicationUseCaseError as exc:
        # ① 按错误类型映射稳定状态码，未知类型兜底为 400
        status_code = _ERROR_STATUS.get(type(exc), 400)
        raise HTTPException(
            status_code=status_code,
            detail={"error": exc.error, "message": exc.message},
        ) from exc
    except HTTPException:
        # ② 已是 HTTP 异常则直接透传，避免二次包装
        raise
    except Exception as exc:
        # ③ 未知异常记录日志并返回 500，不向外暴露内部细节
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
    """创建 application，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

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
    """按 owner、筛选条件和分页参数读取 applications；仅返回当前调用方有权查看的持久化结果。

    Args:
        status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
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
    """读取 application，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

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
    """在 owner 校验下更新 application；只写入允许变更的字段，避免绕过状态机或审批约束。

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


@router.put("/{application_id}/resume", response_model=ApplicationDetailResponse)
async def set_application_resume(
    application_id: int,
    request: ApplicationResumeLinkRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """在 owner 校验下为投递记录设置关联简历链接。

    Args:
        application_id: 投递记录标识。
        request: 简历链接设置请求体。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.set_application_resume(
            application_id=application_id,
            user_id=x_user_id,
            request=request,
        ),
        "更新关联简历失败",
    )


@router.delete("/{application_id}")
async def delete_application(application_id: int, x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    """在 owner 校验下删除 application；删除失败或资源不可见时保持幂等的业务错误语义。

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
    """在 owner 校验通过后追加投递事件，并沿用用例层的持久化与审计边界；不直接执行外部投递。

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
    """按 owner、筛选条件和分页参数读取 application events；仅返回当前调用方有权查看的持久化结果。

    Args:
        application_id: 投递记录标识。
        x_user_id: x user 标识。
    """
    return await _call_use_case(
        lambda: application_use_cases.list_application_events(application_id=application_id, user_id=x_user_id),
        "获取投递事件列表失败",
    )
