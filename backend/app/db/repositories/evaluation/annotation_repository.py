"""Evaluation 人工标注与校准持久化。"""

from __future__ import annotations

from typing import Any

from app.db.models import EvaluationAnnotationModel, EvaluationCalibrationModel, EvaluationCaseRunModel, EvaluationRunModel, EvaluationScoreModel
from app.schemas.evaluation.evaluations import EvaluationAnnotationCreateRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .helpers import _id, _now


class AnnotationRepositoryMixin:
    """按关注点拆分的 EvaluationRepository 行为。"""

    async def add_annotation(
            self,
            session: AsyncSession,
            *,
            case_run_id: str,
            user_id: str,
            request: EvaluationAnnotationCreateRequest,
            adjudication: bool = False,
        ) -> EvaluationAnnotationModel:
            """验证案例 owner 后追加 revision，不更新或删除历史标注。

            Args:
                session: 数据库会话或会话数据。
                case_run_id: 案例运行 ID。
                user_id: 用户 ID，所有者范围限定。
                request: 请求对象。
                adjudication: 传入的 adjudication 值。
            """

            if await self.get_case_run(session, case_run_id=case_run_id, user_id=user_id) is None:
                raise LookupError("case run not found")
            latest = await session.scalar(
                select(func.max(EvaluationAnnotationModel.revision)).where(
                    EvaluationAnnotationModel.case_run_id == case_run_id
                )
            )
            row = EvaluationAnnotationModel(
                id=_id("eann"),
                case_run_id=case_run_id,
                annotator_user_id=user_id,
                reviewer_key=request.reviewer_key or "reviewer-default",
                blind=request.blind,
                rubric_version=request.rubric_version,
                annotation_type=request.annotation_type,
                metric_name=request.metric_name,
                value={"value": request.value},
                labels=request.labels,
                evidence_spans=[item.model_dump(mode="json") for item in request.evidence_spans],
                comment_sanitized=request.comment,
                confidence=request.confidence,
                revision=int(latest or 0) + 1,
                adjudication=adjudication,
                created_at=_now(),
            )
            session.add(row)
            await session.flush()
            score_value: float | None = None
            raw_value = request.value
            if isinstance(raw_value, bool):
                score_value = 1.0 if raw_value else 0.0
            elif isinstance(raw_value, (int, float)):
                score_value = float(raw_value)
            session.add(
                EvaluationScoreModel(
                    id=_id("escore"),
                    case_run_id=case_run_id,
                    metric_name=request.metric_name,
                    value=score_value,
                    status=(
                        "passed"
                        if score_value is not None and score_value >= 0.5
                        else "failed"
                        if score_value is not None
                        else "not_applicable"
                    ),
                    source="human",
                    reason_sanitized=(
                        "expert_adjudication" if adjudication else "blind_human_review"
                    ),
                    severity="info",
                    hard_gate=False,
                    evidence_refs=[
                        f"annotation:{row.id}",
                        *[f"span:{item.start}-{item.end}" for item in request.evidence_spans],
                    ],
                    metric_version=f"human-r{row.revision}",
                    created_at=_now(),
                )
            )
            if adjudication:
                case_run = await self.get_case_run(
                    session, case_run_id=case_run_id, user_id=user_id
                )
                if case_run is not None:
                    case_run.needs_review = False
            await session.flush()
            return row

    async def list_annotations(
            self,
            session: AsyncSession,
            *,
            case_run_id: str,
            user_id: str,
        ) -> list[EvaluationAnnotationModel]:
            """按案例 owner 返回追加式标注历史。

            Args:
                session: 会话数据或数据库会话。
                case_run_id: 案例运行 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            if await self.get_case_run(session, case_run_id=case_run_id, user_id=user_id) is None:
                raise LookupError("case run not found")
            rows = await session.scalars(
                select(EvaluationAnnotationModel)
                .where(EvaluationAnnotationModel.case_run_id == case_run_id)
                .order_by(EvaluationAnnotationModel.revision)
            )
            return list(rows)

    async def get_annotation(
            self,
            session: AsyncSession,
            *,
            annotation_id: str,
            user_id: str,
        ) -> EvaluationAnnotationModel | None:
            """通过案例运行 owner 读取标注，避免跨用户存在性泄漏。

            Args:
                session: 会话数据或数据库会话。
                annotation_id: annotation 的 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            return await session.scalar(
                select(EvaluationAnnotationModel)
                .join(
                    EvaluationCaseRunModel,
                    EvaluationCaseRunModel.id == EvaluationAnnotationModel.case_run_id,
                )
                .join(
                    EvaluationRunModel,
                    EvaluationRunModel.id
                    == EvaluationCaseRunModel.evaluation_run_id,
                )
                .where(
                    EvaluationAnnotationModel.id == annotation_id,
                    EvaluationRunModel.user_id == user_id,
                )
            )

    async def create_calibration(
            self,
            session: AsyncSession,
            *,
            user_id: str,
            metric_name: str,
            judge_version: str,
            dataset_version: str,
            sample_count: int,
            statistics: dict[str, Any],
            threshold: float | None,
        ) -> EvaluationCalibrationModel:
            """保存不可变 Calibration Version。

            Args:
                session: 数据库会话或会话数据。
                user_id: 用户 ID，所有者范围限定。
                metric_name: 指标名称。
                judge_version: 传入的 judge_version 值。
                dataset_version: 传入的 dataset_version 值。
                sample_count: sample 的数量。
                statistics: 传入的 statistics 值。
                threshold: 阈值。
            """

            row = EvaluationCalibrationModel(
                id=_id("ecal"),
                user_id=user_id,
                metric_name=metric_name,
                judge_version=judge_version,
                dataset_version=dataset_version,
                human_sample_count=sample_count,
                statistics=statistics,
                threshold=threshold,
                status="draft",
                created_at=_now(),
            )
            session.add(row)
            await session.flush()
            return row

    async def list_calibrations(
            self, session: AsyncSession, *, user_id: str
        ) -> list[EvaluationCalibrationModel]:
            """列出当前 owner 的 Calibration 历史。

            Args:
                session: 会话数据或数据库会话。
                user_id: 用户 ID，所有者范围限定。
            """

            return list(
                await session.scalars(
                    select(EvaluationCalibrationModel)
                    .where(EvaluationCalibrationModel.user_id == user_id)
                    .order_by(EvaluationCalibrationModel.created_at.desc())
                )
            )

    async def get_calibration(
            self,
            session: AsyncSession,
            *,
            calibration_id: str,
            user_id: str,
        ) -> EvaluationCalibrationModel | None:
            """按 owner 获取一个不可变 Calibration Version。

            Args:
                session: 会话数据或数据库会话。
                calibration_id: calibration 的 ID。
                user_id: 用户 ID，所有者范围限定。
            """

            return await session.scalar(
                select(EvaluationCalibrationModel).where(
                    EvaluationCalibrationModel.id == calibration_id,
                    EvaluationCalibrationModel.user_id == user_id,
                )
            )
