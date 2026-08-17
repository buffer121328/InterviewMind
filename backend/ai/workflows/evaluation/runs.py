"""评测 Run 子域用例：运行编排、案例筛选与 AgentRun 协作。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ai.workflows.agent_runs.use_cases import AgentRunUseCaseError, agent_run_use_cases
from ai.workflows.evaluation.serializers import (
    _annotation,
    _case_run,
    _dataset,
    _dataset_case,
    _run,
    _score,
)
from ai.workflows.evaluation.contracts import EvaluationUseCaseError
from ai.workflows.evaluation.run_filters import (
    record_has_approval_status,
    record_has_empty_retrieval,
    record_has_external_side_effect,
    record_has_tool,
    record_has_tool_effect,
    record_has_tool_status,
    record_trace_incomplete,
)
from app.config import get_settings
from app.db.models import async_session
from app.db.unit_of_work import UnitOfWork
from app.domain.agent_runs import TASK_TYPE_EVALUATION_SUITE
from app.schemas.evaluation.evaluations import (
    EvaluationCandidateDatasetRequest,
    EvaluationQuickRunRequest,
    EvaluationReviewRequest,
    EvaluationRunCreateRequest,
)
from app.security.payload_crypto import (
    TaskPayloadConfigurationError,
    decrypt_payload,
)
from evaluation.builtins import (
    get_builtin_agent,
    get_quick_mode,
    model_config_fingerprint,
)
from evaluation.runners.production import (
    CatalogEvaluationView,
    EvaluationConfigurationError,
)


def _evaluation_run_id_for_idempotency(user_id: str, idempotency_key: str) -> str:
    """处理评测运行ID幂等相关后端逻辑。"""

    digest = hashlib.sha256(
        f"{user_id}\0{TASK_TYPE_EVALUATION_SUITE}\0{idempotency_key}".encode()
    ).hexdigest()[:32]
    return f"erun_{digest}"


class RunUseCasesMixin:
    """Run 子域应用用例：一键/高级运行、案例筛选与取消重试事件。"""

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

        try:
            catalog_entry = CatalogEvaluationView().resolve(agent.name)
        except EvaluationConfigurationError as exc:
            raise EvaluationUseCaseError(str(exc), status_code=503) from exc
        if request.prompt_name is not None and request.prompt_name != catalog_entry.definition.prompt_name:
            raise EvaluationUseCaseError("evaluation prompt identity drifted", status_code=409)
        if request.prompt_version is not None and request.prompt_version != catalog_entry.definition.prompt_version:
            raise EvaluationUseCaseError("evaluation prompt identity drifted", status_code=409)

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
            agent_version=catalog_entry.definition.version,
            prompt_name=catalog_entry.definition.prompt_name,
            prompt_version=catalog_entry.definition.prompt_version,
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
        stable_run_id = (
            _evaluation_run_id_for_idempotency(user_id, idempotency_key)
            if idempotency_key
            else None
        )
        existing_payload: dict[str, Any] | None = None
        existing_agent_run_id: str | None = None
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
            run = (
                await self.repository.get_run(
                    uow.db, run_id=stable_run_id, user_id=user_id
                )
                if stable_run_id
                else None
            )
            if run is None:
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
                    run_id=stable_run_id,
                )
            elif run.agent_run_id:
                existing_payload = _run(run)
                existing_agent_run_id = run.agent_run_id
            evaluation_run_id = run.id

        if existing_payload is not None and existing_agent_run_id is not None:
            try:
                existing_payload["agent_run"] = await agent_run_use_cases.get_run(
                    run_id=existing_agent_run_id,
                    user_id=user_id,
                )
            except AgentRunUseCaseError as exc:
                raise EvaluationUseCaseError(
                    exc.message, status_code=exc.status_code
                ) from exc
            return existing_payload

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

        agent_run_id = str(agent_response.body.get("run_id") or "")
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
            return _run(run, agent_run=agent_response.body)

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
                and (tool_name is None or record_has_tool(row.record_sanitized, tool_name))
                and (
                    tool_effect is None
                    or record_has_tool_effect(row.record_sanitized, tool_effect)
                )
                and (
                    tool_status is None
                    or record_has_tool_status(row.record_sanitized, tool_status)
                )
                and (
                    approval_status is None
                    or record_has_approval_status(
                        row.record_sanitized, approval_status
                    )
                )
                and (
                    has_external_side_effect is None
                    or record_has_external_side_effect(row.record_sanitized)
                    is has_external_side_effect
                )
                and (
                    trace_incomplete is None
                    or record_trace_incomplete(row.record_sanitized)
                    is trace_incomplete
                )
                and (
                    retrieval_empty is None
                    or record_has_empty_retrieval(row.record_sanitized)
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
            return result.body
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
