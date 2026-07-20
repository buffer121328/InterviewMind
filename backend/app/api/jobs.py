"""
BOSS 岗位自动化 API 路由
提供岗位采集、资产生成、投递操作接口
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.workflows.jobs import JobBadRequest, JobNotFound, JobsUseCaseError, jobs_use_cases
from app.schemas.job_schemas import (
    ApplyPreviewRequest,
    ApplyResponse,
    ApplySendRequest,
    CaptureRecommendationsRequest,
    CaptureRecommendationsResponse,
    JobCaptureRequest,
    JobCaptureResponse,
    JobDetailResponse,
    JobListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["岗位自动化"])

T = TypeVar("T")

_ERROR_STATUS = {
    JobBadRequest: 400,
    JobNotFound: 404,
}


async def _call_use_case(action: Callable[[], Awaitable[T]], error_code: str, error_message: str) -> T:
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
        logger.error("[API] %s: %s", error_message, exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": error_code, "message": str(exc)}) from exc


# ============================================================================
# 岗位采集
# ============================================================================

@router.post("/capture", response_model=JobCaptureResponse)
async def capture_job(
    request: JobCaptureRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    岗位采集接口

    支持两种方式：
    1. URL 采集：提供 source_url
    2. 手动粘贴：提供 job_description
    """
    return await _call_use_case(
        lambda: jobs_use_cases.capture_job(request=request, user_id=user_id),
        "capture_failed",
        "岗位采集失败",
    )


# ============================================================================
# 岗位查询
# ============================================================================

@router.post("/apply/preview", response_model=ApplyResponse)
async def preview_job_application(
    request: ApplyPreviewRequest,
    user_id: str = Depends(get_current_user_id),
):
    """生成不会点击发送按钮的投递预览，并签发短期一次性许可。"""
    return await _call_use_case(
        lambda: jobs_use_cases.preview_job_application(request=request, user_id=user_id),
        "apply_preview_failed",
        "生成投递预览失败",
    )


@router.post("/apply/send", response_model=ApplyResponse)
async def send_job_application(
    request: ApplySendRequest,
    user_id: str = Depends(get_current_user_id),
):
    """消费预览许可并执行一次发送；许可与预览内容不一致时拒绝。"""
    return await _call_use_case(
        lambda: jobs_use_cases.send_job_application(request=request, user_id=user_id),
        "apply_send_failed",
        "发送投递失败",
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


# ============================================================================
# 批量推荐页采集（BOSS 半自动化）
# ============================================================================

@router.post("/capture-recommendations", response_model=CaptureRecommendationsResponse)
async def capture_recommendations(
    request: CaptureRecommendationsRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    批量抓取 BOSS 推荐页前 N 个岗位 + 为每个岗位生成投递资产。

    前置条件：
    - 已安装 Playwright Chromium
    - 首次使用时在项目打开的专用浏览器中登录 BOSS直聘

    流程：
    1. 通过持久化 Playwright 会话打开 BOSS 搜索页，读取前 N 个岗位卡片
    2. 对每个卡片：capture_from_text 标准化+入库 → generate_assets 生成 JD分析+定制简历+打招呼
    3. 返回 5 个岗位 + 各自资产
    """
    return await _call_use_case(
        lambda: jobs_use_cases.capture_recommendations(request=request, user_id=user_id),
        "capture_recommendations_failed",
        "批量推荐采集失败",
    )
