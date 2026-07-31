"""Budgeted interview profile, weakness-report, and recoverable evidence analysis."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any, Dict, List, Optional

from ai.llm import llm_utils
from ai.runtime.context_assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)
from ai.runtime.deadlines import TaskDeadline
from app.config import get_settings
from app.schemas.candidate_profile import CandidateProfile, DimensionScore
from app.schemas.llm_outputs import (
    CandidateProfileOutput,
    DimensionAnalysis,
    EvidenceChunkOutput,
    QuestionEvidence,
    SessionInterviewReportOutput,
)

logger = logging.getLogger(__name__)

REPORT_CHECKPOINT_VERSION = "analysis.question_evidence.v1"
ReportCheckpointCallback = Callable[[dict[str, Any]], Awaitable[None]]


class SessionReportAnalysisService:
    """Generate evidence-consistent reports with bounded prompts and recoverable chunks."""

    async def generate_session_report(
        self,
        *,
        session_id: str,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: List[Dict[str, str]],
        api_config: Optional[Dict[str, Any]] = None,
        report_checkpoint: Mapping[str, Any] | None = None,
        checkpoint_callback: ReportCheckpointCallback | None = None,
    ) -> tuple[CandidateProfile, Dict[str, Any]]:
        """Generate both report artifacts without allowing long QA history to form an unbounded prompt.

        Short sessions use one structured call. Long sessions first create 4-5 question evidence
        chunks, checkpoint each completed chunk through the owner-scoped AgentRun service, then
        summarize only the evidence. A retry can therefore skip already completed chunks.
        """
        if not qa_history:
            raise ValueError("qa_history must not be empty")

        settings = get_settings()
        deadline = TaskDeadline(settings.interview_report_task_timeout_seconds)
        qa_chars = sum(
            len(str(item.get("question") or "")) + len(str(item.get("answer") or ""))
            for item in qa_history
        )
        try:
            if qa_chars <= settings.interview_report_qa_char_budget:
                result, evidence, reviewer_assessments = await self._generate_single_call(
                    resume=resume,
                    job_description=job_description,
                    company_info=company_info,
                    qa_history=qa_history,
                    api_config=api_config,
                    deadline=deadline,
                )
                mode = "single"
            else:
                evidence = await self._generate_evidence_chunks(
                    session_id=session_id,
                    qa_history=qa_history,
                    api_config=api_config,
                    deadline=deadline,
                    chunk_size=settings.interview_report_chunk_size,
                    report_checkpoint=report_checkpoint,
                    checkpoint_callback=checkpoint_callback,
                )
                result, reviewer_assessments = await self._generate_from_evidence(
                    resume=resume,
                    job_description=job_description,
                    company_info=company_info,
                    evidence=evidence,
                    api_config=api_config,
                    deadline=deadline,
                )
                mode = "chunked"
        except Exception as exc:
            logger.error(
                "[SessionReportAnalysis] 生成面试评估失败: session=%s error=%s",
                session_id,
                type(exc).__name__,
                exc_info=True,
            )
            raise

        profile = self._to_candidate_profile(
            result.candidate_profile,
            total_questions=len(qa_history),
        )
        weakness_payload = result.weakness_report.model_dump()
        weakness_payload["question_evidence"] = [item.model_dump() for item in evidence]
        weakness_payload["reviewer_assessments"] = reviewer_assessments
        weakness_payload["consensus_method"] = "parallel_map_reduce"
        logger.info(
            "[SessionReportAnalysis] 已生成统一画像、短板和逐题证据: session=%s qa_count=%s mode=%s",
            session_id,
            len(qa_history),
            mode,
        )
        return profile, weakness_payload

    async def _generate_single_call(
        self,
        *,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: List[Dict[str, str]],
        api_config: Optional[Dict[str, Any]],
        deadline: TaskDeadline,
    ) -> tuple[SessionInterviewReportOutput, list[QuestionEvidence], list[dict[str, Any]]]:
        """Run four isolated reviewers in parallel, then reduce a short-session consensus report."""
        from ai.workflows.analysis.multi_reviewer import run_multi_reviewer_map_reduce

        qa_text = self._format_qa(qa_history)
        assembled = self._assemble_report_context(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            qa_text=qa_text,
            include_qa=True,
        )
        review_result = await run_multi_reviewer_map_reduce(
            mode="session_report",
            review_context=assembled.model_context,
            api_config=api_config,
            deadline=deadline,
            call_metadata=assembled.model_event_fields(),
        )
        result = SessionInterviewReportOutput.model_validate(review_result.output)
        evidence = self._normalize_evidence(result.question_evidence, qa_history)
        assessments = [item.model_dump(exclude_none=True) for item in review_result.assessments]
        return result, evidence, assessments

    async def _generate_evidence_chunks(
        self,
        *,
        session_id: str,
        qa_history: List[Dict[str, str]],
        api_config: Optional[Dict[str, Any]],
        deadline: TaskDeadline,
        chunk_size: int,
        report_checkpoint: Mapping[str, Any] | None,
        checkpoint_callback: ReportCheckpointCallback | None,
    ) -> list[QuestionEvidence]:
        """Generate missing evidence chunks and persist encrypted progress after each completed block."""
        from ai.prompts.analysis import build_evidence_chunk_prompt

        message_version = self._message_version(qa_history)
        checkpoint = dict(report_checkpoint or {})
        reusable = (
            checkpoint.get("message_version") == message_version
            and checkpoint.get("prompt_version") == REPORT_CHECKPOINT_VERSION
        )
        completed_items = checkpoint.get("items") if reusable else []
        completed_by_index = {
            int(item.get("chunk_index")): dict(item)
            for item in completed_items or []
            if isinstance(item, Mapping) and str(item.get("chunk_index", "")).isdigit()
        }
        chunk_records: dict[int, dict[str, Any]] = {}
        all_evidence: list[QuestionEvidence] = []

        for chunk_index, start in enumerate(range(0, len(qa_history), chunk_size)):
            chunk = qa_history[start : start + chunk_size]
            key = self._chunk_idempotency_key(
                session_id=session_id,
                message_version=message_version,
                chunk_index=chunk_index,
            )
            cached = completed_by_index.get(chunk_index)
            if cached and cached.get("idempotency_key") == key:
                cached_evidence = [
                    QuestionEvidence.model_validate(item)
                    for item in cached.get("evidence", [])
                ]
                normalized = self._normalize_evidence(
                    cached_evidence,
                    chunk,
                    start_index=start,
                )
                chunk_records[chunk_index] = cached
                all_evidence.extend(normalized)
                continue

            assembled = self._assemble_evidence_chunk(chunk, start_index=start)
            output = await llm_utils.invoke_structured(
                prompt=build_evidence_chunk_prompt(assembled.model_context),
                output_model=EvidenceChunkOutput,
                api_config=api_config,
                channel="smart",
                max_retries=1,
                deadline=deadline,
                call_metadata=assembled.model_event_fields(),
            )
            normalized = self._normalize_evidence(
                output.items,
                chunk,
                start_index=start,
            )
            chunk_records[chunk_index] = {
                "chunk_index": chunk_index,
                "idempotency_key": key,
                "evidence": [item.model_dump() for item in normalized],
            }
            all_evidence.extend(normalized)
            if checkpoint_callback is not None:
                await checkpoint_callback({
                    "message_version": message_version,
                    "prompt_version": REPORT_CHECKPOINT_VERSION,
                    "items": [chunk_records[index] for index in sorted(chunk_records)],
                })

        return all_evidence

    async def _generate_from_evidence(
        self,
        *,
        resume: str,
        job_description: str,
        company_info: str,
        evidence: list[QuestionEvidence],
        api_config: Optional[Dict[str, Any]],
        deadline: TaskDeadline,
    ) -> tuple[SessionInterviewReportOutput, list[dict[str, Any]]]:
        """Run parallel reviewers over cached evidence and reduce one final consensus report."""
        from ai.workflows.analysis.multi_reviewer import run_multi_reviewer_map_reduce

        base_context = self._assemble_report_context(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            qa_text="",
            include_qa=False,
        )
        evidence_text = json.dumps(
            [item.model_dump() for item in evidence],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        final_context = ContextAssembler(
            agent_name="interview_report",
            total_model_chars=16_000,
            source_budgets={"profile_context": 5000, "question_evidence": 11_000},
            cache_version="2026-07-31.multi-reviewer.report.v1",
        ).assemble([
            ContextSource(
                name="question_evidence",
                content=evidence_text,
                required=True,
                trusted=True,
                priority=100,
                max_chars=11_000,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="profile_context",
                content=base_context.model_context,
                trusted=True,
                priority=80,
                max_chars=5000,
                truncation_strategy="head_tail",
            ),
        ])
        review_result = await run_multi_reviewer_map_reduce(
            mode="session_report",
            review_context=final_context.model_context,
            api_config=api_config,
            deadline=deadline,
            call_metadata=final_context.model_event_fields(),
        )
        result = SessionInterviewReportOutput.model_validate(review_result.output)
        assessments = [item.model_dump(exclude_none=True) for item in review_result.assessments]
        return result, assessments

    @staticmethod
    def _assemble_report_context(
        *,
        resume: str,
        job_description: str,
        company_info: str,
        qa_text: str,
        include_qa: bool,
    ) -> AssembledContext:
        """Assemble report sources with QA evidence ahead of resume and company background."""
        sources = [
            ContextSource(
                name="qa_history",
                content=qa_text if include_qa else "",
                required=include_qa,
                trusted=True,
                priority=100,
                max_chars=12_000,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="job_description",
                content=job_description,
                priority=80,
                max_chars=2200,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="resume",
                content=resume,
                priority=70,
                max_chars=2600,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="company",
                content=company_info,
                priority=40,
                max_chars=500,
            ),
        ]
        return ContextAssembler(
            agent_name="interview_report",
            total_model_chars=16_000 if include_qa else 5500,
            source_budgets={
                "qa_history": 12_000,
                "job_description": 2200,
                "resume": 2600,
                "company": 500,
            },
            cache_version="2026-07-29.phase3.report.v1",
        ).assemble(sources)

    @staticmethod
    def _assemble_evidence_chunk(
        qa_chunk: List[Dict[str, str]],
        *,
        start_index: int,
    ) -> AssembledContext:
        """Give every question in a chunk its own required cap so one long answer cannot evict peers."""
        sources = []
        for offset, item in enumerate(qa_chunk):
            question_id = f"Q{start_index + offset + 1}"
            sources.append(ContextSource(
                name=question_id,
                content={
                    "question_id": question_id,
                    "question": str(item.get("question") or ""),
                    "answer": str(item.get("answer") or ""),
                },
                required=True,
                priority=100 - offset,
                max_chars=1400,
                truncation_strategy="head_tail",
            ))
        return ContextAssembler(
            agent_name="interview_report",
            total_model_chars=max(2000, len(sources) * 1400),
            source_budgets={},
            cache_version="2026-07-29.phase3.evidence.v1",
        ).assemble(sources)

    @staticmethod
    def _normalize_evidence(
        evidence: List[QuestionEvidence],
        qa_history: List[Dict[str, str]],
        *,
        start_index: int = 0,
    ) -> list[QuestionEvidence]:
        """Return exactly one evidence item per QA pair and fill only non-inferential excerpts locally."""
        by_id = {item.question_id.upper(): item for item in evidence}
        normalized: list[QuestionEvidence] = []
        for offset, qa in enumerate(qa_history):
            question_id = f"Q{start_index + offset + 1}"
            existing = by_id.get(question_id)
            if existing is not None:
                normalized.append(existing.model_copy(update={"question_id": question_id}, deep=True))
                continue
            question = " ".join(str(qa.get("question") or "").split())
            answer = " ".join(str(qa.get("answer") or "").split())
            normalized.append(QuestionEvidence(
                question_id=question_id,
                question_summary=question[:240],
                candidate_claims=[answer[:320]] if answer else [],
                demonstrated_skills=[],
                missing_evidence=[],
                communication_observations=[],
                score_or_signal=None,
            ))
        return normalized

    @staticmethod
    def _format_qa(qa_history: List[Dict[str, str]]) -> str:
        """Format stable Qn/A pairs for prompts and deterministic message versioning."""
        return "\n\n".join(
            f"Q{index + 1}: {item['question']}\nA{index + 1}: {item['answer']}"
            for index, item in enumerate(qa_history)
        )

    @staticmethod
    def _message_version(qa_history: List[Dict[str, str]]) -> str:
        """Use a one-way content version so changed session messages invalidate old chunks."""
        payload = json.dumps(qa_history, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _chunk_idempotency_key(
        *,
        session_id: str,
        message_version: str,
        chunk_index: int,
    ) -> str:
        """Build the documented session/message/chunk/prompt idempotency key."""
        return (
            f"{session_id}:{message_version}:chunk:{chunk_index}:"
            f"{REPORT_CHECKPOINT_VERSION}"
        )

    @staticmethod
    def _to_candidate_profile(
        result: CandidateProfileOutput,
        *,
        total_questions: int,
    ) -> CandidateProfile:
        """Map the model contract into the persisted session-profile domain model."""

        def dimension(value: DimensionAnalysis) -> DimensionScore:
            """Convert one validated LLM dimension into the stable domain representation."""
            return DimensionScore(
                score=value.score,
                evidence=value.evidence,
                reason=value.reason,
                better_answer_example=value.better_answer_example,
                improvement_tip=value.improvement_tip,
            )

        return CandidateProfile(
            professional_competence=dimension(result.professional_competence),
            execution_results=dimension(result.execution_results),
            logic_problem_solving=dimension(result.logic_problem_solving),
            communication=dimension(result.communication),
            growth_potential=dimension(result.growth_potential),
            collaboration=dimension(result.collaboration),
            skill_tags=result.skill_tags,
            total_questions_analyzed=total_questions,
            last_updated=datetime.now().isoformat(),
            overall_assessment=result.overall_assessment,
            key_strengths=result.key_strengths,
            key_weaknesses=result.key_weaknesses,
            recommendation=result.recommendation,
            confidence=result.confidence,
        )


_session_report_analysis_service: SessionReportAnalysisService | None = None


def get_session_report_analysis_service() -> SessionReportAnalysisService:
    """Return the process-wide stateless session-report analysis service."""
    global _session_report_analysis_service
    if _session_report_analysis_service is None:
        _session_report_analysis_service = SessionReportAnalysisService()
    return _session_report_analysis_service
