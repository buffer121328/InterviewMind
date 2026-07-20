"""面试聊天会话辅助用例。"""

from dataclasses import dataclass

from app.infrastructure.db.repositories.session.session_repo import SessionRepo
from app.schemas.schemas import RollbackRequest


@dataclass(slots=True)
class InterviewSessionUseCaseError(Exception):
    """面试会话辅助用例异常。"""

    message: str


class InterviewSessionNotFound(InterviewSessionUseCaseError):
    """面试会话资源不存在或无权访问。"""


class InterviewSessionUseCases:
    """面试聊天会话辅助应用服务。"""

    def __init__(self) -> None:
        self._session_repo = SessionRepo()

    async def get_hint(self, *, session_id: str, question_index: int, user_id: str) -> dict[str, object]:
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise InterviewSessionNotFound(message="会话不存在或无权访问")

        plan = await self._session_repo.get_interview_plan(session_id)
        if not plan:
            raise InterviewSessionNotFound(message="面试计划不存在")
        if question_index < 0 or question_index >= len(plan):
            raise InterviewSessionNotFound(message="问题索引超出范围")

        question = plan[question_index]
        hint = question.get("hint")
        if not hint:
            return {
                "success": True,
                "generating": True,
                "hint": "提示正在生成中，请稍后再试...",
                "topic": question.get("topic", ""),
                "question": question.get("content", ""),
            }
        return {
            "success": True,
            "generating": False,
            "hint": hint,
            "topic": question.get("topic", ""),
            "question": question.get("content", ""),
        }

    async def get_chat_status(self, *, thread_id: str) -> dict[str, object]:
        return {"success": True, "thread_id": thread_id, "status": "active"}

    async def end_chat_session(self, *, thread_id: str) -> dict[str, object]:
        return {"success": True, "message": f"会话 {thread_id} 已结束", "thread_id": thread_id}

    async def rollback_chat(self, *, request: RollbackRequest, user_id: str) -> dict[str, object]:
        success = await self._session_repo.rollback_session(
            request.thread_id,
            request.index,
            user_id=user_id,
        )
        if not success:
            raise InterviewSessionNotFound(message="Session or message not found")
        return {"success": True, "message": f"会话已回退至索引 {request.index}", "thread_id": request.thread_id}


interview_session_use_cases = InterviewSessionUseCases()
