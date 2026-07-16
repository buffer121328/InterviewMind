"""简历历史与可用面试会话用例。"""

from dataclasses import dataclass
from typing import Literal

from app.repositories.resume.resume_repo import get_resume_repo
from app.repositories.session.session_repo import SessionRepo
from app.schemas.resume_schemas import (
    CompletedSessionItem,
    CompletedSessionsResponse,
    ResumeHistoryDetailResponse,
    ResumeHistoryListResponse,
)


@dataclass(slots=True)
class ResumeHistoryUseCaseError(Exception):
    """简历历史用例异常。"""

    message: str


class ResumeHistoryNotFound(ResumeHistoryUseCaseError):
    """历史结果不存在或用户无权访问。"""


class ResumeHistoryUseCases:
    """简历历史应用服务。"""

    def __init__(self) -> None:
        self._session_repo = SessionRepo()

    async def get_completed_sessions(self, *, user_id: str, limit: int) -> CompletedSessionsResponse:
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
        result = await get_resume_repo().get_result(result_id, user_id)
        if not result:
            raise ResumeHistoryNotFound(message="结果不存在")
        return ResumeHistoryDetailResponse(success=True, result=result)

    async def delete_resume_result(self, *, result_id: int, user_id: str) -> dict[str, object]:
        success = await get_resume_repo().delete_result(result_id, user_id)
        if not success:
            raise ResumeHistoryNotFound(message="结果不存在或无权删除")
        return {"success": True, "message": "删除成功"}


resume_history_use_cases = ResumeHistoryUseCases()
