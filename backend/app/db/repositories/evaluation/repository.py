"""Evaluation 聚合的 owner-scoped SQLAlchemy Repository。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Sequence

from app.security.payload_crypto import decrypt_payload, encrypt_payload
from app.db.models import (
    EvaluationAnnotationModel,
    EvaluationCalibrationModel,
    EvaluationCaseModel,
    EvaluationCaseRunModel,
    EvaluationDatasetVersionModel,
    EvaluationGatePolicyModel,
    EvaluationGateResultModel,
    EvaluationRunModel,
    EvaluationScoreModel,
    EvaluationSuiteModel,
)
from app.schemas.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationCaseCreateRequest,
    EvaluationCandidateDatasetRequest,
    EvaluationDatasetCreateRequest,
    EvaluationGatePolicyCreateRequest,
    EvaluationSuiteCreateRequest,
)
from evaluation.runners import EvaluationCaseSpec, EvaluationCaseResult
from evaluation.schemas import EvalScoreStatus
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _now() -> datetime:
    """返回便于测试替换的本地时间。"""

    return datetime.now()


def _id(prefix: str) -> str:
    """生成带领域前缀的 UUID 标识。"""

    return f"{prefix}_{uuid.uuid4().hex}"


def _hash(value: Any) -> str:
    """对规范化 JSON 计算稳定 SHA-256。"""

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


class EvaluationRepository:
    """持久化评测套件、版本、运行、分数和人工治理数据。"""

    async def create_dataset(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        request: EvaluationDatasetCreateRequest,
    ) -> EvaluationDatasetVersionModel:
        """创建数据集版本和加密案例；同一 owner/name/version 由数据库拒绝重复。"""

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
        for case in request.cases:
            session.add(self._case_model(dataset.id, case))
        await session.flush()
        return dataset

    def _case_model(
        self,
        dataset_id: str,
        case: EvaluationCaseCreateRequest,
    ) -> EvaluationCaseModel:
        """把一个 API Case 分成加密输入和加密 Ground Truth。"""

        expected = {
            "expected_output": case.expected_output,
            "expected_facts": case.expected_facts,
            "forbidden_claims": case.forbidden_claims,
            "expected_tool_calls": case.expected_tool_calls,
            "allowed_tool_calls": case.allowed_tool_calls,
            "required_state_transitions": case.required_state_transitions,
            "forbidden_state_transitions": case.forbidden_state_transitions,
            "quality_rubric": case.quality_rubric,
            "retrieval_context": case.retrieval_context,
            "latency_budget_ms": case.latency_budget_ms,
            "token_budget": case.token_budget,
            "fault_injection": case.fault_injection,
        }
        return EvaluationCaseModel(
            id=_id("ecase"),
            dataset_version_id=dataset_id,
            case_key=case.case_key,
            category=case.category,
            input_encrypted=encrypt_payload(case.input),
            expected_encrypted=encrypt_payload(expected),
            tags=case.tags,
            severity=case.severity,
            content_hash=_hash({"input": case.input, "expected": expected}),
            created_at=_now(),
        )

    async def list_datasets(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[EvaluationDatasetVersionModel], int]:
        """分页列出当前 owner 的数据集元数据，不解密案例正文。"""

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
        """按 owner 获取一个数据集版本。"""

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
        """按 owner/name/version 精确读取数据集，供内置版本幂等引导使用。"""

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
        """按 owner 返回案例安全元数据；不解密输入和 Golden。"""

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
        """锁定 calibrated 数据集；锁定后 Repository 不提供原地案例修改入口。"""

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
        """按单向状态机推进 Dataset Version 生命周期。"""

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
        """创建套件前再次校验 Dataset 与 Gate Policy 所有权。"""

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
        """列出当前 owner 的套件。"""

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
        """按 owner 获取套件。"""

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
        """按 owner/name 精确读取套件，避免一键评测重复创建治理事实。"""

        return await session.scalar(
            select(EvaluationSuiteModel).where(
                EvaluationSuiteModel.user_id == user_id,
                EvaluationSuiteModel.name == name,
            )
        )

    async def create_run(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        suite: EvaluationSuiteModel,
        agent_version: str,
        prompt_name: str | None,
        prompt_version: str | None,
        model_config_hash: str,
        baseline_run_id: str | None,
        repetition_count: int,
        include_judges: bool,
        budget: dict[str, Any],
    ) -> EvaluationRunModel:
        """创建 EvaluationRun；敏感 api_config 由 AgentRun 加密载荷持有。"""

        dataset = await self.get_dataset(
            session, dataset_id=suite.dataset_version_id, user_id=user_id
        )
        if dataset is None:
            raise LookupError("dataset not found")
        run = EvaluationRunModel(
            id=_id("erun"),
            user_id=user_id,
            suite_id=suite.id,
            agent_run_id=None,
            agent_name=suite.agent_name,
            agent_version=agent_version,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model_config_hash=model_config_hash,
            dataset_version=f"{dataset.name}:{dataset.version}",
            status="queued",
            baseline_run_id=baseline_run_id,
            repetition_count=repetition_count,
            include_judges=include_judges,
            budget=budget,
            summary={},
            started_at=None,
            finished_at=None,
            created_at=_now(),
        )
        session.add(run)
        await session.flush()
        return run

    async def attach_agent_run(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: str,
        user_id: str,
        agent_run_id: str,
    ) -> None:
        """只允许 owner 将业务评测聚合关联到其 AgentRun。"""

        run = await self.get_run(
            session, run_id=evaluation_run_id, user_id=user_id
        )
        if run is None:
            raise LookupError("evaluation run not found")
        run.agent_run_id = agent_run_id
        await session.flush()

    async def get_run(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        user_id: str,
    ) -> EvaluationRunModel | None:
        """按 owner 获取 EvaluationRun。"""

        return await session.scalar(
            select(EvaluationRunModel).where(
                EvaluationRunModel.id == run_id,
                EvaluationRunModel.user_id == user_id,
            )
        )

    async def list_runs(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[EvaluationRunModel], int]:
        """分页列出当前 owner 的评测运行。"""

        where = EvaluationRunModel.user_id == user_id
        total = await session.scalar(
            select(func.count()).select_from(EvaluationRunModel).where(where)
        )
        rows = await session.scalars(
            select(EvaluationRunModel)
            .where(where)
            .order_by(EvaluationRunModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def latest_successful_run_for_agent(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent_name: str,
    ) -> EvaluationRunModel | None:
        """返回 owner 下同一 Agent 最近成功运行，作为可选生产比较基线。"""

        return await session.scalar(
            select(EvaluationRunModel)
            .where(
                EvaluationRunModel.user_id == user_id,
                EvaluationRunModel.agent_name == agent_name,
                EvaluationRunModel.status == "succeeded",
            )
            .order_by(EvaluationRunModel.created_at.desc())
            .limit(1)
        )

    async def case_specs_for_run(
        self,
        session: AsyncSession,
        *,
        run: EvaluationRunModel,
        user_id: str,
        max_cases: int | None = None,
        case_ids: Sequence[str] = (),
    ) -> list[tuple[EvaluationCaseModel, EvaluationCaseSpec]]:
        """再次通过 suite/dataset owner 关系读取并解密 Runner 所需案例。"""

        suite = await self.get_suite(session, suite_id=run.suite_id, user_id=user_id)
        if suite is None:
            raise LookupError("suite not found")
        statement = (
            select(EvaluationCaseModel)
            .where(EvaluationCaseModel.dataset_version_id == suite.dataset_version_id)
            .order_by(EvaluationCaseModel.case_key)
        )
        if case_ids:
            statement = statement.where(EvaluationCaseModel.id.in_(tuple(case_ids)))
        if max_cases is not None:
            statement = statement.limit(max_cases)
        rows = list(await session.scalars(statement))
        result: list[tuple[EvaluationCaseModel, EvaluationCaseSpec]] = []
        for row in rows:
            expected = decrypt_payload(row.expected_encrypted)
            result.append(
                (
                    row,
                    EvaluationCaseSpec(
                        case_id=row.id,
                        case_version=row.content_hash,
                        dataset_version=run.dataset_version,
                        input_payload=decrypt_payload(row.input_encrypted),
                        expected_output=expected.get("expected_output"),
                        expected_facts=tuple(expected.get("expected_facts") or []),
                        forbidden_claims=tuple(expected.get("forbidden_claims") or []),
                        expected_tool_calls=tuple(expected.get("expected_tool_calls") or []),
                        allowed_tool_calls=tuple(expected.get("allowed_tool_calls") or []),
                        required_state_transitions=tuple(
                            expected.get("required_state_transitions") or []
                        ),
                        forbidden_state_transitions=tuple(
                            expected.get("forbidden_state_transitions") or []
                        ),
                        retrieval_context=tuple(expected.get("retrieval_context") or []),
                        tags=tuple(row.tags or []),
                        severity=row.severity,
                        latency_budget_ms=expected.get("latency_budget_ms"),
                        token_budget=expected.get("token_budget"),
                        fault_injection=expected.get("fault_injection"),
                    ),
                )
            )
        return result

    async def save_case_result(
        self,
        session: AsyncSession,
        *,
        run: EvaluationRunModel,
        case: EvaluationCaseModel,
        repetition_index: int,
        result: EvaluationCaseResult,
        trace_id: str | None = None,
    ) -> EvaluationCaseRunModel:
        """幂等保存单案例结果和来源分离分数；实际输出加密落库。"""

        existing = await session.scalar(
            select(EvaluationCaseRunModel).where(
                EvaluationCaseRunModel.evaluation_run_id == run.id,
                EvaluationCaseRunModel.case_id == case.id,
                EvaluationCaseRunModel.repetition_index == repetition_index,
            )
        )
        if (
            existing is not None
            and existing.status == "succeeded"
            and existing.hard_gate_passed
        ):
            return existing
        hard_gate_passed = all(
            score.status is EvalScoreStatus.PASSED
            for score in result.scores
            if score.hard_gate
        )
        soft_values = [
            score.value
            for score in result.scores
            if not score.hard_gate and score.value is not None
        ]
        record_payload = result.record.model_dump(mode="json")
        actual_output = record_payload.pop("final_output", None)
        values = {
            "status": result.record.final_status,
            "actual_output_encrypted": encrypt_payload(
                {"actual_output": actual_output}
            ),
            "record_sanitized": record_payload,
            "trace_id": trace_id,
            "latency_ms": result.record.latency_ms,
            "token_usage": result.record.token_usage.model_dump(mode="json"),
            "hard_gate_passed": hard_gate_passed,
            "overall_score": (
                sum(soft_values) / len(soft_values) if soft_values else None
            ),
            "error_category": (
                result.record.error.classification if result.record.error else None
            ),
            "needs_review": (
                not hard_gate_passed or result.record.final_status != "succeeded"
            ),
            "finished_at": _now(),
        }
        if existing is None:
            row = EvaluationCaseRunModel(
                id=_id("ecrun"),
                evaluation_run_id=run.id,
                case_id=case.id,
                repetition_index=repetition_index,
                created_at=_now(),
                **values,
            )
            session.add(row)
        else:
            row = existing
            await session.execute(
                delete(EvaluationScoreModel).where(
                    EvaluationScoreModel.case_run_id == row.id
                )
            )
            for field, value in values.items():
                setattr(row, field, value)
        for score in result.scores:
            session.add(
                EvaluationScoreModel(
                    id=_id("escore"),
                    case_run_id=row.id,
                    metric_name=score.metric_name,
                    value=score.value,
                    status=score.status.value,
                    source=score.source.value,
                    reason_sanitized=score.reason_code,
                    severity="critical" if score.hard_gate else "info",
                    hard_gate=score.hard_gate,
                    evidence_refs=list(score.evidence_refs),
                    metric_version="1",
                    created_at=_now(),
                )
            )
        await session.flush()
        return row

    async def update_run_status(
        self,
        session: AsyncSession,
        *,
        run: EvaluationRunModel,
        status: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """更新业务聚合阶段和终态，不替代 AgentRun 事件生命周期。"""

        run.status = status
        if status == "running" and run.started_at is None:
            run.started_at = _now()
        if status in {"succeeded", "failed", "cancelled"}:
            run.finished_at = _now()
        if summary is not None:
            run.summary = summary
        await session.flush()

    async def list_case_runs(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        user_id: str,
    ) -> list[EvaluationCaseRunModel]:
        """通过 EvaluationRun owner 过滤单案例结果。"""

        rows = await session.scalars(
            select(EvaluationCaseRunModel)
            .join(
                EvaluationRunModel,
                EvaluationRunModel.id == EvaluationCaseRunModel.evaluation_run_id,
            )
            .where(
                EvaluationCaseRunModel.evaluation_run_id == run_id,
                EvaluationRunModel.user_id == user_id,
            )
            .order_by(EvaluationCaseRunModel.created_at)
        )
        return list(rows)

    async def get_case_run(
        self,
        session: AsyncSession,
        *,
        case_run_id: str,
        user_id: str,
    ) -> EvaluationCaseRunModel | None:
        """按 owner 获取案例详情；实际输出仍保持密文，调用方显式决定是否解密。"""

        return await session.scalar(
            select(EvaluationCaseRunModel)
            .join(
                EvaluationRunModel,
                EvaluationRunModel.id == EvaluationCaseRunModel.evaluation_run_id,
            )
            .where(
                EvaluationCaseRunModel.id == case_run_id,
                EvaluationRunModel.user_id == user_id,
            )
        )

    async def get_case_for_case_run(
        self,
        session: AsyncSession,
        *,
        case_run_id: str,
        user_id: str,
    ) -> EvaluationCaseModel | None:
        """按案例运行 owner 获取输入/Golden 对应的案例行。"""

        return await session.scalar(
            select(EvaluationCaseModel)
            .join(
                EvaluationCaseRunModel,
                EvaluationCaseRunModel.case_id == EvaluationCaseModel.id,
            )
            .join(
                EvaluationRunModel,
                EvaluationRunModel.id == EvaluationCaseRunModel.evaluation_run_id,
            )
            .where(
                EvaluationCaseRunModel.id == case_run_id,
                EvaluationRunModel.user_id == user_id,
            )
        )

    async def get_pairwise_baseline_case_run(
        self,
        session: AsyncSession,
        *,
        case_run: EvaluationCaseRunModel,
        user_id: str,
    ) -> EvaluationCaseRunModel | None:
        """按 owner 获取同案例、同重复序号的基线输出，用于盲化 Pairwise。"""

        run = await self.get_run(
            session, run_id=case_run.evaluation_run_id, user_id=user_id
        )
        if run is None or not run.baseline_run_id:
            return None
        return await session.scalar(
            select(EvaluationCaseRunModel)
            .join(
                EvaluationRunModel,
                EvaluationRunModel.id == EvaluationCaseRunModel.evaluation_run_id,
            )
            .where(
                EvaluationCaseRunModel.evaluation_run_id == run.baseline_run_id,
                EvaluationCaseRunModel.case_id == case_run.case_id,
                EvaluationCaseRunModel.repetition_index == case_run.repetition_index,
                EvaluationRunModel.user_id == user_id,
            )
        )

    async def list_scores(
        self,
        session: AsyncSession,
        *,
        case_run_id: str,
        user_id: str,
    ) -> list[EvaluationScoreModel]:
        """按案例运行 owner 返回来源分离的全部评分。"""

        if await self.get_case_run(session, case_run_id=case_run_id, user_id=user_id) is None:
            raise LookupError("case run not found")
        rows = await session.scalars(
            select(EvaluationScoreModel)
            .where(EvaluationScoreModel.case_run_id == case_run_id)
            .order_by(EvaluationScoreModel.source, EvaluationScoreModel.metric_name)
        )
        return list(rows)

    async def mark_case_runs_for_review(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        user_id: str,
        case_run_ids: Sequence[str] = (),
        failed_only: bool = True,
    ) -> int:
        """把 owner 运行中的指定案例或失败案例显式加入人工复核队列。"""

        run = await self.get_run(session, run_id=run_id, user_id=user_id)
        if run is None:
            raise LookupError("evaluation run not found")
        statement = select(EvaluationCaseRunModel).where(
            EvaluationCaseRunModel.evaluation_run_id == run_id
        )
        if case_run_ids:
            statement = statement.where(EvaluationCaseRunModel.id.in_(tuple(case_run_ids)))
        elif failed_only:
            statement = statement.where(
                (EvaluationCaseRunModel.status != "succeeded")
                | (EvaluationCaseRunModel.hard_gate_passed.is_(False))
            )
        rows = list(await session.scalars(statement))
        for row in rows:
            row.needs_review = True
        pending = await session.scalar(
            select(func.count())
            .select_from(EvaluationCaseRunModel)
            .where(
                EvaluationCaseRunModel.evaluation_run_id == run_id,
                EvaluationCaseRunModel.needs_review.is_(True),
            )
        )
        run.summary = {
            **dict(run.summary or {}),
            "needs_review_count": int(pending or 0),
        }
        await session.flush()
        return len(rows)

    async def add_annotation(
        self,
        session: AsyncSession,
        *,
        case_run_id: str,
        user_id: str,
        request: EvaluationAnnotationCreateRequest,
        adjudication: bool = False,
    ) -> EvaluationAnnotationModel:
        """验证案例 owner 后追加 revision，不更新或删除历史标注。"""

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
        """按案例 owner 返回追加式标注历史。"""

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
        """通过案例运行 owner 读取标注，避免跨用户存在性泄漏。"""

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
        """保存不可变 Calibration Version。"""

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
        """列出当前 owner 的 Calibration 历史。"""

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
        """按 owner 获取一个不可变 Calibration Version。"""

        return await session.scalar(
            select(EvaluationCalibrationModel).where(
                EvaluationCalibrationModel.id == calibration_id,
                EvaluationCalibrationModel.user_id == user_id,
            )
        )

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

    async def create_candidate_dataset_from_case_run(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        case_run_id: str,
        request: EvaluationCandidateDatasetRequest,
    ) -> EvaluationDatasetVersionModel:
        """复制失败案例输入到新的候选数据集版本，不修改已锁定版本。"""

        case_run = await self.get_case_run(
            session, case_run_id=case_run_id, user_id=user_id
        )
        if case_run is None:
            raise LookupError("case run not found")
        case = await session.scalar(
            select(EvaluationCaseModel).where(EvaluationCaseModel.id == case_run.case_id)
        )
        if case is None:
            raise LookupError("evaluation case not found")
        source_expected = decrypt_payload(case.expected_encrypted)
        candidate_case = EvaluationCaseCreateRequest(
            case_key=request.case_key or f"{case.case_key}-regression",
            category=request.category,
            input=decrypt_payload(case.input_encrypted),
            expected_output=(
                request.expected_output
                if request.expected_output is not None
                else source_expected.get("expected_output")
            ),
            expected_facts=request.expected_facts
            or source_expected.get("expected_facts")
            or [],
            forbidden_claims=request.forbidden_claims
            or source_expected.get("forbidden_claims")
            or [],
            expected_tool_calls=source_expected.get("expected_tool_calls") or [],
            allowed_tool_calls=source_expected.get("allowed_tool_calls") or [],
            required_state_transitions=(
                source_expected.get("required_state_transitions") or []
            ),
            forbidden_state_transitions=(
                source_expected.get("forbidden_state_transitions") or []
            ),
            quality_rubric=source_expected.get("quality_rubric") or {},
            retrieval_context=source_expected.get("retrieval_context") or [],
            tags=request.tags,
            severity=request.severity,
            latency_budget_ms=source_expected.get("latency_budget_ms"),
            token_budget=source_expected.get("token_budget"),
            fault_injection=source_expected.get("fault_injection"),
        )
        return await self.create_dataset(
            session,
            user_id=user_id,
            request=EvaluationDatasetCreateRequest(
                name=request.name,
                version=request.version,
                source="confirmed_failure",
                cases=[candidate_case],
            ),
        )
