"""岗位自动化应用用例。

应用层负责组合岗位 Repository 与业务 Service；API 层只做 HTTP 映射。
"""

from dataclasses import dataclass
from typing import Any

from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
from app.schemas.job_schemas import (
    BossOpenJobRequest,
    BossTabCaptureRequest,
    GreetingUpdateRequest,
    JobDetailResponse,
    JobExportApplicationRequest,
    JobLibraryImportRequest,
    JobListItem,
    JobListResponse,
)
from integrations.boss.automation_client import (
    BossAutomationError,
    get_boss_automation_client,
)
from integrations.boss.security import is_allowed_boss_job_url


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

    @staticmethod
    async def _record_send_event(
        *,
        application_id: int,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """写入不含消息正文的发送事件。"""

        from app.db.repositories.application.application_event_repo import application_event_repo
        from app.schemas.job_application import EventCreateRequest

        await application_event_repo.add_event(
            application_id,
            EventCreateRequest(
                event_type=event_type,
                event_data=event_data or {},
            ),
        )

    async def _record_send_state(
        self,
        *,
        application_id: int,
        user_id: str,
        send_status: str,
        event_type: str,
        latest_status: str | None = None,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """持久化无正文发送状态和事件；owner 校验失败时停止后续外部动作。"""

        from app.db.repositories.application.job_application_repo import job_application_repo
        from app.schemas.job_application import ApplicationUpdateRequest

        updated = await job_application_repo.update_application(
            application_id,
            user_id,
            ApplicationUpdateRequest(
                send_status=send_status,
                latest_status=latest_status,
            ),
        )
        if updated is None:
            raise JobNotFound("application_not_found", "投递记录不存在或无权访问")
        await self._record_send_event(
            application_id=application_id,
            event_type=event_type,
            event_data=event_data,
        )

    async def send_boss_application_message(
        self,
        *,
        application_id: int,
        browser_channel: str | None,
        user_id: str,
    ) -> dict[str, object]:
        """发送投递记录中已审批的 BOSS 文案，并用状态占位阻止歧义重试。"""

        from app.db.repositories.application.job_application_repo import job_application_repo

        application = await job_application_repo.get_application(application_id, user_id)
        if application is None:
            raise JobNotFound("application_not_found", "投递记录不存在或无权访问")
        send_status = str(application.send_status or "pending")
        if send_status == "sent":
            return {
                "success": True,
                "status": "sent",
                "already_sent": True,
                "message": "该投递文案已发送，本次未重复执行。",
            }
        if send_status in {"sending", "unknown"}:
            raise JobBadRequest(
                "send_state_requires_review",
                "上一次发送结果尚不明确，请人工复核 BOSS 会话后再决定是否重试。",
            )

        source_url = str(application.source_url or "")
        message_text = str(application.greeting_text or "").strip()
        if str(application.source_platform or "").casefold() != "boss":
            raise JobBadRequest("unsupported_platform", "该投递记录不是 BOSS 岗位")
        if not is_allowed_boss_job_url(source_url):
            raise JobBadRequest("invalid_job_url", "投递记录缺少有效的 BOSS 官方岗位链接")
        if not 20 <= len(message_text) <= 500:
            raise JobBadRequest("invalid_greeting", "投递记录中的沟通文案长度必须为 20-500 字")

        claimed = await job_application_repo.claim_application_for_send(application_id, user_id)
        if not claimed:
            latest = await job_application_repo.get_application(application_id, user_id)
            if latest is None:
                raise JobNotFound("application_not_found", "投递记录不存在或无权访问")
            latest_status = str(latest.send_status or "pending")
            if latest_status == "sent":
                return {
                    "success": True,
                    "status": "sent",
                    "already_sent": True,
                    "message": "该投递文案已发送，本次未重复执行。",
                }
            if latest_status in {"sending", "unknown"}:
                raise JobBadRequest(
                    "ambiguous_send_state",
                    "该投递可能正在发送或结果未知，请人工复核 BOSS 会话后再决定是否重试。",
                )
            raise JobBadRequest("send_state_conflict", "投递发送状态已变化，请刷新后重试")

        await self._record_send_event(
            application_id=application_id,
            event_type="send_requested",
            event_data={"browser_channel": browser_channel or "default"},
        )
        try:
            result = await get_boss_automation_client().browser_tab_send_message(
                source_url,
                message_text,
                browser_channel,
            )
        except BossAutomationError as exc:
            ambiguous = bool(exc.request_may_have_run)
            await self._record_send_state(
                application_id=application_id,
                user_id=user_id,
                send_status="unknown" if ambiguous else "failed",
                event_type="send_uncertain" if ambiguous else "send_failed",
                event_data={
                    "browser_channel": browser_channel or "default",
                    "error_type": type(exc).__name__,
                    "request_may_have_run": ambiguous,
                },
            )
            error_type = JobBadRequest if exc.status_code == 400 else JobBrowserTabUnavailable
            raise error_type("boss_message_send_failed", str(exc)) from exc

        await self._record_send_state(
            application_id=application_id,
            user_id=user_id,
            send_status="sent",
            latest_status="applied",
            event_type="applied",
            event_data={"browser_channel": browser_channel or "default"},
        )
        return {
            **result,
            "success": True,
            "status": "sent",
            "application_id": application_id,
        }

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
        """把用户确认的待入库卡片保存进岗位库并调度可恢复资产任务。

        保存按来源哈希去重，资产任务经幂等键复用；失败可安全重试。
        """
        if not request.api_config:
            raise JobBadRequest(
                "missing_api_config",
                "请先配置 Smart 与 Fast 模型通道再入库",
            )
        from ai.workflows.jobs.job_capture_service import (
            import_cards_to_library as _import_cards_to_library,
        )

        return await _import_cards_to_library(
            user_id=user_id,
            cards=[card.model_dump() for card in request.cards],
            resume_content=request.resume_content,
            api_config=request.api_config,
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
