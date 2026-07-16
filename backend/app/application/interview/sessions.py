"""面试会话管理用例。"""

from dataclasses import dataclass
import uuid

from app.repositories.session.session_repo import SessionRepo
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
        self._session_repo = SessionRepo()

    async def create_session(self, *, request: SessionCreateRequest, user_id: str):
        return await self._session_repo.create_session(
            session_id=str(uuid.uuid4()),
            mode=request.mode,
            title=request.title,
            resume_filename=request.resume_filename,
            job_description=request.job_description,
            max_questions=request.max_questions,
            user_id=user_id,
        )

    async def list_sessions(self, *, status: str | None, mode: str | None, limit: int, offset: int, user_id: str):
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
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在")
        return session

    async def update_session(self, *, session_id: str, request: SessionUpdateRequest, user_id: str):
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
        session = await self._session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在或无权访问")
        success = await self._session_repo.delete_session(session_id, user_id=user_id)
        if not success:
            raise SessionManagementPersistenceError(message=f"无法删除会话 {session_id}，请检查后台日志")

    async def add_message(self, *, session_id: str, role: str, content: str, user_id: str):
        session = await self._session_repo.add_message(
            session_id=session_id,
            role=role,
            content=content,
            user_id=user_id,
        )
        if session is None:
            raise SessionManagementNotFound(message=f"会话 {session_id} 不存在")
        return session

    async def create_next_round(self, *, session_id: str, max_questions: int, user_id: str):
        return await self._session_repo.create_next_round(
            parent_session_id=session_id,
            max_questions=max_questions,
            user_id=user_id,
        )


session_management_use_cases = SessionManagementUseCases()
