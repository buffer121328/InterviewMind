"""评测 Dataset 子域用例：owner 边界、版本状态机与内置套件保障。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.evaluation.contracts import EvaluationUseCaseError
from ai.workflows.evaluation.serializers import _dataset, _dataset_case
from app.clock import utc_now
from app.db.models import EvaluationSuiteModel, async_session
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluation.evaluations import (
    EvaluationDatasetCreateRequest,
    EvaluationDatasetStatusRequest,
    EvaluationSuiteCreateRequest,
)
from app.security.payload_crypto import TaskPayloadConfigurationError
from evaluation.builtins import BuiltinEvaluationAgent, BuiltinEvaluationScope


class DatasetUseCasesMixin:
    """Dataset 子域应用用例：创建、查询、锁定与内置套件幂等保障。"""

    async def create_dataset(
        self, *, user_id: str, request: EvaluationDatasetCreateRequest
    ) -> dict[str, Any]:
        """创建加密 Dataset Version。

        Args:
            user_id: 当前用户标识。
            request: 数据集创建请求（含名称、版本与案例）。
        """

        self._ensure_center_enabled()
        try:
            async with UnitOfWork(async_session) as uow:
                row = await self.repository.create_dataset(
                    uow.db, user_id=user_id, request=request
                )
                return _dataset(row)
        except TaskPayloadConfigurationError as exc:
            raise EvaluationUseCaseError(str(exc), status_code=503) from exc

    async def list_datasets(
        self, *, user_id: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """分页返回 Dataset 元数据，不返回案例正文。

        Args:
            user_id: 当前用户标识。
            limit: 分页大小。
            offset: 分页偏移。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows, total = await self.repository.list_datasets(
                uow.db, user_id=user_id, limit=limit, offset=offset
            )
            return {
                "items": [_dataset(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def get_dataset(self, *, user_id: str, dataset_id: str) -> dict[str, Any]:
        """返回 Dataset Version 和不含明文载荷的案例目录。

        Args:
            user_id: 当前用户标识。
            dataset_id: 目标数据集标识。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.get_dataset(
                uow.db, dataset_id=dataset_id, user_id=user_id
            )
            if row is None:
                self._not_found("数据集不存在或无权访问")
            try:
                cases = await self.repository.list_dataset_cases(
                    uow.db, dataset_id=dataset_id, user_id=user_id
                )
            except LookupError:
                self._not_found("数据集不存在或无权访问")
            payload = _dataset(row)
            payload["cases"] = [_dataset_case(case) for case in cases]
            return payload

    async def lock_dataset(self, *, user_id: str, dataset_id: str) -> dict[str, Any]:
        """锁定 calibrated Dataset Version。

        Args:
            user_id: 当前用户标识。
            dataset_id: 目标数据集标识。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                row = await self.repository.lock_dataset(
                    uow.db, dataset_id=dataset_id, user_id=user_id
                )
            except ValueError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=409) from exc
            if row is None:
                self._not_found("数据集不存在或无权访问")
            return _dataset(row)

    async def update_dataset_status(
        self,
        *,
        user_id: str,
        dataset_id: str,
        request: EvaluationDatasetStatusRequest,
    ) -> dict[str, Any]:
        """按单向状态机推进 Dataset Version 生命周期。

        Args:
            user_id: 当前用户标识。
            dataset_id: 目标数据集标识。
            request: 状态更新请求。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                row = await self.repository.update_dataset_status(
                    uow.db,
                    dataset_id=dataset_id,
                    user_id=user_id,
                    status=request.status,
                )
            except ValueError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=409) from exc
            if row is None:
                self._not_found("数据集不存在或无权访问")
            return _dataset(row)

    async def _ensure_builtin_suite(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent: BuiltinEvaluationAgent,
        scope: BuiltinEvaluationScope,
    ) -> EvaluationSuiteModel:
        """幂等创建并锁定 owner 专属内置数据集与套件，不覆盖同名手工资产。

        Args:
            session: 当前数据库会话。
            user_id: 当前用户标识。
            agent: 内置评测 Agent 定义（数据集/套件名称与版本）。
        """

        dataset = await self.repository.get_dataset_by_name_version(
            session,
            user_id=user_id,
            name=scope.dataset_name,
            version=scope.dataset_version,
        )
        if dataset is None:
            dataset = await self.repository.create_dataset(
                session,
                user_id=user_id,
                request=EvaluationDatasetCreateRequest(
                    name=scope.dataset_name,
                    version=scope.dataset_version,
                    source="builtin",
                    cases=list(scope.cases),
                ),
            )
        elif dataset.source != "builtin":
            raise EvaluationUseCaseError(
                "内置评测数据集名称已被手工资产占用，请在高级模式中重命名该资产",
                status_code=409,
            )

        if dataset.status in {"draft", "annotating"}:
            dataset = await self.repository.update_dataset_status(
                session,
                dataset_id=dataset.id,
                user_id=user_id,
                status="calibrated",
            )
        if dataset is None:
            self._not_found("内置评测数据集创建失败")
        if dataset.status == "calibrated":
            dataset = await self.repository.lock_dataset(
                session,
                dataset_id=dataset.id,
                user_id=user_id,
            )
        if dataset is None or dataset.status != "locked":
            raise EvaluationUseCaseError(
                "内置评测数据集已停用，请在高级模式中检查数据集状态",
                status_code=409,
            )

        suite = await self.repository.get_suite_by_name(
            session,
            user_id=user_id,
            name=scope.suite_name,
        )
        if suite is None:
            return await self.repository.create_suite(
                session,
                user_id=user_id,
                request=EvaluationSuiteCreateRequest(
                    name=scope.suite_name,
                    agent_name=agent.name,
                    description=f"系统内置 {scope.name}：{agent.description}",
                    dataset_version_id=dataset.id,
                    rubric_version=scope.rubric_version,
                ),
            )
        if suite.dataset_version_id != dataset.id:
            previous_dataset = await self.repository.get_dataset(
                session,
                dataset_id=suite.dataset_version_id,
                user_id=user_id,
            )
            if previous_dataset is not None and previous_dataset.source == "builtin":
                if previous_dataset.status != "retired":
                    await self.repository.update_dataset_status(
                        session,
                        dataset_id=previous_dataset.id,
                        user_id=user_id,
                        status="retired",
                    )
                suite.dataset_version_id = dataset.id
                suite.agent_name = agent.name
                suite.rubric_version = scope.rubric_version
                suite.description = f"系统内置 {scope.name}：{agent.description}"
                suite.updated_at = utc_now()
                await session.flush()
                return suite
        if (
            suite.agent_name != agent.name
            or suite.dataset_version_id != dataset.id
            or suite.rubric_version != scope.rubric_version
        ):
            raise EvaluationUseCaseError(
                "内置评测套件名称已被其他配置占用，请在高级模式中重命名该套件",
                status_code=409,
            )
        return suite
