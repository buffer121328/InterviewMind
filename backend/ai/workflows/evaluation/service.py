"""Agent 评测中心应用服务：owner 边界、生命周期和治理操作。

具体子域用例按主题拆分在 ``datasets`` / ``suites`` / ``runs`` /
``annotations`` / ``calibration`` / ``gates`` / ``reporting`` mixin 模块中，
本模块保留稳定错误类型、功能开关、catalog 与聚合 facade。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

from app.config import get_settings
from app.db.models import async_session
from app.db.repositories.evaluation import EvaluationRepository
from app.db.unit_of_work import UnitOfWork
from evaluation.builtins import public_evaluation_catalog


@dataclass(slots=True)
class EvaluationUseCaseError(Exception):
    """Evaluation 应用层稳定错误。"""

    message: str
    status_code: int = 400


from ai.workflows.evaluation.annotations import AnnotationUseCasesMixin
from ai.workflows.evaluation.calibration import CalibrationUseCasesMixin
from ai.workflows.evaluation.datasets import DatasetUseCasesMixin
from ai.workflows.evaluation.gates import GateUseCasesMixin
from ai.workflows.evaluation.reporting import (
    ReportingUseCasesMixin,
    _is_unacceptable_regression,
    _latest_agreement,
    _metric_average,
    _passes_threshold,
    _trend_point,
    _weighted_ratio,
    _weighted_success_rate,
)
from ai.workflows.evaluation.runs import RunUseCasesMixin
from ai.workflows.evaluation.suites import SuiteUseCasesMixin


class EvaluationUseCases(
    DatasetUseCasesMixin,
    SuiteUseCasesMixin,
    RunUseCasesMixin,
    AnnotationUseCasesMixin,
    CalibrationUseCasesMixin,
    GateUseCasesMixin,
    ReportingUseCasesMixin,
):
    """编排 Evaluation Repository、AgentRun 和领域规则。"""

    def __init__(self, repository: EvaluationRepository | None = None) -> None:
        """注入 Repository；默认使用 PostgreSQL owner-scoped 实现。"""

        self.repository = repository or EvaluationRepository()

    def _ensure_center_enabled(self) -> None:
        """评测中心关闭时拒绝业务读取，避免半启用功能。"""

        if not get_settings().evaluation_center_enabled:
            raise EvaluationUseCaseError("Agent 评测中心未启用", status_code=404)

    def _ensure_runs_enabled(self) -> None:
        """真实评测运行必须通过独立功能开关。"""

        self._ensure_center_enabled()
        if not get_settings().evaluation_runs_enabled:
            raise EvaluationUseCaseError("Agent 评测运行未启用", status_code=403)

    async def catalog(self, *, user_id: str) -> dict[str, Any]:
        """返回一键评测目录、服务端有效预算和 owner 最近成功基线。"""

        self._ensure_center_enabled()
        settings = get_settings()
        payload = public_evaluation_catalog()
        payload["runs_enabled"] = settings.evaluation_runs_enabled
        for mode in payload["modes"]:
            mode["max_concurrency"] = min(
                int(mode["max_concurrency"]), settings.evaluation_max_concurrency
            )
            mode["max_budget_usd"] = min(
                float(mode["max_budget_usd"]),
                settings.evaluation_default_max_budget_usd,
            )
        async with UnitOfWork(async_session) as uow:
            for agent in payload["agents"]:
                baseline = await self.repository.latest_successful_run_for_agent(
                    uow.db,
                    user_id=user_id,
                    agent_name=str(agent["name"]),
                )
                agent["latest_successful_run_id"] = baseline.id if baseline else None
        return payload

    @staticmethod
    def _not_found(message: str) -> NoReturn:
        """抛出不会泄露资源是否属于其他用户的 404。"""

        raise EvaluationUseCaseError(message, status_code=404)


evaluation_use_cases = EvaluationUseCases()
