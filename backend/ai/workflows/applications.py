"""投递追踪应用用例。

应用层负责组合 Repository、表达业务边界；API 层只负责 HTTP 映射。
"""

from dataclasses import dataclass
from typing import Optional

from app.db.unit_of_work import UnitOfWork
from app.db.models import async_session
from app.db.repositories.application.application_event_repo import application_event_repo
from app.db.repositories.application.job_application_repo import job_application_repo
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
        """创建 application，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

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
        """按 owner、筛选条件和分页参数读取 applications；仅返回当前调用方有权查看的持久化结果。

        Args:
            user_id: 当前用户标识。
            status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
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
        """读取 application，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            application_id: 投递记录标识。
            user_id: 当前用户标识。
        """
        application = await self._get_application_or_raise(application_id, user_id)
        return ApplicationDetailResponse(success=True, application=application)

    async def update_application(
        self,
        *,
        application_id: int,
        user_id: Optional[str],
        request: ApplicationUpdateRequest,
    ) -> ApplicationDetailResponse:
        """在 owner 校验下更新 application；只写入允许变更的字段，避免绕过状态机或审批约束。

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
        """在 owner 校验下删除 application；删除失败或资源不可见时保持幂等的业务错误语义。

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
        """在 owner 校验通过后追加投递事件，并沿用用例层的持久化与审计边界；不直接执行外部投递。

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
        """按 owner、筛选条件和分页参数读取 application events；仅返回当前调用方有权查看的持久化结果。

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
