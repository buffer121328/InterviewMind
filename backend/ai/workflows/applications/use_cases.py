"""投递追踪应用用例。

应用层负责组合 Repository、表达业务边界；API 层只负责 HTTP 映射。
"""

from dataclasses import dataclass
from typing import Optional

from app.db.unit_of_work import UnitOfWork
from app.db.models import async_session
from app.db.repositories.application.application_event_repo import application_event_repo
from app.db.repositories.application.job_application_repo import job_application_repo
from app.db.repositories.resume.resume_generation_repo import get_generation_repo
from app.schemas.jobs.job_application import (
    ApplicationCreateRequest,
    ApplicationDetailResponse,
    ApplicationListResponse,
    ApplicationResumeLinkRequest,
    ApplicationUpdateRequest,
    LinkedResumeAsset,
    EventCreateRequest,
    EventListResponse,
)

DEFAULT_USER_ID = "default_user"


@dataclass(slots=True)
class ApplicationUseCaseError(Exception):
    """投递追踪用例异常。"""

    error: str  # 机器可读的错误码（如 NotFound、InternalServerError）
    message: str  # 面向用户的可读错误信息


class ApplicationNotFound(ApplicationUseCaseError):
    """投递记录不存在或用户无权访问。"""


class ApplicationDeleteFailed(ApplicationUseCaseError):
    """投递记录删除失败。"""


class ApplicationUseCases:
    """投递追踪应用服务。"""

    @staticmethod
    def resolve_user_id(user_id: Optional[str]) -> str:
        """解析 `user id`。

        Args:
            user_id: 当前用户标识。
        """
        return user_id or DEFAULT_USER_ID

    async def create_application(
        self,
        *,
        user_id: Optional[str],
        request: ApplicationCreateRequest,
    ) -> ApplicationDetailResponse:
        """创建投递记录，校验通过后落库并返回详情。

        Args:
            user_id: 当前用户标识。
            request: 请求对象。
        """
        application = await job_application_repo.create_application(
            user_id=self.resolve_user_id(user_id),
            request=request,
        )
        return ApplicationDetailResponse(success=True, application=application)

    async def list_applications(
        self,
        *,
        user_id: Optional[str],
        status: Optional[str],
        limit: int,
        offset: int,
    ) -> ApplicationListResponse:
        """按当前用户与状态条件分页读取投递记录。

        Args:
            user_id: 当前用户标识。
            status: 投递状态筛选条件（可选）。
            limit: 返回数量上限。
            offset: 分页偏移量。
        """
        resolved_user_id = self.resolve_user_id(user_id)
        applications = await job_application_repo.list_applications(
            user_id=resolved_user_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await job_application_repo.get_application_count(
            user_id=resolved_user_id,
            status=status,
        )
        return ApplicationListResponse(
            success=True,
            applications=applications,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_application(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
    ) -> ApplicationDetailResponse:
        """按用户归属读取投递记录详情；不存在或无权限时抛出统一异常。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
        """
        application = await self._get_application_or_raise(application_id, user_id)
        application = await self._attach_linked_resume(
            application=application,
            user_id=self.resolve_user_id(user_id),
        )
        return ApplicationDetailResponse(success=True, application=application)

    async def set_application_resume(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
        request: ApplicationResumeLinkRequest,
    ) -> ApplicationDetailResponse:
        """为投递记录设置关联简历；先校验记录与简历的归属，再写入并返回更新后的投递详情。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
            request: 简历关联请求。
        """
        resolved_user_id = self.resolve_user_id(user_id)
        await self._get_application_or_raise(application_id, resolved_user_id)
        if request.resume_id is not None:
            resume = await get_generation_repo().get_generated_resume(request.resume_id, resolved_user_id)
            if resume is None:
                raise ApplicationNotFound(
                    error="NotFound",
                    message="关联简历不存在或无权访问",
                )
        application = await job_application_repo.set_linked_resume(
            application_id=application_id,
            user_id=resolved_user_id,
            resume_id=request.resume_id,
        )
        if application is None:
            raise self._not_found(application_id)
        application = await self._attach_linked_resume(
            application=application,
            user_id=resolved_user_id,
        )
        return ApplicationDetailResponse(success=True, application=application)

    async def _attach_linked_resume(
        self,
        *,
        application,
        user_id: str,
    ):
        """为投递记录附加关联简历资产；无关联简历或读取失败时返回空链接。

        Args:
            application: 投递记录对象。
            user_id: 当前用户标识。
        """
        resume_id = application.generated_resume_id or application.custom_resume_id
        if not resume_id:
            return application.model_copy(update={"linked_resume": None})
        resume = await get_generation_repo().get_generated_resume(resume_id, user_id)
        if resume is None:
            return application.model_copy(update={"linked_resume": None})
        asset = LinkedResumeAsset(
            id=resume["id"],
            title=resume["title"],
            job_description=resume.get("job_description"),
            content=resume["content"],
            created_at=resume["created_at"],
        )
        return application.model_copy(update={"linked_resume": asset})

    async def update_application(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
        request: ApplicationUpdateRequest,
    ) -> ApplicationDetailResponse:
        """按用户归属更新投递记录并返回详情。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
            request: 请求对象。
        """
        application = await job_application_repo.update_application(
            application_id=application_id,
            user_id=self.resolve_user_id(user_id),
            request=request,
        )
        if application is None:
            raise self._not_found(application_id)
        return ApplicationDetailResponse(success=True, application=application)

    async def delete_application(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
    ) -> dict[str, object]:
        """按用户归属删除投递记录；删除失败时抛出统一异常。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
        """
        await self._get_application_or_raise(application_id, user_id)
        success = await job_application_repo.delete_application(
            application_id=application_id,
            user_id=self.resolve_user_id(user_id),
        )
        if not success:
            raise ApplicationDeleteFailed(
                error="InternalServerError",
                message=f"无法删除投递记录 {application_id}",
            )
        return {"success": True, "message": f"投递记录 {application_id} 已删除"}

    async def add_event_to_application(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
        request: EventCreateRequest,
    ) -> dict[str, object]:
        """校验归属后为投递记录追加一条事件记录（仅持久化，不触发外部投递）。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
            request: 请求对象。
        """
        await self._get_application_or_raise(application_id, user_id)
        async with UnitOfWork(async_session) as uow:
            event_row = await application_event_repo.add_event(
                application_id=application_id,
                request=request,
                session=uow.db,
            )
        return {"success": True, "event": event_row}

    async def list_application_events(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
    ) -> EventListResponse:
        """按用户归属读取投递记录的事件列表。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
        """
        await self._get_application_or_raise(application_id, user_id)
        events = await application_event_repo.list_events(application_id=application_id)
        return EventListResponse(success=True, events=events)

    async def _get_application_or_raise(self, application_id: int, user_id: Optional[str]):
        """按 owner 读取投递记录，不存在或不属于当前用户时抛出统一业务异常，避免路由泄露资源存在性。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
        """
        application = await job_application_repo.get_application(
            application_id,
            user_id=self.resolve_user_id(user_id),
        )
        if application is None:
            raise self._not_found(application_id)
        return application

    @staticmethod
    def _not_found(application_id: int) -> ApplicationNotFound:
        """构造统一的 404 错误响应，保持 API 客户端可识别的错误格式。

        Args:
            application_id: 投递记录标识。
        """
        return ApplicationNotFound(
            error="NotFound",
            message=f"投递记录 {application_id} 不存在或无权访问",
        )


application_use_cases = ApplicationUseCases()
