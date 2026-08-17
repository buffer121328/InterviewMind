"""评测 Gate 子域用例：发布门禁策略、硬门禁检查与 Prompt 发布验证。"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluation.evaluations import EvaluationGatePolicyCreateRequest

from ai.workflows.evaluation.analytics import (
    _is_unacceptable_regression,
    _passes_threshold,
)
from ai.workflows.evaluation.serializers import _gate
from ai.workflows.evaluation.contracts import EvaluationUseCaseError


class GateUseCasesMixin:
    """Gate 子域应用用例：策略版本、硬门禁结果与 Prompt 发布治理。"""

    async def create_gate_policy(
        self, *, user_id: str, request: EvaluationGatePolicyCreateRequest
    ) -> dict[str, Any]:
        """创建 Gate Policy Version。

        Args:
            user_id: 当前用户标识。
            request: 门禁策略创建请求。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.create_gate_policy(
                uow.db, user_id=user_id, request=request
            )
            return _gate(row)

    async def list_gate_policies(self, *, user_id: str) -> dict[str, Any]:
        """列出 Gate Policy Versions。

        Args:
            user_id: 当前用户标识。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows = await self.repository.list_gate_policies(uow.db, user_id=user_id)
            return {"items": [_gate(row) for row in rows], "total": len(rows)}

    async def gate_check(
        self,
        *,
        user_id: str,
        run_id: str,
        policy_id: str | None = None,
    ) -> dict[str, Any]:
        """检查硬门禁、最低样本量和汇总指标，并追加不可变 Gate Result。

        Args:
            user_id: 当前用户标识。
            run_id: 目标评测运行标识。
            policy_id: 可选的门禁策略标识，缺省使用套件默认策略。
        """

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            run = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if run is None:
                self._not_found("评测运行不存在或无权访问")
            suite = await self.repository.get_suite(
                uow.db, suite_id=run.suite_id, user_id=user_id
            )
            selected_policy_id = policy_id or (suite.gate_policy_id if suite else None)
            if not selected_policy_id:
                raise EvaluationUseCaseError("评测套件未配置 Gate Policy", 409)
            policy = await self.repository.get_gate_policy(
                uow.db, policy_id=selected_policy_id, user_id=user_id
            )
            if policy is None:
                self._not_found("Gate Policy 不存在或无权访问")
            blocked: set[str] = set()
            if getattr(run, "status", "succeeded") != "succeeded" or not bool(
                run.summary.get("complete_success")
            ):
                blocked.add("evaluation_run_incomplete")
            if bool(run.summary.get("budget_exhausted")):
                blocked.add("evaluation_budget_exhausted")
            if int(run.summary.get("hard_gate_failure_count") or 0) > 0:
                blocked.add("hard_gates")
            sample_size = int(run.summary.get("completed_count") or 0)
            if sample_size < policy.minimum_sample_size:
                blocked.add("minimum_sample_size")
            metrics = dict(run.summary.get("metrics") or {})
            for name, threshold_config in policy.metric_thresholds.items():
                value = metrics.get(name)
                if value is None or not _passes_threshold(value, threshold_config):
                    blocked.add(name)
            baseline_comparison = dict(run.summary.get("baseline_comparison") or {})
            metric_deltas = dict(baseline_comparison.get("metric_deltas") or {})
            for name, tolerance_config in policy.regression_tolerances.items():
                delta = metric_deltas.get(name)
                if delta is None or _is_unacceptable_regression(
                    delta, tolerance_config
                ):
                    blocked.add(f"regression:{name}")
            for hard_gate_name in policy.hard_gates:
                hard_gate_values = dict(run.summary.get("hard_gates") or {})
                if hard_gate_values.get(hard_gate_name) is not True:
                    blocked.add(hard_gate_name)
            result = await self.repository.save_gate_result(
                uow.db,
                user_id=user_id,
                run_id=run.id,
                policy_id=policy.id,
                passed=not blocked,
                blocked_by=sorted(blocked),
                details={
                    "sample_size": sample_size,
                    "minimum_sample_size": policy.minimum_sample_size,
                    "metrics": metrics,
                    "baseline_comparison": baseline_comparison,
                    "hard_gates": dict(run.summary.get("hard_gates") or {}),
                    "hard_gate_evidence": dict(
                        run.summary.get("hard_gate_evidence") or {}
                    ),
                    "mode": get_settings().evaluation_release_gate_mode,
                },
            )
            return {
                "id": result.id,
                "passed": result.passed,
                "blocked_by": result.blocked_by,
                "details": result.details,
            }

    async def validate_prompt_promotion(
        self,
        *,
        user_id: str,
        prompt_name: str,
        prompt_version: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """按 off/warn/enforce 检查 Prompt 版本最近的不可变 Gate Result。

        Args:
            user_id: 当前用户标识。
            prompt_name: Prompt 名称。
            prompt_version: Prompt 版本号。
            run_id: 可选的目标评测运行标识。
        """

        mode = get_settings().evaluation_release_gate_mode
        if mode == "off":
            return {"mode": mode, "allowed": True, "warning": None}
        async with UnitOfWork(async_session) as uow:
            result = await self.repository.latest_gate_result_for_prompt(
                uow.db,
                user_id=user_id,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                run_id=run_id,
            )
        passed = result is not None and result.passed
        if mode == "enforce" and not passed:
            raise EvaluationUseCaseError(
                "Prompt 发布被评测门禁阻止：缺少通过的 Gate Result",
                status_code=409,
            )
        warning = None if passed else "当前 Prompt 版本没有通过的 Gate Result"
        return {
            "mode": mode,
            "allowed": True,
            "warning": warning,
            "gate_result_id": result.id if result else None,
        }
