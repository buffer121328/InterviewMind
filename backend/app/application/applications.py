"""投递追踪应用用例。

应用层负责组合 Repository、表达业务边界；API 层只负责 HTTP 映射。
"""

from dataclasses import dataclass
from typing import Optional

from app.repositories.application.application_event_repo import application_event_repo
from app.repositories.application.job_application_repo import job_application_repo
from app.schemas.job_application import (
    ApplicationCreateRequest,
    ApplicationDetailResponse,
    ApplicationListResponse,
    ApplicationUpdateRequest,
    EventCreateRequest,
    EventListResponse,
)

DEFAULT_USER_ID = "default_user"


@dataclass(slots=True)
class ApplicationUseCaseError(Exception):
    """投递追踪用例异常。"""

    error: str
    message: str


class ApplicationNotFound(ApplicationUseCaseError):
    """投递记录不存在或用户无权访问。"""


class ApplicationDeleteFailed(ApplicationUseCaseError):
    """投递记录删除失败。"""


class ApplicationUseCases:
    """投递追踪应用服务。"""

    @staticmethod
    def resolve_user_id(user_id: Optional[str]) -> str:
        return user_id or DEFAULT_USER_ID

    async def create_application(
        self,
        *,
        user_id: Optional[str],
        request: ApplicationCreateRequest,
    ) -> ApplicationDetailResponse:
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
        application = await self._get_application_or_raise(application_id, user_id)
        return ApplicationDetailResponse(success=True, application=application)

    async def update_application(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
        request: ApplicationUpdateRequest,
    ) -> ApplicationDetailResponse:
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
        await self._get_application_or_raise(application_id, user_id)
        event_row = await application_event_repo.add_event(
            application_id=application_id,
            request=request,
        )
        return {"success": True, "event": event_row}

    async def list_application_events(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
    ) -> EventListResponse:
        await self._get_application_or_raise(application_id, user_id)
        events = await application_event_repo.list_events(application_id=application_id)
        return EventListResponse(success=True, events=events)

    async def _get_application_or_raise(self, application_id: int, user_id: Optional[str]):
        application = await job_application_repo.get_application(
            application_id,
            user_id=self.resolve_user_id(user_id),
        )
        if application is None:
            raise self._not_found(application_id)
        return application

    @staticmethod
    def _not_found(application_id: int) -> ApplicationNotFound:
        return ApplicationNotFound(
            error="NotFound",
            message=f"投递记录 {application_id} 不存在或无权访问",
        )


application_use_cases = ApplicationUseCases()
