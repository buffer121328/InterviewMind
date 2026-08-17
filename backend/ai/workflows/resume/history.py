"""简历历史与可用面试会话用例。"""

from dataclasses import dataclass
from typing import Literal

from app.db.repositories.resume.resume_repo import get_resume_repo
from app.db.repositories.session.session_repo import SessionRepo
from app.schemas.resume.resume_schemas import (
    CompletedSessionItem,
    CompletedSessionsResponse,
    ResumeHistoryDetailResponse,
    ResumeHistoryListResponse,
)


@dataclass(slots=True)
class ResumeHistoryUseCaseError(Exception):
    """简历历史用例异常。"""

    message: str  # 错误信息文本


class ResumeHistoryNotFound(ResumeHistoryUseCaseError):
    """历史结果不存在或用户无权访问。"""


class ResumeHistoryUseCases:
    """简历历史应用服务。"""

    def __init__(self) -> None:
        """初始化 `ResumeHistoryUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()

    async def get_completed_sessions(self, *, user_id: str, limit: int) -> CompletedSessionsResponse:
        """读取 completed sessions，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            user_id: 当前用户标识。
            limit: 返回数量上限。
        """
        try:
            sessions = await self._session_repo.get_completed_sessions_for_resume(
                user_id=user_id,
                limit=limit,
            )
            return CompletedSessionsResponse(
                success=True,
                sessions=[
                    CompletedSessionItem(
                        session_id=session["session_id"],
                        title=session["title"],
                        updated_at=session["updated_at"],
                        round_index=session["round_index"],
                        round_type=session["round_type"],
                        message_count=session["message_count"],
                    )
                    for session in sessions
                ],
            )
        except Exception as exc:
            return CompletedSessionsResponse(
                success=False,
                sessions=[],
                message=f"获取失败: {exc}",
            )

    async def list_resume_results(
        self,
        *,
        user_id: str,
        result_type: Literal["analyze", "optimize"] | None,
        limit: int,
        offset: int,
        include_data: bool,
    ) -> ResumeHistoryListResponse:
        """按 owner、筛选条件和分页参数读取 resume results；仅返回当前调用方有权查看的持久化结果。

        Args:
            user_id: 当前用户标识。
            result_type: 经过类型边界校验的 `result_type`；其格式和可选值由参数类型及调用流程约束。
            limit: 返回数量上限。
            offset: 分页偏移量。
            include_data: include 数据。
        """
        try:
            resume_repo = get_resume_repo()
            results = await resume_repo.list_results(
                user_id=user_id,
                result_type=result_type,
                limit=limit,
                offset=offset,
                include_data=include_data,
            )
            total = await resume_repo.count_results(user_id=user_id, result_type=result_type)
            return ResumeHistoryListResponse(
                success=True,
                results=results,
                total=total,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            return ResumeHistoryListResponse(
                success=False,
                results=[],
                total=0,
                limit=limit,
                offset=offset,
                message=str(exc),
            )

    async def get_resume_result(self, *, result_id: int, user_id: str) -> ResumeHistoryDetailResponse:
        """读取 resume result，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            result_id: result 标识。
            user_id: 当前用户标识。
        """
        result = await get_resume_repo().get_result(result_id, user_id)
        if not result:
            raise ResumeHistoryNotFound(message="结果不存在")
        return ResumeHistoryDetailResponse(success=True, result=result)

    async def delete_resume_result(self, *, result_id: int, user_id: str) -> dict[str, object]:
        """在 owner 校验下删除 resume result；删除失败或资源不可见时保持幂等的业务错误语义。

        Args:
            result_id: result 标识。
            user_id: 当前用户标识。
        """
        success = await get_resume_repo().delete_result(result_id, user_id)
        if not success:
            raise ResumeHistoryNotFound(message="结果不存在或无权删除")
        return {"success": True, "message": "删除成功"}


resume_history_use_cases = ResumeHistoryUseCases()
