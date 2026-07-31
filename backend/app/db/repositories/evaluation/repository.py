"""Evaluation 聚合的 owner-scoped SQLAlchemy Repository。"""

from app.db.models import EvaluationCaseModel, EvaluationDatasetVersionModel, EvaluationScoreModel
from app.schemas.evaluations import EvaluationCandidateDatasetRequest, EvaluationCaseCreateRequest, EvaluationDatasetCreateRequest
from app.security.payload_crypto import decrypt_payload, encrypt_payload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .annotation_repository import AnnotationRepositoryMixin
from .dataset_repository import DatasetRepositoryMixin
from .gate_repository import GateRepositoryMixin
from .helpers import (
    _candidate_governance_metadata,
    _hash,
    _id,
    _merge_candidate_tags,
    _now,
    _safe_evidence_refs,
)
from .run_repository import RunRepositoryMixin


class EvaluationRepository(
    DatasetRepositoryMixin,
    RunRepositoryMixin,
    AnnotationRepositoryMixin,
    GateRepositoryMixin,
):
    """持久化评测套件、版本、运行、分数和人工治理数据。"""

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
                    "evidence_refs": case.evidence_refs,
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
                scores = list(
                    await session.scalars(
                        select(EvaluationScoreModel).where(
                            EvaluationScoreModel.case_run_id == case_run.id
                        )
                    )
                )
                governance_tags, evidence_refs = _candidate_governance_metadata(
                    record=dict(case_run.record_sanitized or {}),
                    error_category=case_run.error_category,
                    scores=scores,
                )
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
                    evidence_refs=_safe_evidence_refs(
                        [*(source_expected.get("evidence_refs") or []), *evidence_refs]
                    ),
                    tags=_merge_candidate_tags(request.tags, governance_tags),
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
