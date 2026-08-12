"""提供分析服务相关后端功能。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Dict, List, Optional

from ai.llm import llm_utils
from ai.runtime.context.assembler import (
    AssembledContext,
    ContextAssembler,
    ContextSource,
)
from ai.runtime.execution.deadlines import TaskDeadline
from ai.workflows.analysis.report_records import (
    REPORT_CHECKPOINT_VERSION,
    answer_points_by_question,
    build_degraded_report,
    chunk_idempotency_key,
    format_answer_points,
    format_qa,
    message_version as calculate_message_version,
    normalize_evidence,
    to_candidate_profile,
)
from app.config import get_settings
from app.schemas.candidate_profile import CandidateProfile
from app.schemas.llm_outputs import (
    CandidateProfileOutput,
    EvidenceChunkOutput,
    QuestionEvidence,
    SessionInterviewReportOutput,
)

logger = logging.getLogger(__name__)

ReportCheckpointCallback = Callable[[dict[str, Any]], Awaitable[None]]


class SessionReportAnalysisService:
    """定义会话报告分析服务相关后端数据结构或服务组件。"""

    async def generate_session_report(
        self,
        *,
        session_id: str,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: List[Dict[str, Any]],
        api_config: Optional[Dict[str, Any]] = None,
        report_checkpoint: Mapping[str, Any] | None = None,
        checkpoint_callback: ReportCheckpointCallback | None = None,
    ) -> tuple[CandidateProfile, Dict[str, Any]]:
        """生成会话报告相关后端逻辑。"""
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
                    qa_history=qa_history,
                    api_config=api_config,
                    deadline=deadline,
                )
                mode = "chunked"
        except RuntimeError as exc:
            if str(exc) == "all parallel reviewers failed":
                profile, weakness_payload = build_degraded_report(qa_history)
                logger.warning(
                    "[SessionReportAnalysis] 所有评审器不可用，已生成证据受限降级报告: "
                    "session=%s qa_count=%s",
                    session_id,
                    len(qa_history),
                )
                return profile, weakness_payload
            logger.error(
                "[SessionReportAnalysis] 生成面试评估失败: session=%s error=%s",
                session_id,
                type(exc).__name__,
                exc_info=True,
            )
            raise
        except Exception as exc:
            logger.error(
                "[SessionReportAnalysis] 生成面试评估失败: session=%s error=%s",
                session_id,
                type(exc).__name__,
                exc_info=True,
            )
            raise

        profile = to_candidate_profile(
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
        qa_history: List[Dict[str, Any]],
        api_config: Optional[Dict[str, Any]],
        deadline: TaskDeadline,
    ) -> tuple[SessionInterviewReportOutput, list[QuestionEvidence], list[dict[str, Any]]]:
        """生成分析服务相关后端逻辑。"""
        from ai.workflows.analysis.reviewers.multi_reviewer import run_multi_reviewer_map_reduce

        qa_text = format_qa(qa_history)
        assembled = self._assemble_report_context(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            qa_text=qa_text,
            include_qa=True,
        )
        from ai.workflows.analysis.reviewers.contexts import build_reviewer_contexts

        reviewer_contexts = build_reviewer_contexts(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            evidence=[
                {
                    "question_id": f"Q{index + 1}",
                    "question_summary": str(item.get("question") or ""),
                    "candidate_claims": [str(item.get("answer") or "")],
                }
                for index, item in enumerate(qa_history)
            ],
            answer_points_by_question=answer_points_by_question(qa_history),
        )
        review_result = await run_multi_reviewer_map_reduce(
            mode="session_report",
            review_context=assembled.model_context,
            review_contexts=reviewer_contexts,
            api_config=api_config,
            deadline=deadline,
            call_metadata={**assembled.model_event_fields(), "review_context_policy": "perspective_specific.v1"},
        )
        result = SessionInterviewReportOutput.model_validate(review_result.output)
        evidence = normalize_evidence(result.question_evidence, qa_history)
        assessments = [item.model_dump(exclude_none=True) for item in review_result.assessments]
        return result, evidence, assessments

    async def _generate_evidence_chunks(
        self,
        *,
        session_id: str,
        qa_history: List[Dict[str, Any]],
        api_config: Optional[Dict[str, Any]],
        deadline: TaskDeadline,
        chunk_size: int,
        report_checkpoint: Mapping[str, Any] | None,
        checkpoint_callback: ReportCheckpointCallback | None,
    ) -> list[QuestionEvidence]:
        """生成证据片段相关后端逻辑。"""
        from ai.prompts.analysis import build_evidence_chunk_prompt

        current_message_version = calculate_message_version(qa_history)
        checkpoint = dict(report_checkpoint or {})
        reusable = (
            checkpoint.get("message_version") == current_message_version
            and checkpoint.get("prompt_version") == REPORT_CHECKPOINT_VERSION
        )
        completed_items = checkpoint.get("items") if reusable else []
        completed_by_index = {
            int(str(item.get("chunk_index"))): dict(item)
            for item in completed_items or []
            if isinstance(item, Mapping) and str(item.get("chunk_index", "")).isdigit()
        }
        chunk_records: dict[int, dict[str, Any]] = {}
        all_evidence: list[QuestionEvidence] = []

        for chunk_index, start in enumerate(range(0, len(qa_history), chunk_size)):
            chunk = qa_history[start : start + chunk_size]
            key = chunk_idempotency_key(
                session_id=session_id,
                message_version_value=current_message_version,
                chunk_index=chunk_index,
            )
            cached = completed_by_index.get(chunk_index)
            if cached and cached.get("idempotency_key") == key:
                cached_evidence = [
                    QuestionEvidence.model_validate(item)
                    for item in cached.get("evidence", [])
                ]
                normalized = normalize_evidence(
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
            normalized = normalize_evidence(
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
                    "message_version": current_message_version,
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
        qa_history: List[Dict[str, Any]],
        api_config: Optional[Dict[str, Any]],
        deadline: TaskDeadline,
    ) -> tuple[SessionInterviewReportOutput, list[dict[str, Any]]]:
        """生成来源证据相关后端逻辑。"""
        from ai.workflows.analysis.reviewers.multi_reviewer import run_multi_reviewer_map_reduce

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
            source_budgets={
                "profile_context": 4500,
                "question_evidence": 8500,
                "answer_points": 3000,
            },
            cache_version="2026-07-31.multi-reviewer.report.v1",
        ).assemble([
            ContextSource(
                name="question_evidence",
                content=evidence_text,
                required=True,
                trusted=True,
                priority=100,
                max_chars=8500,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="answer_points",
                content=format_answer_points(qa_history),
                trusted=True,
                priority=90,
                max_chars=3000,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="profile_context",
                content=base_context.model_context,
                trusted=True,
                priority=80,
                max_chars=4500,
                truncation_strategy="head_tail",
            ),
        ])
        from ai.workflows.analysis.reviewers.contexts import build_reviewer_contexts

        reviewer_contexts = build_reviewer_contexts(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            evidence=evidence,
            answer_points_by_question=answer_points_by_question(qa_history),
        )
        review_result = await run_multi_reviewer_map_reduce(
            mode="session_report",
            review_context=final_context.model_context,
            review_contexts=reviewer_contexts,
            api_config=api_config,
            deadline=deadline,
            call_metadata={**final_context.model_event_fields(), "review_context_policy": "perspective_specific.v1"},
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
        """组装报告上下文相关后端逻辑。"""
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
        qa_chunk: List[Dict[str, Any]],
        *,
        start_index: int,
    ) -> AssembledContext:
        """组装证据片段相关后端逻辑。"""
        sources = []
        for offset, item in enumerate(qa_chunk):
            question_id = f"Q{start_index + offset + 1}"
            sources.append(ContextSource(
                name=question_id,
                content={
                    "question_id": question_id,
                    "question": str(item.get("question") or ""),
                    "answer": str(item.get("answer") or ""),
                    "answer_points": item.get("answer_points") or [],
                    "answer_points_policy": "仅用于内部评估，不得原样输出",
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



_session_report_analysis_service: SessionReportAnalysisService | None = None


def get_session_report_analysis_service() -> SessionReportAnalysisService:
    """获取会话报告分析服务相关后端逻辑。"""
    global _session_report_analysis_service
    if _session_report_analysis_service is None:
        _session_report_analysis_service = SessionReportAnalysisService()
    return _session_report_analysis_service
