"""Evaluation 发布门禁策略与结果持久化。"""

from __future__ import annotations

from typing import Any, Sequence

from app.db.models import EvaluationGatePolicyModel, EvaluationGateResultModel, EvaluationRunModel
from app.schemas.evaluations import EvaluationGatePolicyCreateRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .helpers import _id, _now


class GateRepositoryMixin:
    """按关注点拆分的 EvaluationRepository 行为。"""

    async def create_gate_policy(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            request: EvaluationGatePolicyCreateRequest,
        ) -> EvaluationGatePolicyModel:
            """创建版本化 Gate Policy。"""

            metric_thresholds = {
                name: (
                    value.model_dump(mode="json")
                    if hasattr(value, "model_dump")
                    else value
                )
                for name, value in request.metric_thresholds.items()
            }
            regression_tolerances = {
                name: (
                    value.model_dump(mode="json")
                    if hasattr(value, "model_dump")
                    else value
                )
                for name, value in request.regression_tolerances.items()
            }
            row = EvaluationGatePolicyModel(
                id=_id("egate"),
                user_id=user_id,
                name=request.name,
                version=request.version,
                hard_gates=request.hard_gates,
                metric_thresholds=metric_thresholds,
                regression_tolerances=regression_tolerances,
                minimum_sample_size=request.minimum_sample_size,
                status=request.status,
                created_at=_now(),
            )
            session.add(row)
            await session.flush()
            return row

    async def get_gate_policy(
            self,
            session: AsyncSession,
            *,
            policy_id: str,
            user_id: str,
        ) -> EvaluationGatePolicyModel | None:
            """按 owner 获取 Gate Policy。"""

            return await session.scalar(
                select(EvaluationGatePolicyModel).where(
                    EvaluationGatePolicyModel.id == policy_id,
                    EvaluationGatePolicyModel.user_id == user_id,
                )
            )

    async def list_gate_policies(
            self, session: AsyncSession, *, user_id: str
        ) -> list[EvaluationGatePolicyModel]:
            """列出当前 owner 的 Gate Policy。"""

            return list(
                await session.scalars(
                    select(EvaluationGatePolicyModel)
                    .where(EvaluationGatePolicyModel.user_id == user_id)
                    .order_by(EvaluationGatePolicyModel.created_at.desc())
                )
            )

    async def save_gate_result(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            run_id: str,
            policy_id: str,
            passed: bool,
            blocked_by: Sequence[str],
            details: dict[str, Any],
        ) -> EvaluationGateResultModel:
            """追加不可变 Gate Result，供 Prompt 发布审计。"""

            row = EvaluationGateResultModel(
                id=_id("egresult"),
                user_id=user_id,
                evaluation_run_id=run_id,
                gate_policy_id=policy_id,
                passed=passed,
                blocked_by=list(blocked_by),
                details=details,
                created_at=_now(),
            )
            session.add(row)
            await session.flush()
            return row

    async def latest_gate_result_for_prompt(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            prompt_name: str,
            prompt_version: str,
            run_id: str | None = None,
        ) -> EvaluationGateResultModel | None:
            """返回指定 Prompt 版本最近一次 owner-scoped 门禁结果。"""

            statement = (
                select(EvaluationGateResultModel)
                .join(
                    EvaluationRunModel,
                    EvaluationRunModel.id == EvaluationGateResultModel.evaluation_run_id,
                )
                .where(
                    EvaluationGateResultModel.user_id == user_id,
                    EvaluationRunModel.user_id == user_id,
                    EvaluationRunModel.prompt_name == prompt_name,
                    EvaluationRunModel.prompt_version == prompt_version,
                )
                .order_by(EvaluationGateResultModel.created_at.desc())
            )
            if run_id is not None:
                statement = statement.where(
                    EvaluationGateResultModel.evaluation_run_id == run_id
                )
            return await session.scalar(statement.limit(1))
