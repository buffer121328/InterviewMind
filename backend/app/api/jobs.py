"""
BOSS 岗位中心 API 路由
提供当前页岗位导入、资产管理、投递管理联动和现有标签页导航接口
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Literal, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from ai.workflows.jobs import (
    JobBadRequest,
    JobBrowserTabUnavailable,
    JobNotFound,
    JobsUseCaseError,
    jobs_use_cases,
)
from app.schemas.job_schemas import (
    BossTabCaptureRequest,
    BossTabCaptureResponse,
    BossTabStatusResponse,
    BossOpenJobRequest,
    GreetingUpdateRequest,
    JobExportApplicationRequest,
    JobDetailResponse,
    JobImportResponse,
    JobLibraryImportRequest,
    JobListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["岗位自动化"])

T = TypeVar("T")

_ERROR_STATUS = {
    JobBadRequest: 400,
    JobNotFound: 404,
    JobBrowserTabUnavailable: 409,
}


async def _call_use_case(action: Callable[[], Awaitable[T]], error_code: str, error_message: str) -> T:
    """执行路由传入的 use-case，并将预期业务错误映射为统一的 HTTP 响应。

    Args:
        action: 待执行的异步 use-case；异常由本函数统一转换，动作本身的副作用仍由 use-case 负责。
        error_code: 对外或日志使用的错误语义；必须保持脱敏，不包含凭据和完整输入。
        error_message: 对外或日志使用的错误语义；必须保持脱敏，不包含凭据和完整输入。
    """
    try:
        return await action()
    except JobsUseCaseError as exc:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(type(exc), 400),
            detail=exc.message if isinstance(exc, JobBadRequest) else {"error": exc.error, "message": exc.message},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[API] %s: error_type=%s",
            error_message,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": error_code, "message": error_message},
        ) from exc




@router.get("/browser-tab/status", response_model=BossTabStatusResponse)
async def get_boss_browser_tab_status(
    browser_channel: Optional[Literal["msedge", "chrome"]] = None,
    _user_id: str = Depends(get_current_user_id),
):
    """经宿主机服务检查 Edge/Chrome BOSS 标签页；Docker 主后端不直接访问 GUI。"""
    return await _call_use_case(
        lambda: jobs_use_cases.get_boss_browser_tab_status(browser_channel=browser_channel),
        "boss_browser_tab_failed",
        "检查现有 BOSS 标签页失败",
    )


@router.post("/browser-tab/search-and-capture", response_model=BossTabCaptureResponse)
async def search_and_capture_current_boss_tab(
    request: BossTabCaptureRequest,
    _user_id: str = Depends(get_current_user_id),
):
    """经宿主机服务复用现有登录标签页搜索和采集，不接收或导出浏览器凭据。"""
    return await _call_use_case(
        lambda: jobs_use_cases.search_and_capture_boss_tab(request=request),
        "boss_browser_tab_failed",
        "现有 BOSS 标签页搜索采集失败",
    )


@router.post("/import", response_model=JobImportResponse)
async def import_cards_to_library(
    request: JobLibraryImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """把用户确认的待入库卡片确定性写入岗位库，不调度模型或后台资产任务。"""
    return await _call_use_case(
        lambda: jobs_use_cases.import_cards_to_library(request=request, user_id=user_id),
        "job_import_failed",
        "岗位入库失败",
    )


@router.patch("/{job_id}/assets/greetings/{greeting_index}", response_model=JobDetailResponse)
async def update_job_greeting(
    job_id: int,
    greeting_index: int,
    request: GreetingUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """保存用户编辑后的打招呼方案。"""
    return await _call_use_case(
        lambda: jobs_use_cases.update_greeting(
            job_id=job_id, greeting_index=greeting_index, request=request, user_id=user_id
        ),
        "greeting_update_failed",
        "保存打招呼方案失败",
    )


@router.post("/{job_id}/export-application")
async def export_job_to_application(
    job_id: int,
    request: JobExportApplicationRequest,
    user_id: str = Depends(get_current_user_id),
):
    """一键加入投递管理，初始状态统一为待投递。"""
    return await _call_use_case(
        lambda: jobs_use_cases.export_to_application(job_id=job_id, request=request, user_id=user_id),
        "job_export_failed",
        "加入投递管理失败",
    )


@router.post("/{job_id}/browser-tab/open")
async def open_job_in_existing_boss_tab(
    job_id: int,
    request: BossOpenJobRequest,
    user_id: str = Depends(get_current_user_id),
):
    """在已有登录 BOSS 标签页打开岗位详情，不执行投递或发送。"""
    return await _call_use_case(
        lambda: jobs_use_cases.open_job_in_existing_tab(job_id=job_id, request=request, user_id=user_id),
        "open_job_failed",
        "打开 BOSS 岗位失败",
    )


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """查看已采集岗位详情。"""
    return await _call_use_case(
        lambda: jobs_use_cases.get_job(job_id=job_id, user_id=user_id),
        "get_job_failed",
        "获取岗位失败",
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    """岗位列表查询。"""
    return await _call_use_case(
        lambda: jobs_use_cases.list_jobs(
            user_id=user_id,
            platform=platform,
            status=status,
            limit=limit,
            offset=offset,
        ),
        "list_jobs_failed",
        "获取岗位列表失败",
    )


# ============================================================================
# 岗位删除
# ============================================================================

@router.delete("/{job_id}")
async def delete_job(
    job_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """删除已采集岗位。"""
    return await _call_use_case(
        lambda: jobs_use_cases.delete_job(job_id=job_id, user_id=user_id),
        "delete_failed",
        "删除岗位失败",
    )
