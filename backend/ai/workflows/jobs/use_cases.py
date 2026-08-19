"""岗位自动化应用用例。

应用层负责组合岗位 Repository 与业务 Service；API 层只做 HTTP 映射。
"""

from dataclasses import dataclass
from typing import Any

from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
from app.schemas.jobs.job_schemas import (
    BossOpenJobRequest,
    BossTabCaptureRequest,
    JobDetailResponse,
    JobJdAnalysisRequest,
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
    """返回不含已退役岗位中心问候资产的响应安全副本。

    Args:
        job: 传入的 job 值。
    """
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

    # 异常实例。
    # 异常实例。
    error: str
    # 单条消息。
    # 单条消息。
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
        """经宿主机服务检查现有 BOSS 标签页，不在主后端读取 GUI 或浏览器凭据。

        Args:
            browser_channel: 浏览器渠道标识（如 msedge/chrome）。
        """
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
        """让宿主机复用现有登录标签页完成一次保守搜索和有限字段采集。

        Args:
            request: 请求对象。
        """
        try:
            return await get_boss_automation_client().browser_tab_search_and_capture(
                query=request.query,
                city=request.city,
                max_cards=request.max_cards,
                experience=request.experience,
                job_type=request.job_type,
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
        """通过宿主机服务在现有登录 BOSS 标签页打开已保存的官方岗位链接。

        Args:
            job_id: 岗位 ID。
            request: 请求对象。
            user_id: 用户 ID，所有者范围限定。
        """
        job = await get_job_capture_repo().get_job(job_id, user_id)
        if not job:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
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

    async def analyze_job_jd(
        self,
        *,
        job_id: int,
        request: JobJdAnalysisRequest,
        user_id: str,
    ) -> JobDetailResponse:
        """显式分析一个已入库岗位的 JD，并只保存公开的匹配摘要。

        该操作不走完整岗位资产编排，因此不会生成简历、创建投递动作或变更岗位投递状态。

        Args:
            job_id: 岗位 ID。
            request: 请求对象。
            user_id: 用户 ID，所有者范围限定。
        """
        if not request.resume_content.strip():
            raise JobBadRequest("missing_resume", "请先提供当前简历内容")
        if request.api_config is None:
            raise JobBadRequest("missing_api_config", "请先配置可用模型后再进行 JD 匹配分析")

        repo = get_job_capture_repo()
        job = await repo.get_job(job_id, user_id)
        if not job:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        job_description = str(job.get("job_description") or "").strip()
        if not job_description:
            raise JobBadRequest("missing_job_description", "该岗位缺少可分析的职位介绍")

        from ai.runtime.safety.guardrails import screen_untrusted_text

        guardrail = screen_untrusted_text(job_description, source="job_capture_job_description")
        if not guardrail.allowed:
            raise JobBadRequest("job_description_rejected", "该职位介绍无法安全用于 JD 匹配分析")

        from ai.agents.resume.jd_matcher import match_jd

        try:
            raw_analysis = await match_jd(
                resume_content=request.resume_content,
                job_description=job_description,
                mode="smart",
                api_config=request.api_config.model_dump(),
                user_id=user_id,
            )
        except ValueError as exc:
            raise JobBadRequest("jd_analysis_unavailable", str(exc)) from exc
        except Exception as exc:
            raise JobBadRequest("jd_analysis_failed", "JD 匹配分析暂时失败，请稍后重试") from exc

        public_keys = (
            "overall_match_score",
            "skill_match_score",
            "project_match_score",
            "experience_match_score",
            "education_match_score",
            "matched_keywords",
            "missing_keywords",
            "strengths",
            "risks",
            "priority_actions",
            "selection_hints",
        )
        analysis = {key: raw_analysis[key] for key in public_keys if key in raw_analysis}
        match_score = analysis.get("overall_match_score")
        if not isinstance(match_score, (int, float)):
            raise JobBadRequest("invalid_jd_analysis", "JD 匹配分析没有返回有效匹配度")

        existing_payload = job.get("asset_payload")
        asset_payload = dict(existing_payload) if isinstance(existing_payload, dict) else {}
        if "preliminary_match_score" not in asset_payload and isinstance(job.get("match_score"), (int, float)):
            asset_payload["preliminary_match_score"] = job["match_score"]
        asset_payload["jd_analysis"] = analysis

        updated = await repo.update_asset_tracking(
            job_id,
            user_id,
            match_score=float(match_score),
            asset_payload=asset_payload,
        )
        if not updated:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        refreshed = await repo.get_job(job_id, user_id)
        if not refreshed:
            raise JobNotFound("job_not_found", "岗位不存在或无权访问")
        return JobDetailResponse(success=True, job=_without_retired_greetings(refreshed), message="JD 匹配分析已完成")

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

        Args:
            request: 请求对象。
            user_id: 用户 ID，所有者范围限定。
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
