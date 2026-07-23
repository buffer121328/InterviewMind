"""岗位自动化应用用例。

应用层负责组合岗位 Repository 与业务 Service；API 层只做 HTTP 映射。
"""

from dataclasses import dataclass

from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
from app.schemas.job_schemas import (
    ApplyPreviewRequest,
    ApplyResponse,
    ApplySendRequest,
    CapturedJobSummary,
    CaptureRecommendationsRequest,
    CaptureRecommendationsResponse,
    JobCaptureRequest,
    JobCaptureResponse,
    JobDetailResponse,
    JobListItem,
    JobListResponse,
)
from ai.workflows.jobs_support.boss_apply_service import execute_apply_preview, execute_apply_send
from ai.workflows.jobs_support.job_capture_service import (
    capture_from_recommendations,
    capture_from_text,
    capture_from_url,
)


@dataclass(slots=True)
class JobsUseCaseError(Exception):
    """岗位自动化用例异常。"""

    error: str
    message: str


class JobBadRequest(JobsUseCaseError):
    """岗位请求参数不完整。"""


class JobNotFound(JobsUseCaseError):
    """岗位不存在或用户无权访问。"""


class JobsUseCases:
    """岗位自动化应用服务。"""

    async def capture_job(self, *, request: JobCaptureRequest, user_id: str) -> JobCaptureResponse:
        """异步执行 `capture_job` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
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
            raise JobBadRequest(error="BadRequest", message="请提供 source_url 或 job_description")

        return JobCaptureResponse(
            success=result.get("success", False),
            job_id=result.get("job_id"),
            normalized_job=result.get("normalized_job"),
            is_duplicate=result.get("is_duplicate", False),
            message=result.get("message"),
        )

    async def preview_job_application(self, *, request: ApplyPreviewRequest, user_id: str) -> ApplyResponse:
        """预览 `job application`。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        return await execute_apply_preview(
            job_id=request.job_id,
            user_id=user_id,
            greeting_text=request.greeting_text,
            resume_id=request.resume_id,
        )

    async def send_job_application(self, *, request: ApplySendRequest, user_id: str) -> ApplyResponse:
        """发送 `job application`。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        return await execute_apply_send(
            job_id=request.job_id,
            user_id=user_id,
            greeting_text=request.greeting_text,
            resume_id=request.resume_id,
            approval_token=request.approval_token,
            confirmed=request.confirmed,
        )

    async def get_job(self, *, job_id: int, user_id: str) -> JobDetailResponse:
        """获取 `job`。

        Args:
            job_id: 岗位标识。
            user_id: 当前用户标识。
        """
        repo = get_job_capture_repo()
        job = await repo.get_job(job_id, user_id)
        if not job:
            raise JobNotFound(error="NotFound", message="岗位不存在")
        return JobDetailResponse(success=True, job=job)

    async def list_jobs(
        self,
        *,
        user_id: str,
        platform: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> JobListResponse:
        """列出 `jobs`。

        Args:
            user_id: 当前用户标识。
            platform: 调用方传入的 `platform` 参数。
            status: 调用方传入的 `status` 参数。
            limit: 返回数量上限。
            offset: 分页偏移量。
        """
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
        items = [
            JobListItem(
                id=job["id"],
                company_name=job.get("company_name", ""),
                job_title=job.get("job_title", ""),
                platform=job.get("platform", ""),
                city=job.get("city", ""),
                salary_text=job.get("salary_text", ""),
                status=job.get("status", "pending"),
                tags=job.get("tags", []),
                captured_at=job.get("captured_at"),
            )
            for job in jobs
        ]
        return JobListResponse(success=True, jobs=items, total=total)

    async def delete_job(self, *, job_id: int, user_id: str) -> dict[str, object]:
        """删除 `job`。

        Args:
            job_id: 岗位标识。
            user_id: 当前用户标识。
        """
        repo = get_job_capture_repo()
        deleted = await repo.delete_job(job_id, user_id)
        if not deleted:
            raise JobNotFound(error="NotFound", message="岗位不存在")
        return {"success": True, "message": "岗位已删除"}

    async def capture_recommendations(
        self,
        *,
        request: CaptureRecommendationsRequest,
        user_id: str,
    ) -> CaptureRecommendationsResponse:
        """异步执行 `capture_recommendations` 相关逻辑。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        result = await capture_from_recommendations(
            user_id=user_id,
            query=request.query,
            resume_content=request.resume_content,
            api_config=request.api_config,
            top_n=request.top_n,
            city=request.city,
        )
        job_summaries = [
            CapturedJobSummary(
                job_id=job["job_id"],
                company_name=job.get("company_name", ""),
                job_title=job.get("job_title", ""),
                salary_text=job.get("salary_text", ""),
                city=job.get("city", ""),
                match_score=job.get("match_score"),
                custom_resume_id=job.get("custom_resume_id"),
                greetings=job.get("greetings", []),
                risk_flags=job.get("risk_flags", []),
                asset_run_id=job.get("asset_run_id"),
                asset_status=job.get("asset_status"),
            )
            for job in result.get("jobs", [])
        ]
        return CaptureRecommendationsResponse(
            success=result.get("success", False),
            total=result.get("total", 0),
            jobs=job_summaries,
            message=result.get("message"),
        )


jobs_use_cases = JobsUseCases()
