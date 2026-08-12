"""评测 Calibration 子域用例：不可变校准版本与阈值回放。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.config import get_settings
from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluations import (
    EvaluationCalibrationCreateRequest,
    EvaluationCalibrationSimulateRequest,
)
from evaluation.domain import calculate_calibration

from ai.workflows.evaluation.serializers import _calibration
from ai.workflows.evaluation.contracts import EvaluationUseCaseError


class CalibrationUseCasesMixin:
    """Calibration 子域应用用例：创建、列表与无副作用阈值回放。"""

    async def create_calibration(
        self,
        *,
        user_id: str,
        request: EvaluationCalibrationCreateRequest,
    ) -> dict[str, Any]:
        """计算并保存不可变 Calibration Version。"""

        self._ensure_center_enabled()
        try:
            result = calculate_calibration(
                judge_scores=request.judge_scores,
                human_scores=request.human_scores,
                judge_binary=request.judge_binary,
                human_binary=request.human_binary,
                severe_mask=request.severe_mask,
            )
        except ValueError as exc:
            raise EvaluationUseCaseError(str(exc)) from exc
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.create_calibration(
                uow.db,
                user_id=user_id,
                metric_name=request.metric_name,
                judge_version=request.judge_version,
                dataset_version=request.dataset_version,
                sample_count=result.sample_count,
                statistics=asdict(result),
                threshold=request.threshold,
            )
            return _calibration(row)

    async def list_calibrations(self, *, user_id: str) -> dict[str, Any]:
        """列出 Calibration 历史。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows = await self.repository.list_calibrations(uow.db, user_id=user_id)
            return {"items": [_calibration(row) for row in rows], "total": len(rows)}

    async def simulate_calibration(
        self,
        *,
        user_id: str,
        calibration_id: str,
        request: EvaluationCalibrationSimulateRequest,
    ) -> dict[str, Any]:
        """回放阈值对假阳性、假阴性和通过率的影响，不写生产配置。"""

        self._ensure_center_enabled()
        if len(request.scores) != len(request.expected_pass):
            raise EvaluationUseCaseError("scores 与 expected_pass 长度不一致")
        async with UnitOfWork(async_session) as uow:
            calibration = await self.repository.get_calibration(
                uow.db, calibration_id=calibration_id, user_id=user_id
            )
            if calibration is None:
                self._not_found("Calibration 不存在或无权访问")
        predicted = [score >= request.threshold for score in request.scores]
        false_positive = sum(p and not e for p, e in zip(predicted, request.expected_pass))
        false_negative = sum(not p and e for p, e in zip(predicted, request.expected_pass))
        return {
            "threshold": request.threshold,
            "sample_count": len(predicted),
            "pass_rate": sum(predicted) / len(predicted),
            "false_positive_count": false_positive,
            "false_negative_count": false_negative,
        }
