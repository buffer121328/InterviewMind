"""岗位自动化应用用例。

应用层负责组合岗位 Repository 与业务 Service；API 层只做 HTTP 映射。
"""

from dataclasses import dataclass
from typing import Any

from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
from app.schemas.job_schemas import (
    BossOpenJobRequest,
    BossTabCaptureRequest,
    JobDetailResponse,
    JobLibraryImportRequest,
    JobListItem,
    JobListResponse,
)
from integrations.boss.automation_client import (
    BossAutomationError,
    get_boss_automation_client,
)
from integrations.boss.security import is_allowed_boss_job_url


def _without_retired_greetings(job: dict[str, Any]) -> dict[str, Any]:
    """Return a response-safe copy without retired job-center greeting assets."""
    safe_job = dict(job)
    asset_payload = safe_job.get("asset_payload")
    if isinstance(asset_payload, dict):
        safe_job["asset_payload"] = {
            key: value for key, value in asset_payload.items() if key != "greetings"
        }
    return safe_job


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
        return JobDetailResponse(success=True, job=_without_retired_greetings(job))

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
                company_name=job.get("company_name") or "",
                job_title=job.get("job_title") or "",
                platform=job.get("platform") or "",
                company_size_text=job.get("company_size_text") or "",
                city=job.get("city") or "",
                salary_text=job.get("salary_text") or "",
                source_url=job.get("source_url") or "",
                match_score=job.get("match_score"),
                asset_run_id=job.get("asset_run_id"),
                asset_status=job.get("asset_status"),
                status=job.get("status") or "pending",
                tags=job.get("tags") or [],
                captured_at=job.get("captured_at"),
            )
            for job in jobs
        ]
        return JobListResponse(success=True, jobs=items, total=total)

    async def import_cards_to_library(
        self,
        *,
        request: JobLibraryImportRequest,
        user_id: str,
    ) -> dict[str, object]:
        """把用户确认的待入库卡片确定性保存进岗位库。

        保存仅执行 owner 绑定、标准化和来源哈希去重；模型分析、Greeting 与
        Resume Generation 必须由用户在对应工作台显式启动。
        """
        from ai.workflows.jobs.capture import imports as capture_imports

        return await capture_imports.import_cards_to_library(
            user_id=user_id,
            cards=[card.model_dump() for card in request.cards],
            city=request.city,
        )

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
