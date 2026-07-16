"""轻量 Unit of Work，用于应用层统一事务边界。"""

from __future__ import annotations

from types import TracebackType
from typing import Callable, Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import async_session


class UnitOfWork:
    """围绕一个 AsyncSession 管理 commit/rollback/close。

    用法：

    ```python
    async with UnitOfWork() as uow:
        uow.session.add(model)
    ```

    正常退出自动 commit，异常退出自动 rollback。Repository 迁移时可以把
    `uow.session` 显式传入，避免多个 Service/Repo 各自提交。
    """

    def __init__(self, session_factory: Callable[[], AsyncSession] = async_session):
        self._session_factory = session_factory
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        if self.session is None:
            return False
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
        return False

    @property
    def db(self) -> AsyncSession:
        if self.session is None:
            raise RuntimeError("UnitOfWork 尚未进入上下文")
        return self.session
