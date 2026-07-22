"""面试会话管理用例。"""

from dataclasses import dataclass
import uuid

from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.infrastructure.db.repositories.session.session_repo import SessionRepo
from app.schemas.session import SessionCreateRequest, SessionUpdateRequest


@dataclass(slots=True)
class SessionManagementUseCaseError(Exception):
    """会话管理用例异常。"""

    message: str


class SessionManagementNotFound(SessionManagementUseCaseError):
    """会话不存在或无权访问。"""


class SessionManagementPersistenceError(SessionManagementUseCaseError):
    """会话持久化失败。"""


class SessionManagementUseCases:
    """会话基础管理应用服务。"""

    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._session_repo = SessionRepo()

    async def create_session(self, *, request: SessionCreateRequest, user_id: str):
        """创建 `session`。

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
            user_id=user_id,
        )

    async def list_sessions(self, *, status: str | None, mode: str | None, limit: int, offset: int, user_id: str):
        """列出 `sessions`。

        Args:
            status: 调用方传入的 `status` 参数。
            mode: 调用方传入的 `mode` 参数。
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
        """获取 `session`。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在")
        return session

    async def update_session(self, *, session_id: str, request: SessionUpdateRequest, user_id: str):
        """更新 `session`。

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
        """删除 `session`。

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
        """新增 `message`。

        Args:
            session_id: 会话标识。
            role: 调用方传入的 `role` 参数。
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

    async def create_next_round(self, *, session_id: str, max_questions: int | None, user_id: str, round_type: str | None = None):
        """创建 `next round`。

        Args:
            session_id: 会话标识。
            max_questions: 调用方传入的 `max_questions` 参数。
            user_id: 当前用户标识。
            round_type: 调用方传入的 `round_type` 参数。
        """
        if round_type is not None:
            round_type = resolve_round_type(round_type)
            max_questions = resolve_max_questions(round_type, max_questions)
        return await self._session_repo.create_next_round(
            parent_session_id=session_id,
            max_questions=max_questions,
            round_type=round_type,
            user_id=user_id,
        )


session_management_use_cases = SessionManagementUseCases()
