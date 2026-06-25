"""
BOSS 岗位自动化 API 路由
提供岗位采集、资产生成、投递操作接口
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends

from app.schemas.job_schemas import (
    JobCaptureRequest,
    JobCaptureResponse,
    JobListResponse,
    JobDetailResponse,
    JobListItem,
    AssetGenerateRequest,
    AssetGenerateResponse,
    GreetingGenerateRequest,
    GreetingGenerateResponse,
    CaptureRecommendationsRequest,
    CaptureRecommendationsResponse,
    CapturedJobSummary,
)
from app.api.deps import get_current_user_id
from app.repositories.jobs.job_capture_repo import get_job_capture_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["岗位自动化"])


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
    from app.services.jobs.job_capture_service import capture_from_url, capture_from_text

    try:
        if request.source_url:
            result = await capture_from_url(
                url=request.source_url,
                user_id=user_id,
                platform=request.platform,
                company_name_hint=request.company_name_hint or "",
                job_title_hint=request.job_title_hint or "",
                api_config=request.api_config,
                cookies=request.cookies,
                headless=request.headless,
            )
        elif request.job_description:
            result = await capture_from_text(
                jd_text=request.job_description,
                user_id=user_id,
                platform=request.platform,
                company_name_hint=request.company_name_hint or "",
                job_title_hint=request.job_title_hint or "",
                api_config=request.api_config,
            )
        else:
            raise HTTPException(status_code=400, detail="请提供 source_url 或 job_description")

        return JobCaptureResponse(
            success=result.get("success", False),
            job_id=result.get("job_id"),
            normalized_job=result.get("normalized_job"),
            is_duplicate=result.get("is_duplicate", False),
            message=result.get("message"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 岗位采集失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "capture_failed", "message": str(e)})


# ============================================================================
# 岗位查询
# ============================================================================

@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """
    查看已采集岗位详情
    """
    try:
        repo = get_job_capture_repo()
        job = await repo.get_job(job_id, user_id)

        if not job:
            raise HTTPException(status_code=404, detail="岗位不存在")

        return JobDetailResponse(success=True, job=job)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 获取岗位失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "get_job_failed", "message": str(e)})


@router.get("", response_model=JobListResponse)
async def list_jobs(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    """
    岗位列表查询
    """
    try:
        repo = get_job_capture_repo()
        jobs = await repo.list_jobs(
            user_id=user_id,
            platform=platform,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await repo.get_job_count(
            user_id=user_id,
            platform=platform,
            status=status,
        )

        items = []
        for job in jobs:
            items.append(JobListItem(
                id=job["id"],
                company_name=job.get("company_name", ""),
                job_title=job.get("job_title", ""),
                platform=job.get("platform", ""),
                city=job.get("city", ""),
                salary_text=job.get("salary_text", ""),
                status=job.get("status", "pending"),
                tags=job.get("tags", []),
                captured_at=job.get("captured_at"),
            ))

        return JobListResponse(success=True, jobs=items, total=total)
    except Exception as e:
        logger.error(f"[API] 获取岗位列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "list_jobs_failed", "message": str(e)})


# ============================================================================
# 岗位删除
# ============================================================================

@router.delete("/{job_id}")
async def delete_job(
    job_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """
    删除已采集岗位
    """
    try:
        repo = get_job_capture_repo()
        deleted = await repo.delete_job(job_id, user_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="岗位不存在")

        return {"success": True, "message": "岗位已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] 删除岗位失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "delete_failed", "message": str(e)})


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

    前置条件（仅 macOS）：
    - Chrome 浏览器已打开且已登录 BOSS直聘
    - 菜单 查看 → 开发者 → 允许 Apple 事件中的 JavaScript 已启用

    流程：
    1. 通过 AppleScript 在 Chrome 新开 BOSS 首页 tab，读取「精选职位」前 N 个卡片
    2. 对每个卡片：capture_from_text 标准化+入库 → generate_assets 生成 JD分析+定制简历+打招呼
    3. 返回 5 个岗位 + 各自资产
    """
    from app.services.jobs.job_capture_service import capture_from_recommendations

    try:
        result = await capture_from_recommendations(
            user_id=user_id,
            query=request.query,
            resume_content=request.resume_content,
            api_config=request.api_config,
            top_n=request.top_n,
            city=request.city,
        )

        # 转换为响应模型
        job_summaries = []
        for j in result.get("jobs", []):
            job_summaries.append(CapturedJobSummary(
                job_id=j["job_id"],
                company_name=j.get("company_name", ""),
                job_title=j.get("job_title", ""),
                salary_text=j.get("salary_text", ""),
                city=j.get("city", ""),
                match_score=j.get("match_score"),
                custom_resume_id=j.get("custom_resume_id"),
                greetings=j.get("greetings", []),
                risk_flags=j.get("risk_flags", []),
            ))

        return CaptureRecommendationsResponse(
            success=result.get("success", False),
            total=result.get("total", 0),
            jobs=job_summaries,
            message=result.get("message"),
        )
    except Exception as e:
        logger.error(f"[API] 批量推荐采集失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "capture_recommendations_failed", "message": str(e)},
        )
