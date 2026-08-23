"""评测一键运行用例：解析服务端目录并创建受约束的快速评测批次。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal, Protocol, cast

from ai.workflows.evaluation.contracts import EvaluationUseCaseError
from app.config import get_settings
from app.db.models import async_session
from app.db.repositories.jobs.job_capture_repo import JobCaptureRepo
from app.db.unit_of_work import UnitOfWork
from app.schemas.evaluation.evaluations import (
    EvaluationAllQuickRunRequest,
    EvaluationQuickRunRequest,
    EvaluationRunCreateRequest,
)
from app.security.payload_crypto import TaskPayloadConfigurationError
from evaluation.builtins import (
    BUILTIN_EVALUATION_AGENTS,
    get_builtin_agent,
    get_builtin_scope,
    get_quick_mode,
    model_config_fingerprint,
)
from evaluation.runners.production import (
    CatalogEvaluationView,
    EvaluationConfigurationError,
)

EvaluationAgentName = Literal[
    "interview_planner",
    "interview_turn",
    "interview_scoring",
    "resume_optimizer",
    "resume_analyzer",
    "resume_generator",
]


class _QuickRunHost(Protocol):
    """描述一键运行 mixin 由聚合服务提供的最小能力。"""

    repository: Any

    def _ensure_runs_enabled(self) -> None: ...

    async def _ensure_builtin_suite(self, *args: Any, **kwargs: Any) -> Any: ...

    async def create_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    async def quick_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


async def _job_description_snapshot_for_evaluation(user_id: str) -> str:
    """Read one owner-scoped JD once, before creating an immutable evaluation dataset."""

    jobs = await JobCaptureRepo().list_jobs(user_id=user_id, limit=50)
    for job in jobs:
        description = str(job.get("job_description") or "").strip()
        if description:
            return description[:12_000]
    raise EvaluationUseCaseError(
        "标准回归和发布检查需要岗位库中至少一条完整 JD", status_code=409
    )


class QuickRunUseCasesMixin:
    """把一键评测选择展开为服务端治理的 EvaluationRun。"""

    async def quick_run(
        self,
        *,
        user_id: str,
        request: EvaluationQuickRunRequest,
        idempotency_key: str | None,
        smoke_batch_id: str | None = None,
    ) -> dict[str, Any]:
        """把 Agent 与模式选择展开为受服务端约束的真实可恢复评测运行。"""

        host = cast(_QuickRunHost, self)
        host._ensure_runs_enabled()
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

        try:
            scope = get_builtin_scope(agent, mode.name)
            if mode.name in {"standard", "release"}:
                async with UnitOfWork(async_session) as uow:
                    existing_dataset = await host.repository.get_dataset_by_name_version(
                        uow.db,
                        user_id=user_id,
                        name=scope.dataset_name,
                        version=scope.dataset_version,
                    )
                if existing_dataset is None:
                    scope = get_builtin_scope(
                        agent,
                        mode.name,
                        job_description=await _job_description_snapshot_for_evaluation(user_id),
                        require_job_description=True,
                    )
        except ValueError as exc:
            raise EvaluationUseCaseError(str(exc), status_code=409) from exc

        settings = get_settings()
        baseline_run_id: str | None = None
        try:
            async with UnitOfWork(async_session) as uow:
                suite = await host._ensure_builtin_suite(
                    uow.db,
                    user_id=user_id,
                    agent=agent,
                    scope=scope,
                )
                if request.compare_production:
                    baseline = await host.repository.latest_successful_run_for_agent(
                        uow.db,
                        user_id=user_id,
                        agent_name=agent.name,
                        dataset_version=f"{scope.dataset_name}:{scope.dataset_version}",
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
        return await host.create_run(
            user_id=user_id,
            request=run_request,
            idempotency_key=idempotency_key,
            smoke_batch_id=smoke_batch_id,
        )

    async def all_agents_quick_run(
        self,
        *,
        user_id: str,
        request: EvaluationAllQuickRunRequest,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """Queue one server-owned quick smoke run for every supported built-in Agent."""

        host = cast(_QuickRunHost, self)
        host._ensure_runs_enabled()
        runs: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        if idempotency_key:
            smoke_batch_id = "smoke_" + hashlib.sha256(
                f"{user_id}\0{idempotency_key}".encode()
            ).hexdigest()[:32]
        else:
            smoke_batch_id = f"smoke_{uuid.uuid4().hex}"
        for agent in BUILTIN_EVALUATION_AGENTS:
            agent_key = f"{idempotency_key}:{agent.name}" if idempotency_key else None
            try:
                run = await host.quick_run(
                    user_id=user_id,
                    request=EvaluationQuickRunRequest(
                        agent_name=cast(EvaluationAgentName, agent.name),
                        mode="quick",
                        api_config=request.api_config,
                    ),
                    idempotency_key=agent_key,
                    smoke_batch_id=smoke_batch_id,
                )
            except EvaluationUseCaseError as exc:
                failures.append({"agent_name": agent.name, "message": exc.message})
            else:
                runs.append(run)
        return {"smoke_batch_id": smoke_batch_id, "runs": runs, "failures": failures}


__all__ = ["QuickRunUseCasesMixin"]
