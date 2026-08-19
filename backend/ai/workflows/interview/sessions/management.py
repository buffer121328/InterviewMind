"""面试会话管理用例。"""

import uuid
from dataclasses import dataclass

from app.db.repositories.session.session_repo import SessionRepo
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.schemas.interview.session import SessionCreateRequest, SessionUpdateRequest
from ai.workflows.interview.questions.regeneration import QuestionRegenerationError, regenerate_question


@dataclass(slots=True)
class SessionManagementUseCaseError(Exception):
    """会话管理用例异常。"""

    # 单条消息。
    # 单条消息。
    message: str


class SessionManagementNotFound(SessionManagementUseCaseError):
    """会话不存在或无权访问。"""


class SessionManagementPersistenceError(SessionManagementUseCaseError):
    """会话持久化失败。"""


class SessionManagementBadRequest(SessionManagementUseCaseError):
    """会话管理请求不合法。"""


class SessionManagementUseCases:
    """会话基础管理应用服务。"""

    def __init__(self) -> None:
        """初始化 `SessionManagementUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._session_repo = SessionRepo()

    async def create_session(self, *, request: SessionCreateRequest, user_id: str):
        """创建 session，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        return await self._session_repo.create_session(
            session_id=str(uuid.uuid4()),
            mode=request.mode,
            title=request.title,
            resume_filename=request.resume_filename,
            job_description=request.job_description,
            max_questions=request.max_questions,
            round_type=request.round_type,
            report_mode=request.report_mode,
            user_id=user_id,
        )

    async def list_sessions(self, *, status: str | None, mode: str | None, limit: int, offset: int, user_id: str):
        """按 owner、筛选条件和分页参数读取 sessions；仅返回当前调用方有权查看的持久化结果。

        Args:
            status: 经过类型边界校验的 `status`；其格式和可选值由参数类型及调用流程约束。
            mode: 经过类型边界校验的 `mode`；其格式和可选值由参数类型及调用流程约束。
            limit: 返回数量上限。
            offset: 分页偏移量。
            user_id: 当前用户标识。
        """
        sessions = await self._session_repo.list_sessions(
            status=status,
            mode=mode,
            limit=limit,
            offset=offset,
            user_id=user_id,
        )
        total = await self._session_repo.get_session_count(status=status, mode=mode, user_id=user_id)
        return sessions, total

    async def get_session(self, *, session_id: str, user_id: str):
        """读取 session，并通过 owner 校验限制可见范围；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在")
        return session

    async def update_session(self, *, session_id: str, request: SessionUpdateRequest, user_id: str):
        """在 owner 校验下更新 session；只写入允许变更的字段，避免绕过状态机或审批约束。

        Args:
            session_id: 会话标识。
            request: 请求对象。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.update_session(
            session_id=session_id,
            title=request.title,
            status=request.status,
            metadata_updates=request.metadata,
            user_id=user_id,
        )
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在")
        return session

    async def delete_session(self, *, session_id: str, user_id: str) -> None:
        """在 owner 校验下删除 session；删除失败或资源不可见时保持幂等的业务错误语义。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在或无权访问")
        success = await self._session_repo.delete_session(session_id, user_id=user_id)
        if not success:
            raise SessionManagementPersistenceError(message=f"无法删除会话 {session_id}，请检查后台日志")

    async def add_message(self, *, session_id: str, role: str, content: str, user_id: str):
        """把用户或模型消息追加到面试会话，并沿用会话 owner、顺序和持久化约束。

        Args:
            session_id: 会话标识。
            role: 经过类型边界校验的 `role`；其格式和可选值由参数类型及调用流程约束。
            content: 内容文本。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.add_message(
            session_id=session_id,
            role=role,
            content=content,
            user_id=user_id,
        )
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在")
        return session

    async def regenerate_question(
        self,
        *,
        session_id: str,
        question_index: int,
        reason: str | None,
        api_config: dict | None,
        user_id: str,
    ) -> dict:
        """在当前活动会话中替换尚未回答的主问题，不改变轮次进度。"""
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在或无权访问")
        if session.metadata.status != "active":
            raise SessionManagementBadRequest(message="面试已完成，不能重新生成题目")
        if question_index != session.metadata.question_count:
            raise SessionManagementBadRequest(message="只能重新生成当前待回答题目")
        try:
            replacement = await regenerate_question(
                session=session,
                question_index=question_index,
                reason=reason,
                api_config=api_config,
            )
        except QuestionRegenerationError as exc:
            raise SessionManagementBadRequest(message=str(exc)) from exc
        except Exception as exc:
            raise SessionManagementPersistenceError(message="题目重新生成失败，请稍后重试") from exc

        plan = [dict(item) for item in session.metadata.interview_plan]
        replacement["id"] = question_index + 1
        plan[question_index] = replacement
        if not await self._session_repo.replace_current_question(
            session_id=session_id,
            question_index=question_index,
            content=replacement["content"],
            plan=plan,
            user_id=user_id,
        ):
            raise SessionManagementPersistenceError(message="新题目保存失败，请稍后重试")
        return replacement

    async def create_next_round(self, *, session_id: str, max_questions: int | None, user_id: str, round_type: str | None = None):
        """创建 next round，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

        Args:
            session_id: 会话标识。
            max_questions: 经过类型边界校验的 `max_questions`；其格式和可选值由参数类型及调用流程约束。
            user_id: 当前用户标识。
            round_type: 经过类型边界校验的 `round_type`；其格式和可选值由参数类型及调用流程约束。
        """
        if round_type is not None:
            try:
                round_type = resolve_round_type(round_type)
                max_questions = resolve_max_questions(round_type, max_questions)
            except ValueError as exc:
                raise SessionManagementBadRequest(message=str(exc)) from exc
        try:
            return await self._session_repo.create_next_round(
                parent_session_id=session_id,
                max_questions=max_questions,
                round_type=round_type,
                user_id=user_id,
            )
        except ValueError as exc:
            raise SessionManagementBadRequest(message=str(exc)) from exc


session_management_use_cases = SessionManagementUseCases()
