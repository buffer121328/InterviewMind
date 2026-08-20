"""Evaluation 数据集与套件持久化。"""

from __future__ import annotations

from app.db.models import EvaluationCaseModel, EvaluationDatasetVersionModel, EvaluationSuiteModel
from app.schemas.evaluation.evaluations import EvaluationDatasetCreateRequest, EvaluationSuiteCreateRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .helpers import _hash, _id, _now


class DatasetRepositoryMixin:
    """按关注点拆分的 EvaluationRepository 行为。"""

    async def create_dataset(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            request: EvaluationDatasetCreateRequest,
        ) -> EvaluationDatasetVersionModel:
            """创建数据集版本和加密案例；同一 owner/name/version 由数据库拒绝重复。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
                request: 请求对象。
            """

            canonical_cases = [case.model_dump(mode="json") for case in request.cases]
            dataset = EvaluationDatasetVersionModel(
                id=_id("eds"),
                user_id=user_id,
                name=request.name,
                version=request.version,
                status="draft",
                case_count=len(request.cases),
                source=request.source,
                content_hash=_hash(canonical_cases),
                created_at=_now(),
                locked_at=None,
            )
            session.add(dataset)
            # 说明：PostgreSQL may enforce the child FK before a single mixed flush has
            # 说明：inserted the dataset row. Persist the parent identity first.
            await session.flush()
            for case in request.cases:
                session.add(self._case_model(dataset.id, case))
            await session.flush()
            return dataset


    async def list_datasets(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            limit: int,
            offset: int,
        ) -> tuple[list[EvaluationDatasetVersionModel], int]:
            """分页列出当前 owner 的数据集元数据，不解密案例正文。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
                limit: 返回数量上限。
                offset: 偏移量。
            """

            where = EvaluationDatasetVersionModel.user_id == user_id
            total = await session.scalar(
                select(func.count()).select_from(EvaluationDatasetVersionModel).where(where)
            )
            rows = await session.scalars(
                select(EvaluationDatasetVersionModel)
                .where(where)
                .order_by(EvaluationDatasetVersionModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(rows), int(total or 0)

    async def get_dataset(
            self,
            session: AsyncSession,
            *,
            dataset_id: str,
            user_id: str,
        ) -> EvaluationDatasetVersionModel | None:
            """按 owner 获取一个数据集版本。

            Args:
                session: 会话数据或数据库会话。
                dataset_id: dataset 的 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            return await session.scalar(
                select(EvaluationDatasetVersionModel).where(
                    EvaluationDatasetVersionModel.id == dataset_id,
                    EvaluationDatasetVersionModel.user_id == user_id,
                )
            )

    async def get_dataset_by_name_version(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            name: str,
            version: str,
        ) -> EvaluationDatasetVersionModel | None:
            """按 owner/name/version 精确读取数据集，供内置版本幂等引导使用。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
                name: 名称。
                version: 版本字符串。
            """

            return await session.scalar(
                select(EvaluationDatasetVersionModel).where(
                    EvaluationDatasetVersionModel.user_id == user_id,
                    EvaluationDatasetVersionModel.name == name,
                    EvaluationDatasetVersionModel.version == version,
                )
            )

    async def list_dataset_cases(
            self,
            session: AsyncSession,
            *,
            dataset_id: str,
            user_id: str,
        ) -> list[EvaluationCaseModel]:
            """按 owner 返回案例安全元数据；不解密输入和 Golden。

            Args:
                session: 会话数据或数据库会话。
                dataset_id: dataset 的 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            if await self.get_dataset(session, dataset_id=dataset_id, user_id=user_id) is None:
                raise LookupError("dataset not found")
            rows = await session.scalars(
                select(EvaluationCaseModel)
                .where(EvaluationCaseModel.dataset_version_id == dataset_id)
                .order_by(EvaluationCaseModel.case_key)
            )
            return list(rows)

    async def lock_dataset(
            self,
            session: AsyncSession,
            *,
            dataset_id: str,
            user_id: str,
        ) -> EvaluationDatasetVersionModel | None:
            """锁定 calibrated 数据集；锁定后 Repository 不提供原地案例修改入口。

            Args:
                session: 会话数据或数据库会话。
                dataset_id: dataset 的 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            dataset = await self.get_dataset(session, dataset_id=dataset_id, user_id=user_id)
            if dataset is None:
                return None
            if dataset.status not in {"calibrated", "locked"}:
                raise ValueError("only calibrated datasets can be locked")
            if dataset.status != "locked":
                dataset.status = "locked"
                dataset.locked_at = _now()
            await session.flush()
            return dataset

    async def update_dataset_status(
            self,
            session: AsyncSession,
            *,
            dataset_id: str,
            user_id: str,
            status: str,
        ) -> EvaluationDatasetVersionModel | None:
            """按单向状态机推进 Dataset Version 生命周期。

            Args:
                session: 会话数据或数据库会话。
                dataset_id: dataset 的 ID。
                user_id: 用户 ID，所有者范围限定。
                status: 状态字符串。
            """

            dataset = await self.get_dataset(session, dataset_id=dataset_id, user_id=user_id)
            if dataset is None:
                return None
            allowed = {
                "draft": {"annotating", "calibrated", "retired"},
                "annotating": {"calibrated", "retired"},
                "calibrated": {"retired"},
                "locked": {"retired"},
                "retired": set(),
            }
            if status == dataset.status:
                return dataset
            if status not in allowed.get(dataset.status, set()):
                raise ValueError(
                    f"dataset status transition {dataset.status} -> {status} is not allowed"
                )
            dataset.status = status
            await session.flush()
            return dataset

    async def create_suite(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            request: EvaluationSuiteCreateRequest,
        ) -> EvaluationSuiteModel:
            """创建套件前再次校验 Dataset 与 Gate Policy 所有权。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
                request: 请求对象。
            """

            dataset = await self.get_dataset(
                session, dataset_id=request.dataset_version_id, user_id=user_id
            )
            if dataset is None:
                raise LookupError("dataset not found")
            if request.gate_policy_id:
                gate = await self.get_gate_policy(
                    session, policy_id=request.gate_policy_id, user_id=user_id
                )
                if gate is None:
                    raise LookupError("gate policy not found")
            now = _now()
            suite = EvaluationSuiteModel(
                id=_id("esuite"),
                user_id=user_id,
                name=request.name,
                agent_name=request.agent_name,
                description=request.description,
                dataset_version_id=request.dataset_version_id,
                rubric_version=request.rubric_version,
                gate_policy_id=request.gate_policy_id,
                created_at=now,
                updated_at=now,
            )
            session.add(suite)
            await session.flush()
            return suite

    async def list_suites(
            self,
            session: AsyncSession,
            *,
            user_id: str,
        ) -> list[EvaluationSuiteModel]:
            """列出当前 owner 的套件。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
            """

            rows = await session.scalars(
                select(EvaluationSuiteModel)
                .where(EvaluationSuiteModel.user_id == user_id)
                .order_by(EvaluationSuiteModel.updated_at.desc())
            )
            return list(rows)

    async def get_suite(
            self,
            session: AsyncSession,
            *,
            suite_id: str,
            user_id: str,
        ) -> EvaluationSuiteModel | None:
            """按 owner 获取套件。

            Args:
                session: 会话数据或数据库会话。
                suite_id: 评测套件 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            return await session.scalar(
                select(EvaluationSuiteModel).where(
                    EvaluationSuiteModel.id == suite_id,
                    EvaluationSuiteModel.user_id == user_id,
                )
            )

    async def get_suite_by_name(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            name: str,
        ) -> EvaluationSuiteModel | None:
            """按 owner/name 精确读取套件，避免一键评测重复创建治理事实。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
                name: 名称。
            """

            return await session.scalar(
                select(EvaluationSuiteModel).where(
                    EvaluationSuiteModel.user_id == user_id,
                    EvaluationSuiteModel.name == name,
                )
            )
