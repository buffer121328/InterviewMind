"""Evaluation 运行、案例执行与分数持久化。"""

from __future__ import annotations

from typing import Any, Sequence

from app.db.models import EvaluationCaseModel, EvaluationCaseRunModel, EvaluationDatasetVersionModel, EvaluationRunModel, EvaluationScoreModel, EvaluationSuiteModel
from app.security.payload_crypto import decrypt_payload, encrypt_payload
from evaluation.outcomes import classify_case_outcome, semantic_score_average
from evaluation.runners import EvaluationCaseResult, EvaluationCaseSpec
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .helpers import _id, _now


class RunRepositoryMixin:
    """按关注点拆分的 EvaluationRepository 行为。"""

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
            run_id: str | None = None,
        ) -> EvaluationRunModel:
            """创建 EvaluationRun；敏感 api_config 由 AgentRun 加密载荷持有。"""

            dataset = await self.get_dataset(
                session, dataset_id=suite.dataset_version_id, user_id=user_id
            )
            if dataset is None:
                raise LookupError("dataset not found")
            run = EvaluationRunModel(
                id=run_id or _id("erun"),
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
                            quality_rubric=dict(expected.get("quality_rubric") or {}),
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
            outcome = result.record.outcome or classify_case_outcome(
                result.record, result.scores
            )
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
                "hard_gate_passed": outcome.hard_gate_passed,
                "overall_score": semantic_score_average(result.scores),
                "error_category": (
                    result.record.error.classification if result.record.error else None
                ),
                "needs_review": outcome.review_required,
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
