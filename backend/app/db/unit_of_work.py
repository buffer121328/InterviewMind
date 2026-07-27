"""轻量 Unit of Work，用于应用层统一事务边界。"""

from __future__ import annotations

from types import TracebackType
from typing import Callable, Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import async_session


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
        """初始化 `UnitOfWork` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端仅在后续方法调用时承担对应的访问边界。

        Args:
            session_factory: 经过类型边界校验的 `session_factory`；其格式和可选值由参数类型及调用流程约束。
        """
        self._session_factory = session_factory
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        """异步进入上下文管理器并返回可用资源。"""
        self.session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        """异步退出上下文管理器并释放相关资源。

        Args:
            exc_type: 经过类型边界校验的 `exc_type`；其格式和可选值由参数类型及调用流程约束。
            exc: 经过类型边界校验的 `exc`；其格式和可选值由参数类型及调用流程约束。
            tb: 经过类型边界校验的 `tb`；其格式和可选值由参数类型及调用流程约束。
        """
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
        """返回 `db` 属性值。"""
        if self.session is None:
            raise RuntimeError("UnitOfWork 尚未进入上下文")
        return self.session
