"""评测 Suite 子域用例：owner-scoped 套件创建与列表。"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluations import EvaluationSuiteCreateRequest

from ai.workflows.evaluation.serializers import _suite
from ai.workflows.evaluation.contracts import EvaluationUseCaseError


class SuiteUseCasesMixin:
    """Suite 子域应用用例：创建与查询当前用户套件。"""

    async def create_suite(
        self, *, user_id: str, request: EvaluationSuiteCreateRequest
    ) -> dict[str, Any]:
        """创建 owner-scoped Evaluation Suite。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                row = await self.repository.create_suite(
                    uow.db, user_id=user_id, request=request
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            return _suite(row)

    async def list_suites(self, *, user_id: str) -> dict[str, Any]:
        """列出当前用户套件。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows = await self.repository.list_suites(uow.db, user_id=user_id)
            return {"items": [_suite(row) for row in rows], "total": len(rows)}
