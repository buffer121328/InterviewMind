"""面试聊天会话辅助用例。"""

from dataclasses import dataclass

from ai.agents.interview.answer_points import answer_points_hint
from app.db.repositories.session.session_repo import SessionRepo
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
        """初始化 `InterviewSessionUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()

    async def get_hint(self, *, session_id: str, question_index: int, user_id: str) -> dict[str, object]:
        """读取 hint，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            question_index: 经过类型边界校验的 `question_index`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise InterviewSessionNotFound(message="会话不存在或无权访问")

        plan = await self._session_repo.get_interview_plan(session_id)
        if not plan:
            raise InterviewSessionNotFound(message="面试计划不存在")
        if question_index < 0 or question_index >= len(plan):
            raise InterviewSessionNotFound(message="问题索引超出范围")

        question = plan[question_index]
        hint = answer_points_hint(question)
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

    async def rollback_chat(self, *, request: RollbackRequest, user_id: str) -> dict[str, object]:
        """将聊天会话回滚到指定消息边界，并按 owner 校验避免跨用户修改。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        success = await self._session_repo.rollback_session(
            request.thread_id,
            request.index,
            user_id=user_id,
        )
        if not success:
            raise InterviewSessionNotFound(message="Session or message not found")
        return {"success": True, "message": f"会话已回退至索引 {request.index}", "thread_id": request.thread_id}


interview_session_use_cases = InterviewSessionUseCases()
