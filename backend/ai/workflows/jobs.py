"""岗位自动化应用用例。

应用层负责组合岗位 Repository 与业务 Service；API 层只做 HTTP 映射。
"""

from dataclasses import dataclass

from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
from app.schemas.job_schemas import (
    BossOpenJobRequest,
    BossTabCaptureRequest,
    GreetingUpdateRequest,
    JobDetailResponse,
    JobExportApplicationRequest,
    JobListItem,
    JobListResponse,
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


class JobBrowserTabUnavailable(JobsUseCaseError):
    """宿主机浏览器服务或现有 BOSS 标签页尚不满足操作前置条件。"""


class JobsUseCases:
    """岗位自动化应用服务。"""

    async def get_boss_browser_tab_status(
        self,
        *,
        browser_channel: str | None,
    ) -> dict[str, object]:
        """经宿主机服务检查现有 BOSS 标签页，不在主后端读取 GUI 或浏览器凭据。"""
        from integrations.boss.automation_client import BossAutomationError, get_boss_automation_client

        try:
            return await get_boss_automation_client().browser_tab_status(browser_channel)
        except BossAutomationError as exc:
            error_type = JobBadRequest if exc.status_code == 400 else JobBrowserTabUnavailable
            raise error_type("boss_browser_tab_failed", str(exc)) from exc

    async def search_and_capture_boss_tab(
        self,
        *,
        request: BossTabCaptureRequest,
    ) -> dict[str, object]:
        """让宿主机复用现有登录标签页完成一次保守搜索和有限字段采集。"""
        from integrations.boss.automation_client import BossAutomationError, get_boss_automation_client

        try:
            return await get_boss_automation_client().browser_tab_search_and_capture(
                query=request.query,
                city=request.city,
                max_cards=request.max_cards,
                browser_channel=request.browser_channel,
            )
        except BossAutomationError as exc:
            error_type = JobBadRequest if exc.status_code == 400 else JobBrowserTabUnavailable
            raise error_type("boss_browser_tab_failed", str(exc)) from exc

    async def update_greeting(
        self,
        *,
        job_id: int,
        greeting_index: int,
        request: GreetingUpdateRequest,
        user_id: str,
    ) -> JobDetailResponse:
        """在 owner 校验后持久化一条用户编辑的打招呼方案。"""
        repo = get_job_capture_repo()
        try:
            job = await repo.update_greeting(
                job_id,
                user_id,
                greeting_index,
                request.message_text.strip(),
            )
        except IndexError as exc:
            raise JobBadRequest("invalid_greeting_index", "打招呼方案不存在或资产尚未生成") from exc
        if job is None:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        return JobDetailResponse(success=True, job=job)

    async def export_to_application(
        self,
        *,
        job_id: int,
        request: JobExportApplicationRequest,
        user_id: str,
    ) -> dict[str, object]:
        """把已采集岗位和选定文案加入投递管理，初始状态固定为待投递。"""
        job_repo = get_job_capture_repo()
        job = await job_repo.get_job(job_id, user_id)
        if not job:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        try:
            updated_job = await job_repo.update_greeting(
                job_id,
                user_id,
                request.greeting_index,
                request.greeting_text.strip(),
            )
        except IndexError as exc:
            raise JobBadRequest(
                "invalid_greeting_index",
                "所选打招呼方案不存在或岗位资产尚未生成",
            ) from exc
        if updated_job is None:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        job = updated_job
        from app.db.repositories.application.job_application_repo import job_application_repo
        from app.schemas.job_application import ApplicationCreateRequest

        existing = await job_application_repo.find_by_captured_job_id(job_id, user_id)
        if existing is not None:
            from app.schemas.job_application import ApplicationUpdateRequest

            detail = await job_application_repo.update_application(
                existing.id,
                user_id,
                ApplicationUpdateRequest(greeting_text=request.greeting_text.strip()),
            )
            return {
                "success": True,
                "application": detail or existing,
                "message": "该岗位已在投递管理中，已更新打招呼文案",
            }

        detail = await job_application_repo.create_application(
            user_id,
            ApplicationCreateRequest(
                company_name=str(job.get("company_name") or ""),
                job_title=str(job.get("job_title") or ""),
                job_description=str(job.get("job_description") or ""),
                channel="BOSS直聘",
                generated_resume_id=(job.get("asset_payload") or {}).get("custom_resume_id"),
                custom_resume_id=(job.get("asset_payload") or {}).get("custom_resume_id"),
                latest_status="saved",
                priority="medium",
                source_platform="boss",
                source_url=str(job.get("source_url") or ""),
                captured_job_id=job_id,
                greeting_text=request.greeting_text.strip(),
                send_status="pending",
                notes=f"匹配度：{job.get('match_score')}%" if job.get("match_score") is not None else None,
            ),
        )
        return {"success": True, "application": detail, "message": "已加入投递管理，状态为待投递"}

    async def open_job_in_existing_tab(
        self,
        *,
        job_id: int,
        request: BossOpenJobRequest,
        user_id: str,
    ) -> dict[str, object]:
        """通过宿主机服务在现有登录 BOSS 标签页打开已保存的官方岗位链接。"""
        job = await get_job_capture_repo().get_job(job_id, user_id)
        if not job:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        from integrations.boss.security import is_allowed_boss_job_url
        source_url = str(job.get("source_url") or "")
        if not is_allowed_boss_job_url(source_url):
            raise JobBadRequest("invalid_job_url", "岗位没有可打开的 BOSS 官方详情链接")
        from integrations.boss.automation_client import BossAutomationError, get_boss_automation_client
        try:
            return await get_boss_automation_client().browser_tab_open_job(
                source_url, request.browser_channel
            )
        except BossAutomationError as exc:
            error_type = JobBadRequest if exc.status_code == 400 else JobBrowserTabUnavailable
            raise error_type("boss_browser_tab_failed", str(exc)) from exc

    async def get_job(self, *, job_id: int, user_id: str) -> JobDetailResponse:
        """读取 job，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

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
        """按 owner、筛选条件和分页参数读取 jobs；仅返回当前调用方有权查看的持久化结果。

        Args:
            user_id: 当前用户标识。
            platform: 经过类型边界校验的 `platform`；其格式和可选值由参数类型及调用流程约束。
            status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
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
                company_size_text=job.get("company_size_text", ""),
                city=job.get("city", ""),
                salary_text=job.get("salary_text", ""),
                source_url=job.get("source_url", ""),
                match_score=job.get("match_score"),
                asset_run_id=job.get("asset_run_id"),
                asset_status=job.get("asset_status"),
                status=job.get("status", "pending"),
                tags=job.get("tags", []),
                captured_at=job.get("captured_at"),
            )
            for job in jobs
        ]
        return JobListResponse(success=True, jobs=items, total=total)

    async def delete_job(self, *, job_id: int, user_id: str) -> dict[str, object]:
        """在 owner 校验下删除 job；删除失败或资源不可见时保持幂等的业务错误语义。

        Args:
            job_id: 岗位标识。
            user_id: 当前用户标识。
        """
        repo = get_job_capture_repo()
        deleted = await repo.delete_job(job_id, user_id)
        if not deleted:
            raise JobNotFound(error="NotFound", message="岗位不存在")
        return {"success": True, "message": "岗位已删除"}

jobs_use_cases = JobsUseCases()
