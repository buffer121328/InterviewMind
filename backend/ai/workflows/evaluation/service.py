"""Agent 评测中心应用服务：owner 边界、生命周期和治理操作。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, NoReturn

from ai.runtime.agent_runs.crypto import TaskPayloadConfigurationError, decrypt_payload
from ai.workflows.agent_runs import AgentRunUseCaseError, agent_run_use_cases
from app.config import get_settings
from app.db.models import EvaluationSuiteModel, async_session
from app.db.repositories.evaluation import EvaluationRepository
from app.db.unit_of_work import UnitOfWork
from app.domain.agent_runs import TASK_TYPE_EVALUATION_SUITE
from app.schemas.evaluations import (
    EvaluationAdjudicationRequest,
    EvaluationAnnotationCreateRequest,
    EvaluationCalibrationCreateRequest,
    EvaluationCalibrationSimulateRequest,
    EvaluationCandidateDatasetRequest,
    EvaluationDatasetCreateRequest,
    EvaluationDatasetStatusRequest,
    EvaluationGatePolicyCreateRequest,
    EvaluationOnlineSampleRequest,
    EvaluationQuickRunRequest,
    EvaluationReviewRequest,
    EvaluationRunCreateRequest,
    EvaluationSuiteCreateRequest,
)
from evaluation.builtins import (
    BuiltinEvaluationAgent,
    get_builtin_agent,
    get_quick_mode,
    model_config_fingerprint,
    public_evaluation_catalog,
)
from evaluation.domain import calculate_calibration
from evaluation.online import sampling_decision, sanitize_production_trace
from evaluation.reporting import build_run_report, render_run_report_html
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class EvaluationUseCaseError(Exception):
    """Evaluation 应用层稳定错误。"""

    message: str
    status_code: int = 400


class EvaluationUseCases:
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

    async def create_dataset(
        self, *, user_id: str, request: EvaluationDatasetCreateRequest
    ) -> dict[str, Any]:
        """创建加密 Dataset Version。"""

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
        """分页返回 Dataset 元数据，不返回案例正文。"""

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
        """返回 Dataset Version 和不含明文载荷的案例目录。"""

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
        """锁定 calibrated Dataset Version。"""

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
        """按单向状态机推进 Dataset Version 生命周期。"""

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

    async def _ensure_builtin_suite(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent: BuiltinEvaluationAgent,
    ) -> EvaluationSuiteModel:
        """幂等创建并锁定 owner 专属内置数据集与套件，不覆盖同名手工资产。"""

        dataset = await self.repository.get_dataset_by_name_version(
            session,
            user_id=user_id,
            name=agent.dataset_name,
            version=agent.dataset_version,
        )
        if dataset is None:
            dataset = await self.repository.create_dataset(
                session,
                user_id=user_id,
                request=EvaluationDatasetCreateRequest(
                    name=agent.dataset_name,
                    version=agent.dataset_version,
                    source="builtin",
                    cases=list(agent.cases),
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
            name=agent.suite_name,
        )
        if suite is None:
            return await self.repository.create_suite(
                session,
                user_id=user_id,
                request=EvaluationSuiteCreateRequest(
                    name=agent.suite_name,
                    agent_name=agent.name,
                    description=f"系统内置：{agent.description}",
                    dataset_version_id=dataset.id,
                    rubric_version=agent.rubric_version,
                ),
            )
        if (
            suite.agent_name != agent.name
            or suite.dataset_version_id != dataset.id
            or suite.rubric_version != agent.rubric_version
        ):
            raise EvaluationUseCaseError(
                "内置评测套件名称已被其他配置占用，请在高级模式中重命名该套件",
                status_code=409,
            )
        return suite

    async def quick_run(
        self,
        *,
        user_id: str,
        request: EvaluationQuickRunRequest,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """把 Agent 与模式选择展开为受服务端约束的真实可恢复评测运行。"""

        self._ensure_runs_enabled()
        try:
            agent = get_builtin_agent(request.agent_name)
            mode = get_quick_mode(request.mode)
        except ValueError as exc:
            raise EvaluationUseCaseError(str(exc), status_code=400) from exc

        settings = get_settings()
        baseline_run_id: str | None = None
        try:
            async with UnitOfWork(async_session) as uow:
                suite = await self._ensure_builtin_suite(
                    uow.db,
                    user_id=user_id,
                    agent=agent,
                )
                if request.compare_production:
                    baseline = await self.repository.latest_successful_run_for_agent(
                        uow.db,
                        user_id=user_id,
                        agent_name=agent.name,
                    )
                    baseline_run_id = baseline.id if baseline else None
                suite_id = suite.id
        except TaskPayloadConfigurationError as exc:
            raise EvaluationUseCaseError(str(exc), status_code=503) from exc
        except ValueError as exc:
            raise EvaluationUseCaseError(str(exc), status_code=409) from exc

        api_config = request.api_config.model_dump(mode="json")
        run_request = EvaluationRunCreateRequest(
            suite_id=suite_id,
            agent_version="production",
            prompt_name=request.prompt_name or agent.prompt_name,
            prompt_version=request.prompt_version or agent.prompt_version,
            baseline_run_id=baseline_run_id,
            model_config_hash=model_config_fingerprint(api_config),
            api_config=api_config,
            repetition_count=mode.repetition_count,
            max_concurrency=min(
                mode.max_concurrency, settings.evaluation_max_concurrency
            ),
            max_budget_usd=min(
                mode.max_budget_usd,
                settings.evaluation_default_max_budget_usd,
            ),
            max_cases=mode.max_cases,
            include_judges=mode.include_judges,
            human_review_rate=mode.human_review_rate,
        )
        return await self.create_run(
            user_id=user_id,
            request=run_request,
            idempotency_key=idempotency_key,
        )

    async def create_run(
        self,
        *,
        user_id: str,
        request: EvaluationRunCreateRequest,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """创建 EvaluationRun，并通过加密 AgentRun payload 排队执行。"""

        self._ensure_runs_enabled()
        settings = get_settings()
        if request.max_concurrency > settings.evaluation_max_concurrency:
            raise EvaluationUseCaseError("评测并发超过服务端上限", status_code=400)
        async with UnitOfWork(async_session) as uow:
            suite = await self.repository.get_suite(
                uow.db, suite_id=request.suite_id, user_id=user_id
            )
            if suite is None:
                self._not_found("评测套件不存在或无权访问")
            dataset = await self.repository.get_dataset(
                uow.db,
                dataset_id=suite.dataset_version_id,
                user_id=user_id,
            )
            if dataset is None:
                self._not_found("评测数据集不存在或无权访问")
            if dataset.status != "locked":
                raise EvaluationUseCaseError(
                    "评测运行只能使用已锁定的 Dataset Version", status_code=409
                )
            if request.case_ids:
                dataset_cases = await self.repository.list_dataset_cases(
                    uow.db,
                    dataset_id=suite.dataset_version_id,
                    user_id=user_id,
                )
                available_case_ids = {case.id for case in dataset_cases}
                unknown_case_ids = sorted(set(request.case_ids) - available_case_ids)
                if unknown_case_ids:
                    raise EvaluationUseCaseError(
                        "选中的评测案例不属于当前套件数据集", status_code=400
                    )
            if request.baseline_run_id:
                baseline = await self.repository.get_run(
                    uow.db, run_id=request.baseline_run_id, user_id=user_id
                )
                if baseline is None:
                    self._not_found("基线评测运行不存在或无权访问")
                if baseline.status != "succeeded":
                    raise EvaluationUseCaseError("基线评测尚未完成", status_code=409)
            run = await self.repository.create_run(
                uow.db,
                user_id=user_id,
                suite=suite,
                agent_version=request.agent_version,
                prompt_name=request.prompt_name,
                prompt_version=request.prompt_version,
                model_config_hash=request.model_config_hash,
                baseline_run_id=request.baseline_run_id,
                repetition_count=request.repetition_count,
                include_judges=request.include_judges,
                budget={
                    "max_concurrency": request.max_concurrency,
                    "max_budget_usd": request.max_budget_usd,
                    "max_cases": request.max_cases,
                    "human_review_rate": request.human_review_rate,
                },
            )
            evaluation_run_id = run.id

        payload = {
            "evaluation_run_id": evaluation_run_id,
            "api_config": request.api_config,
            "max_cases": request.max_cases,
            "case_ids": request.case_ids,
        }
        fallback_key = "evaluation:" + hashlib.sha256(
            json.dumps(
                {
                    "run_id": evaluation_run_id,
                    "suite_id": request.suite_id,
                    "prompt_version": request.prompt_version,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        try:
            agent_response = await agent_run_use_cases.create_queued_run(
                task_type=TASK_TYPE_EVALUATION_SUITE,
                payload=payload,
                user_id=user_id,
                idempotency_key=idempotency_key or fallback_key,
            )
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, status_code=exc.status_code) from exc

        agent_run_id = str(agent_response.payload.get("run_id") or "")
        async with UnitOfWork(async_session) as uow:
            if agent_run_id:
                await self.repository.attach_agent_run(
                    uow.db,
                    evaluation_run_id=evaluation_run_id,
                    user_id=user_id,
                    agent_run_id=agent_run_id,
                )
            run = await self.repository.get_run(
                uow.db, run_id=evaluation_run_id, user_id=user_id
            )
            return _run(run, agent_run=agent_response.payload)

    async def list_runs(
        self, *, user_id: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """分页列出评测运行和安全汇总。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows, total = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=limit, offset=offset
            )
            return {
                "items": [_run(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def get_run(self, *, user_id: str, run_id: str) -> dict[str, Any]:
        """返回评测聚合及案例安全摘要。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if row is None:
                self._not_found("评测运行不存在或无权访问")
            cases = await self.repository.list_case_runs(
                uow.db, run_id=run_id, user_id=user_id
            )
            payload = _run(row)
            payload["cases"] = [_case_run(item) for item in cases]
            return payload

    async def list_case_runs(
        self,
        *,
        user_id: str,
        run_id: str,
        status: str | None = None,
        error_category: str | None = None,
        tool_name: str | None = None,
        tool_effect: str | None = None,
        tool_status: str | None = None,
        approval_status: str | None = None,
        has_external_side_effect: bool | None = None,
        trace_incomplete: bool | None = None,
        retrieval_empty: bool | None = None,
        needs_review: bool | None = None,
        hard_gate_passed: bool | None = None,
    ) -> dict[str, Any]:
        """在 owner 校验后按失败、工具、门禁和复核状态筛选案例摘要。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            if await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id) is None:
                self._not_found("评测运行不存在或无权访问")
            rows = await self.repository.list_case_runs(
                uow.db, run_id=run_id, user_id=user_id
            )
            filtered = [
                row
                for row in rows
                if (status is None or row.status == status)
                and (error_category is None or row.error_category == error_category)
                and (needs_review is None or row.needs_review is needs_review)
                and (
                    hard_gate_passed is None
                    or row.hard_gate_passed is hard_gate_passed
                )
                and (tool_name is None or _record_has_tool(row.record_sanitized, tool_name))
                and (
                    tool_effect is None
                    or _record_has_tool_effect(row.record_sanitized, tool_effect)
                )
                and (
                    tool_status is None
                    or _record_has_tool_status(row.record_sanitized, tool_status)
                )
                and (
                    approval_status is None
                    or _record_has_approval_status(
                        row.record_sanitized, approval_status
                    )
                )
                and (
                    has_external_side_effect is None
                    or _record_has_external_side_effect(row.record_sanitized)
                    is has_external_side_effect
                )
                and (
                    trace_incomplete is None
                    or _record_trace_incomplete(row.record_sanitized)
                    is trace_incomplete
                )
                and (
                    retrieval_empty is None
                    or _record_has_empty_retrieval(row.record_sanitized)
                    is retrieval_empty
                )
            ]
            return {"items": [_case_run(row) for row in filtered], "total": len(filtered)}

    async def get_case_run(self, *, user_id: str, case_run_id: str) -> dict[str, Any]:
        """owner 显式请求详情时解密案例、Golden 与实际输出。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.get_case_run(
                uow.db, case_run_id=case_run_id, user_id=user_id
            )
            if row is None:
                self._not_found("案例运行不存在或无权访问")
            case = await self.repository.get_case_for_case_run(
                uow.db, case_run_id=case_run_id, user_id=user_id
            )
            if case is None:
                self._not_found("评测案例不存在或无权访问")
            scores = await self.repository.list_scores(
                uow.db, case_run_id=case_run_id, user_id=user_id
            )
            annotations = await self.repository.list_annotations(
                uow.db, case_run_id=case_run_id, user_id=user_id
            )
            baseline_case = await self.repository.get_pairwise_baseline_case_run(
                uow.db, case_run=row, user_id=user_id
            )
            payload = _case_run(row)
            actual_output = decrypt_payload(row.actual_output_encrypted).get(
                "actual_output"
            )
            payload["actual_output"] = actual_output
            payload["pairwise_outputs"] = {
                "A": actual_output,
                "B": (
                    decrypt_payload(baseline_case.actual_output_encrypted).get(
                        "actual_output"
                    )
                    if baseline_case is not None
                    else None
                ),
            }
            payload["record"] = row.record_sanitized
            payload["case"] = {
                **_dataset_case(case),
                "input": decrypt_payload(case.input_encrypted),
                "expected": decrypt_payload(case.expected_encrypted),
            }
            payload["scores"] = [_score(score) for score in scores]
            payload["annotations"] = [
                _annotation(annotation) for annotation in annotations
            ]
            return payload

    async def request_review(
        self,
        *,
        user_id: str,
        run_id: str,
        request: EvaluationReviewRequest,
    ) -> dict[str, Any]:
        """显式把失败案例或选中案例加入人工复核队列。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                count = await self.repository.mark_case_runs_for_review(
                    uow.db,
                    run_id=run_id,
                    user_id=user_id,
                    case_run_ids=request.case_run_ids,
                    failed_only=request.failed_only,
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            return {"run_id": run_id, "queued_count": count}

    async def add_annotation(
        self,
        *,
        user_id: str,
        case_run_id: str,
        request: EvaluationAnnotationCreateRequest,
    ) -> dict[str, Any]:
        """追加人工标注 revision。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                row = await self.repository.add_annotation(
                    uow.db,
                    case_run_id=case_run_id,
                    user_id=user_id,
                    request=request,
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            if get_settings().evaluation_langfuse_reporting_enabled:
                _mirror_human_annotation(row)
            return _annotation(row)

    async def list_annotations(
        self, *, user_id: str, case_run_id: str
    ) -> dict[str, Any]:
        """返回 append-only 标注历史。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                rows = await self.repository.list_annotations(
                    uow.db, case_run_id=case_run_id, user_id=user_id
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            return {"items": [_annotation(row) for row in rows], "total": len(rows)}

    async def adjudicate(
        self,
        *,
        user_id: str,
        annotation_id: str,
        request: EvaluationAdjudicationRequest,
    ) -> dict[str, Any]:
        """通过现有 annotation 定位案例并追加专家裁决。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            source = await self.repository.get_annotation(
                uow.db, annotation_id=annotation_id, user_id=user_id
            )
            if source is None:
                self._not_found("标注不存在或无权访问")
            annotation_request = EvaluationAnnotationCreateRequest(
                rubric_version=source.rubric_version,
                annotation_type="categorical",
                metric_name=request.metric_name,
                value=request.value,
                comment=request.comment,
                confidence=1.0,
                reviewer_key="adjudicator",
                blind=False,
            )
            try:
                row = await self.repository.add_annotation(
                    uow.db,
                    case_run_id=source.case_run_id,
                    user_id=user_id,
                    request=annotation_request,
                    adjudication=True,
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            if get_settings().evaluation_langfuse_reporting_enabled:
                _mirror_human_annotation(row)
            return _annotation(row)

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

    async def create_candidate_dataset(
        self,
        *,
        user_id: str,
        case_run_id: str,
        request: EvaluationCandidateDatasetRequest,
    ) -> dict[str, Any]:
        """将人工确认的失败案例复制到新的候选 Dataset Version。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            try:
                row = await self.repository.create_candidate_dataset_from_case_run(
                    uow.db,
                    user_id=user_id,
                    case_run_id=case_run_id,
                    request=request,
                )
            except LookupError as exc:
                raise EvaluationUseCaseError(str(exc), status_code=404) from exc
            return _dataset(row)

    def online_sample(
        self, *, request: EvaluationOnlineSampleRequest
    ) -> dict[str, Any]:
        """对生产 Trace 做脱敏并返回确定性、Judge 和人工抽样决策。"""

        self._ensure_center_enabled()
        if not get_settings().evaluation_online_sampling_enabled:
            raise EvaluationUseCaseError("线上评测抽样未启用", status_code=403)
        return {
            "trace_id": request.trace_id,
            "risk_level": request.risk_level,
            "decision": sampling_decision(
                trace_id=request.trace_id, risk_level=request.risk_level
            ),
            "sanitized_trace": sanitize_production_trace(request.trace),
        }

    async def create_gate_policy(
        self, *, user_id: str, request: EvaluationGatePolicyCreateRequest
    ) -> dict[str, Any]:
        """创建 Gate Policy Version。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            row = await self.repository.create_gate_policy(
                uow.db, user_id=user_id, request=request
            )
            return _gate(row)

    async def list_gate_policies(self, *, user_id: str) -> dict[str, Any]:
        """列出 Gate Policy Versions。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows = await self.repository.list_gate_policies(uow.db, user_id=user_id)
            return {"items": [_gate(row) for row in rows], "total": len(rows)}

    async def overview(self, *, user_id: str) -> dict[str, Any]:
        """聚合运行、语义、专项质量、人工队列和效率指标。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows, total = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            calibrations = await self.repository.list_calibrations(
                uow.db, user_id=user_id
            )
            succeeded = [row for row in rows if row.status == "succeeded"]
            runtime = [row for row in rows if row.summary.get("runtime_success")]
            semantic = [row for row in rows if row.summary.get("semantic_success")]
            complete = [row for row in succeeded if row.summary.get("complete_success")]
            hard_passed = [row for row in succeeded if row.summary.get("hard_gate_passed")]
            latest = succeeded[0] if succeeded else None
            return {
                "run_count": total,
                "runtime_success_rate": len(runtime) / total if total else None,
                "semantic_success_rate": len(semantic) / total if total else None,
                "complete_success_rate": len(complete) / total if total else None,
                "hard_gate_pass_rate": len(hard_passed) / len(succeeded) if succeeded else None,
                "factual_support_rate": _metric_average(
                    succeeded, ("factual", "support", "faithful")
                ),
                "tool_call_accuracy": _metric_average(
                    succeeded, ("tool", "function_call")
                ),
                "judge_human_agreement": _latest_agreement(calibrations),
                "pending_review_count": sum(
                    int(row.summary.get("needs_review_count") or 0) for row in rows
                ),
                "regression_count": sum(
                    int(row.summary.get("regression_count") or 0) for row in rows
                ),
                "p95_latency_ms": (
                    latest.summary.get("p95_latency_ms") if latest else None
                ),
                "token_delta_percent": (
                    dict(latest.summary.get("baseline_comparison") or {}).get(
                        "token_total_delta_percent"
                    )
                    if latest
                    else None
                ),
                "trace_completeness_rate": _weighted_ratio(
                    rows, "trace_complete_count", "completed_count"
                ),
                "trace_incomplete_count": sum(
                    int(row.summary.get("trace_incomplete_count") or 0) for row in rows
                ),
                "tool_failure_rate": _weighted_ratio(
                    rows, "tool_call_failed_count", "tool_call_total"
                ),
                "tool_execution_success_rate": _weighted_ratio(
                    rows, "tool_call_completed_count", "tool_call_total"
                ),
                "tool_p95_duration_ms": (
                    latest.summary.get("tool_p95_duration_ms") if latest else None
                ),
                "dependency_failure_rate": _weighted_ratio(
                    rows, "external_io_failed_count", "external_io_total"
                ),
                "external_io_timeout_rate": _weighted_ratio(
                    rows, "external_io_timeout_count", "external_io_total"
                ),
                "retrieval_empty_rate": _weighted_ratio(
                    rows,
                    "retrieval_empty_case_count",
                    "retrieval_observed_case_count",
                ),
                "external_effect_count": sum(
                    int(row.summary.get("external_effect_total") or 0) for row in rows
                ),
                "external_effect_blocked_count": sum(
                    int(row.summary.get("external_effect_blocked_count") or 0)
                    for row in rows
                ),
                "approval_event_count": sum(
                    int(row.summary.get("approval_event_total") or 0) for row in rows
                ),
                "approval_violation_count": sum(
                    int(row.summary.get("approval_violation_count") or 0)
                    for row in rows
                ),
                "langfuse_reported_case_count": sum(
                    int(row.summary.get("langfuse_reported_case_count") or 0)
                    for row in rows
                ),
                "langfuse_failed_case_count": sum(
                    int(row.summary.get("langfuse_failed_case_count") or 0)
                    for row in rows
                ),
            }

    async def trends(
        self,
        *,
        user_id: str,
        agent_name: str | None = None,
        agent_version: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        model_config_hash: str | None = None,
        dataset_version: str | None = None,
        environment: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> dict[str, Any]:
        """返回按创建时间排序的版本、质量、延迟和 Token 趋势点。"""

        self._ensure_center_enabled()
        created_from = _without_timezone(created_from)
        created_to = _without_timezone(created_to)
        async with UnitOfWork(async_session) as uow:
            rows, _ = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            rows = [
                row
                for row in rows
                if (agent_name is None or row.agent_name == agent_name)
                and (agent_version is None or row.agent_version == agent_version)
                and (prompt_name is None or row.prompt_name == prompt_name)
                and (prompt_version is None or row.prompt_version == prompt_version)
                and (
                    model_config_hash is None
                    or row.model_config_hash == model_config_hash
                )
                and (
                    dataset_version is None
                    or row.dataset_version == dataset_version
                )
                and (environment is None or environment == "evaluation")
                and (created_from is None or row.created_at >= created_from)
                and (created_to is None or row.created_at <= created_to)
            ]
            return {
                "items": [
                    _trend_point(row)
                    for row in reversed(rows)
                ]
            }

    async def regressions(self, *, user_id: str) -> dict[str, Any]:
        """返回已由运行聚合确认的回归告警。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            rows, _ = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            items = [
                {
                    "run_id": row.id,
                    "baseline_run_id": row.baseline_run_id,
                    "agent_name": row.agent_name,
                    "agent_version": row.agent_version,
                    "prompt_name": row.prompt_name,
                    "prompt_version": row.prompt_version,
                    "model_config_hash": row.model_config_hash,
                    "dataset_version": row.dataset_version,
                    "severity": (
                        "critical"
                        if int(row.summary.get("hard_gate_failure_count") or 0) > 0
                        else row.summary.get("regression_severity", "warning")
                    ),
                    "regression_count": row.summary.get("regression_count", 0),
                    "failed_case_count": row.summary.get("failed_count", 0),
                    "hard_gate_failure_count": row.summary.get(
                        "hard_gate_failure_count", 0
                    ),
                    "hard_gate_blocked": int(
                        row.summary.get("hard_gate_failure_count") or 0
                    )
                    > 0,
                    "metric_deltas": dict(
                        dict(row.summary.get("baseline_comparison") or {}).get(
                            "metric_deltas"
                        )
                        or {}
                    ),
                    "complete_success_rate_delta": dict(
                        row.summary.get("baseline_comparison") or {}
                    ).get("complete_success_rate_delta"),
                    "p95_latency_ms_delta": dict(
                        row.summary.get("baseline_comparison") or {}
                    ).get("p95_latency_ms_delta"),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
                if int(row.summary.get("regression_count") or 0) > 0
            ]
            return {"items": items, "total": len(items)}

    async def annotation_queue(self, *, user_id: str) -> dict[str, Any]:
        """汇总当前用户所有 needs_review 案例，不阻塞已完成 Worker。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            runs, _ = await self.repository.list_runs(
                uow.db, user_id=user_id, limit=500, offset=0
            )
            items = []
            for run in runs:
                cases = await self.repository.list_case_runs(
                    uow.db, run_id=run.id, user_id=user_id
                )
                items.extend(
                    {**_case_run(case), "agent_name": run.agent_name}
                    for case in cases
                    if case.needs_review
                )
            return {"items": items, "total": len(items)}

    async def cancel_run(self, *, user_id: str, run_id: str) -> dict[str, Any]:
        """通过关联 AgentRun 发起 cooperative cancellation。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            run = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if run is None or not run.agent_run_id:
                self._not_found("评测运行不存在或尚未进入任务队列")
            agent_run_id = run.agent_run_id
        try:
            return await agent_run_use_cases.cancel_run(
                run_id=agent_run_id, user_id=user_id
            )
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, exc.status_code) from exc

    async def retry_failed(self, *, user_id: str, run_id: str) -> dict[str, Any]:
        """复用 AgentRun retry；案例结果幂等键阻止重复分数写入。"""

        self._ensure_runs_enabled()
        async with UnitOfWork(async_session) as uow:
            run = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if run is None or not run.agent_run_id:
                self._not_found("评测运行不存在或尚未进入任务队列")
            agent_run_id = run.agent_run_id
        try:
            result = await agent_run_use_cases.retry_run(
                run_id=agent_run_id, user_id=user_id
            )
            return result.payload
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, exc.status_code) from exc

    async def events(
        self,
        *,
        user_id: str,
        run_id: str,
        after_sequence: int,
        limit: int,
    ) -> dict[str, Any]:
        """复用 AgentRun owner-scoped 可重放事件。"""

        self._ensure_center_enabled()
        async with UnitOfWork(async_session) as uow:
            run = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if run is None or not run.agent_run_id:
                self._not_found("评测运行不存在或尚未进入任务队列")
            agent_run_id = run.agent_run_id
        try:
            return await agent_run_use_cases.list_events(
                run_id=agent_run_id,
                user_id=user_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except AgentRunUseCaseError as exc:
            raise EvaluationUseCaseError(exc.message, exc.status_code) from exc

    async def gate_check(
        self,
        *,
        user_id: str,
        run_id: str,
        policy_id: str | None = None,
    ) -> dict[str, Any]:
        """检查硬门禁、最低样本量和汇总指标，并追加不可变 Gate Result。"""

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
        """按 off/warn/enforce 检查 Prompt 版本最近的不可变 Gate Result。"""

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

    async def export_report(
        self, *, user_id: str, run_id: str, output_format: str
    ) -> dict[str, Any] | str:
        """导出 owner-scoped JSON 或独立 HTML 报告。"""

        self._ensure_center_enabled()
        if output_format not in {"json", "html"}:
            raise EvaluationUseCaseError("报告格式仅支持 json 或 html", 422)
        async with UnitOfWork(async_session) as uow:
            run = await self.repository.get_run(uow.db, run_id=run_id, user_id=user_id)
            if run is None:
                self._not_found("评测运行不存在或无权访问")
            case_rows = await self.repository.list_case_runs(
                uow.db, run_id=run_id, user_id=user_id
            )
            cases = []
            for row in case_rows:
                item = _case_run(row)
                item["record"] = row.record_sanitized
                cases.append(item)
            report = build_run_report(_run(run), cases)
        if output_format == "html":
            return render_run_report_html(report)
        return report

    @staticmethod
    def _not_found(message: str) -> NoReturn:
        """抛出不会泄露资源是否属于其他用户的 404。"""

        raise EvaluationUseCaseError(message, status_code=404)


def _dataset(row: Any) -> dict[str, Any]:
    """序列化 Dataset 元数据。"""

    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "status": row.status,
        "case_count": row.case_count,
        "source": row.source,
        "content_hash": row.content_hash,
        "created_at": row.created_at.isoformat(),
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
    }


def _dataset_case(row: Any) -> dict[str, Any]:
    """序列化不含输入和 Golden 明文的 Dataset Case 目录项。"""

    return {
        "id": row.id,
        "case_key": row.case_key,
        "category": row.category,
        "tags": row.tags,
        "severity": row.severity,
        "content_hash": row.content_hash,
        "created_at": row.created_at.isoformat(),
    }


def _suite(row: Any) -> dict[str, Any]:
    """序列化 Evaluation Suite。"""

    return {
        "id": row.id,
        "name": row.name,
        "agent_name": row.agent_name,
        "description": row.description,
        "dataset_version_id": row.dataset_version_id,
        "rubric_version": row.rubric_version,
        "gate_policy_id": row.gate_policy_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _run(row: Any, *, agent_run: dict[str, Any] | None = None) -> dict[str, Any]:
    """序列化 EvaluationRun，不公开 api_config 或加密载荷。"""

    payload = {
        "id": row.id,
        "suite_id": row.suite_id,
        "agent_run_id": row.agent_run_id,
        "agent_name": row.agent_name,
        "agent_version": row.agent_version,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "model_config_hash": row.model_config_hash,
        "dataset_version": row.dataset_version,
        "status": row.status,
        "baseline_run_id": row.baseline_run_id,
        "repetition_count": row.repetition_count,
        "include_judges": row.include_judges,
        "budget": row.budget,
        "summary": row.summary,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat(),
    }
    if agent_run is not None:
        payload["agent_run"] = agent_run
    return payload


def _case_run(row: Any) -> dict[str, Any]:
    """序列化案例运行安全摘要。"""

    return {
        "id": row.id,
        "evaluation_run_id": row.evaluation_run_id,
        "case_id": row.case_id,
        "repetition_index": row.repetition_index,
        "status": row.status,
        "trace_id": row.trace_id,
        "latency_ms": row.latency_ms,
        "token_usage": row.token_usage,
        "hard_gate_passed": row.hard_gate_passed,
        "overall_score": row.overall_score,
        "error_category": row.error_category,
        "needs_review": row.needs_review,
    }


def _score(row: Any) -> dict[str, Any]:
    """序列化来源分离的 Score，不合并硬门禁和软评分。"""

    return {
        "id": row.id,
        "case_run_id": row.case_run_id,
        "metric_name": row.metric_name,
        "value": row.value,
        "status": row.status,
        "source": row.source,
        "reason": row.reason_sanitized,
        "severity": row.severity,
        "hard_gate": row.hard_gate,
        "evidence_refs": row.evidence_refs,
        "metric_version": row.metric_version,
        "created_at": row.created_at.isoformat(),
    }


def _annotation(row: Any) -> dict[str, Any]:
    """序列化 append-only Annotation Revision。"""

    return {
        "id": row.id,
        "case_run_id": row.case_run_id,
        "rubric_version": row.rubric_version,
        "annotation_type": row.annotation_type,
        "metric_name": row.metric_name,
        "value": row.value.get("value"),
        "labels": row.labels,
        "evidence_spans": row.evidence_spans,
        "comment": row.comment_sanitized,
        "confidence": row.confidence,
        "reviewer_key": row.reviewer_key,
        "blind": row.blind,
        "revision": row.revision,
        "adjudication": row.adjudication,
        "created_at": row.created_at.isoformat(),
    }


def _calibration(row: Any) -> dict[str, Any]:
    """序列化 Calibration Version。"""

    return {
        "id": row.id,
        "metric_name": row.metric_name,
        "judge_version": row.judge_version,
        "dataset_version": row.dataset_version,
        "human_sample_count": row.human_sample_count,
        "statistics": row.statistics,
        "threshold": row.threshold,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def _gate(row: Any) -> dict[str, Any]:
    """序列化 Gate Policy Version。"""

    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "hard_gates": row.hard_gates,
        "metric_thresholds": row.metric_thresholds,
        "regression_tolerances": row.regression_tolerances,
        "minimum_sample_size": row.minimum_sample_size,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def _weighted_ratio(rows: list[Any], numerator_key: str, denominator_key: str) -> float | None:
    """按运行摘要中的计数加权计算治理指标，避免小运行放大平均值。"""

    numerator = sum(int(row.summary.get(numerator_key) or 0) for row in rows)
    denominator = sum(int(row.summary.get(denominator_key) or 0) for row in rows)
    return numerator / denominator if denominator else None


def _record_has_tool(record: Any, tool_name: str) -> bool:
    """只从 owner 已授权返回的脱敏 record 中匹配工具名，不读取原始参数。"""

    if not isinstance(record, dict):
        return False
    for item in record.get("tool_calls") or ():
        if isinstance(item, dict) and item.get("tool_name") == tool_name:
            return True
    return False


def _record_has_tool_effect(record: Any, tool_effect: str) -> bool:
    """只从脱敏 ToolCall 列表匹配副作用等级。"""

    return _record_has_item_value(record, collection="tool_calls", key="effect", value=tool_effect)


def _record_has_tool_status(record: Any, tool_status: str) -> bool:
    """只从脱敏 ToolCall 列表匹配工具终态。"""

    return _record_has_item_value(record, collection="tool_calls", key="status", value=tool_status)


def _record_has_approval_status(record: Any, approval_status: str) -> bool:
    """从 ToolCall 或 Approval 安全字段匹配审批状态。"""

    return _record_has_item_value(
        record,
        collection="tool_calls",
        key="approval_status",
        value=approval_status,
    ) or _record_has_item_value(
        record,
        collection="approvals",
        key="status",
        value=approval_status,
    )


def _record_has_external_side_effect(record: Any) -> bool:
    """判断脱敏轨迹中是否存在 external effect Tool。"""

    return _record_has_tool_effect(record, "external")


def _record_trace_incomplete(record: Any) -> bool:
    """历史记录缺少完整性字段时不伪造 incomplete，仅匹配显式 false。"""

    if not isinstance(record, dict):
        return False
    observability = record.get("observability")
    if not isinstance(observability, dict):
        return False
    completeness = observability.get("trace_completeness")
    return isinstance(completeness, dict) and completeness.get("complete") is False


def _record_has_empty_retrieval(record: Any) -> bool:
    """从脱敏 Retrieval 列表识别显式空召回案例。"""

    if not isinstance(record, dict):
        return False
    for item in record.get("retrievals") or ():
        if not isinstance(item, dict):
            continue
        if item.get("empty_result") is True or item.get("result_count") == 0:
            return True
    return False


def _record_has_item_value(
    record: Any,
    *,
    collection: str,
    key: str,
    value: str,
) -> bool:
    """在已脱敏结构化列表中执行精确短标量匹配。"""

    if not isinstance(record, dict):
        return False
    return any(
        isinstance(item, dict) and item.get(key) == value
        for item in record.get(collection) or ()
    )


def _metric_average(rows: list[Any], keywords: tuple[str, ...]) -> float | None:
    """从运行汇总中按指标关键词计算非空均值。"""

    values = [
        float(value)
        for row in rows
        for name, value in dict(row.summary.get("metrics") or {}).items()
        if value is not None and any(keyword in name.lower() for keyword in keywords)
    ]
    return sum(values) / len(values) if values else None


def _latest_agreement(rows: list[Any]) -> float | None:
    """优先返回最近 Calibration 的 Weighted Kappa，其次 Spearman/Pearson。"""

    for row in rows:
        statistics = dict(row.statistics or {})
        for name in ("weighted_kappa", "spearman", "pearson", "exact_agreement"):
            value = statistics.get(name)
            if value is not None:
                return float(value)
    return None


def _trend_point(row: Any) -> dict[str, Any]:
    """把一次运行转换为可筛选、可绘图的版本趋势点。"""

    metrics = [
        float(value)
        for value in dict(row.summary.get("metrics") or {}).values()
        if value is not None
    ]
    average_score = sum(metrics) / len(metrics) if metrics else None
    minimum_score = min(metrics) if metrics else None
    score_spread = max(metrics) - min(metrics) if metrics else None
    return {
        "run_id": row.id,
        "created_at": row.created_at.isoformat(),
        "environment": "evaluation",
        "agent_name": row.agent_name,
        "agent_version": row.agent_version,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "model_config_hash": row.model_config_hash,
        "dataset_version": row.dataset_version,
        "average_score": average_score,
        "minimum_score": minimum_score,
        "score_spread": score_spread,
        "sample_count": int(row.summary.get("completed_count") or 0),
        "complete_success_rate": row.summary.get("complete_success_rate"),
        "p50_latency_ms": row.summary.get("p50_latency_ms"),
        "p95_latency_ms": row.summary.get("p95_latency_ms"),
        "token_total": row.summary.get("token_total"),
        "p50_tokens": row.summary.get("p50_tokens"),
        "p95_tokens": row.summary.get("p95_tokens"),
    }


def _without_timezone(value: datetime | None) -> datetime | None:
    """数据库当前使用 naive datetime，查询过滤时统一去掉时区信息。"""

    return value.replace(tzinfo=None) if value and value.tzinfo else value


def _passes_threshold(value: Any, config: Any) -> bool:
    """兼容旧 float 阈值与带比较方向的新阈值对象。"""

    actual = float(value)
    if isinstance(config, dict):
        threshold = float(config.get("value"))
        comparison = str(config.get("comparison") or "gte")
    else:
        threshold = float(config)
        comparison = "gte"
    if comparison == "lte":
        return actual <= threshold
    if comparison == "eq":
        return actual == threshold
    return actual >= threshold


def _is_unacceptable_regression(delta: Any, config: Any) -> bool:
    """判断相对基线的指标变化是否超出方向化容忍度。"""

    actual_delta = float(delta)
    if isinstance(config, dict):
        tolerance = abs(float(config.get("value")))
        comparison = str(config.get("comparison") or "gte")
    else:
        tolerance = abs(float(config))
        comparison = "gte"
    if comparison == "lte":
        return actual_delta > tolerance
    if comparison == "eq":
        return abs(actual_delta) > tolerance
    return actual_delta < -tolerance


def _mirror_human_annotation(row: Any) -> None:
    """Best-effort mirror one human revision without uploading case content."""

    try:
        from observability.evaluation_reporting import EvaluationScore, report_score

        raw = row.value.get("value")
        value = (
            1.0
            if raw is True
            else 0.0
            if raw is False
            else float(raw)
            if isinstance(raw, (int, float))
            else "not_applicable"
        )
        report_score(
            EvaluationScore(
                name=row.metric_name,
                value=value,
                trace_id=None,
                metadata={
                    "source": "human",
                    "case_run_id": row.case_run_id,
                    "revision": row.revision,
                    "adjudication": row.adjudication,
                },
            )
        )
    except Exception:
        return


evaluation_use_cases = EvaluationUseCases()
