"""Evaluation 聚合的 owner-scoped SQLAlchemy Repository。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvaluationCaseModel, EvaluationDatasetVersionModel
from app.schemas.evaluation.evaluations import (
    EvaluationCandidateDatasetRequest,
    EvaluationCaseCreateRequest,
)
from app.security.payload_crypto import encrypt_payload

from .annotation_repository import AnnotationRepositoryMixin
from .candidate_dataset_repository import create_confirmed_failure_dataset
from .dataset_repository import DatasetRepositoryMixin
from .gate_repository import GateRepositoryMixin
from .helpers import (
    _hash,
    _id,
    _now,
)
from .interview_history_repository import InterviewHistoryRepositoryMixin
from .run_repository import RunRepositoryMixin


class EvaluationRepository(
    InterviewHistoryRepositoryMixin,
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
            "required_workflow_tool_calls": case.required_workflow_tool_calls,
            "degraded_workflow_tool_calls": case.degraded_workflow_tool_calls,
            "blocked_workflow_tool_calls": case.blocked_workflow_tool_calls,
            "tool_fixtures": case.tool_fixtures,
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

        return await create_confirmed_failure_dataset(
            self, session, user_id=user_id, case_run_id=case_run_id, request=request
        )
