"""标准面试报告：确定性来源准备 + 一次 General 结构化生成。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

from langchain_core.exceptions import OutputParserException

from ai.llm import llm_utils
from ai.runtime.execution.deadlines import TaskDeadline
from ai.runtime.safety.errors import FailureType, classify_exception
from observability.events import record_model_event
from observability.usage import measure_model_input
from app.config import get_settings
from ai.workflows.analysis.report_records import (
    build_degraded_report,
    normalize_evidence,
    to_candidate_profile,
)
from ai.workflows.interview.reports.prompt_components import build_standard_report_prompt
from app.domain.interview_reports import build_interview_report_markdown
from app.schemas.llm_outputs import SessionInterviewReportOutput

_STANDARD_SOURCE_PREPARATION_VERSION = "2026-08-17.standard-report-source.v1"
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？.!?；;])\s*")


@dataclass(frozen=True, slots=True)
class PreparedStandardReportSource:
    """标准报告模型输入及其不含正文的来源覆盖元数据。"""

    model_context: str
    source_coverage: dict[str, Any]
    context_metrics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StandardReportGeneration:
    """已验证的标准报告中间结果，仅在受控工作流内用于 PDF 渲染。"""

    markdown: str
    profile: dict[str, Any]
    weakness_report: dict[str, Any]
    evaluation_digest: str
    source_coverage: dict[str, Any]
    generation_mode: str = "model_reviewed"
    degradation_reason: str = ""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _deterministic_answer_ir(answer: str, *, raw_char_budget: int) -> dict[str, Any]:
    """把超预算回答转为可回查的确定性 IR，显式标明省略量而非静默截断。"""

    normalized = " ".join(str(answer or "").split())
    if len(normalized) <= raw_char_budget:
        return {
            "representation": "full_source",
            "answer": normalized,
            "answer_char_count": len(normalized),
            "answer_sha256": _sha256(normalized),
            "omitted_char_count": 0,
        }
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(normalized) if part.strip()]
    first = sentences[0] if sentences else normalized[: raw_char_budget // 2]
    last = sentences[-1] if len(sentences) > 1 else ""
    excerpt_limit = max(24, raw_char_budget // 2)
    excerpt = first[:excerpt_limit]
    if last and last != first:
        excerpt = f"{excerpt}\n…\n{last[-excerpt_limit:]}"
    return {
        "representation": "derived_ir",
        "answer_excerpt": excerpt,
        "answer_char_count": len(normalized),
        "answer_sha256": _sha256(normalized),
        "omitted_char_count": max(0, len(normalized) - len(excerpt.replace("\n…\n", ""))),
        "source_reference": "authoritative_messages",
    }


def prepare_standard_report_source(
    *,
    resume: str,
    job_description: str,
    company_info: str,
    qa_history: list[Mapping[str, Any]],
    source_version: str,
    raw_char_budget: int = 2_000,
) -> PreparedStandardReportSource:
    """准备覆盖每个权威问答的单调用输入，并保留可审计来源指针。"""

    if not qa_history:
        raise ValueError("qa_history must not be empty")
    rows: list[dict[str, Any]] = []
    derived_count = 0
    for index, item in enumerate(qa_history, start=1):
        answer_ir = _deterministic_answer_ir(str(item.get("answer") or ""), raw_char_budget=raw_char_budget)
        derived_count += int(answer_ir["representation"] == "derived_ir")
        rows.append(
            {
                "question_id": f"Q{index}",
                "source_reference": f"[Q{index}]",
                "question": str(item.get("question") or ""),
                "answer": answer_ir,
                "answer_points": [str(point) for point in item.get("answer_points") or [] if str(point).strip()],
            }
        )
    resume_ir = _deterministic_answer_ir(str(resume or ""), raw_char_budget=raw_char_budget)
    job_description_ir = _deterministic_answer_ir(
        str(job_description or ""), raw_char_budget=raw_char_budget
    )
    company_info_ir = _deterministic_answer_ir(str(company_info or "未知"), raw_char_budget=raw_char_budget)
    coverage = {
        "preparation_version": _STANDARD_SOURCE_PREPARATION_VERSION,
        "source_version": source_version,
        "qa_count": len(rows),
        "derived_ir_count": derived_count,
        "source_reference": "authoritative_messages",
        "resume_sha256": _sha256(str(resume or "")),
        "job_description_sha256": _sha256(str(job_description or "")),
        "resume_representation": resume_ir["representation"],
        "job_description_representation": job_description_ir["representation"],
    }
    source_payloads = {
        "resume": resume_ir,
        "job_description": job_description_ir,
        "company_info": company_info_ir,
        "qa_history": rows,
    }
    context = json.dumps(
        {
            "source_coverage": coverage,
            "resume": source_payloads["resume"],
            "job_description": source_payloads["job_description"],
            "company_info": source_payloads["company_info"],
            "qa_records": source_payloads["qa_history"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    chars_per_token = get_settings().llm_estimated_chars_per_token
    source_metrics = {
        name: measure_model_input(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            chars_per_token=chars_per_token,
        )
        for name, payload in source_payloads.items()
    }
    context_metrics = measure_model_input(context, chars_per_token=chars_per_token)
    context_metrics["source_breakdown"] = {
        name: metrics["input_chars"]
        for name, metrics in source_metrics.items()
    }
    context_metrics["source_token_breakdown"] = {
        name: metrics["estimated_input_tokens"]
        for name, metrics in source_metrics.items()
    }
    return PreparedStandardReportSource(
        model_context=context,
        source_coverage=coverage,
        context_metrics=context_metrics,
    )


class StandardInterviewReportService:
    """只通过 General 通道执行一次逻辑结构化生成的标准报告服务。"""

    async def generate(
        self,
        *,
        title: str,
        mode: str,
        round_index: int,
        max_questions: int,
        resume: str,
        job_description: str,
        company_info: str,
        qa_history: list[Mapping[str, Any]],
        report_source_version: str,
        api_config: dict[str, Any] | None,
        deadline: TaskDeadline | None = None,
    ) -> StandardReportGeneration:
        """生成并校验标准报告，调用方负责将唯一的 PDF 交付给用户。"""

        preparation_started_at = perf_counter()
        prepared = prepare_standard_report_source(
            resume=resume,
            job_description=job_description,
            company_info=company_info,
            qa_history=qa_history,
            source_version=report_source_version,
        )
        record_model_event(
            event_type="context.assembled",
            stage="interview_report.context_assembly",
            status="completed",
            duration_ms=max(0, int((perf_counter() - preparation_started_at) * 1000)),
            **prepared.context_metrics,
        )
        try:
            output = await llm_utils.invoke_structured(
                prompt=build_standard_report_prompt(prepared_source=prepared.model_context),
                output_model=SessionInterviewReportOutput,
                api_config=api_config,
                channel="general",
                temperature=0.1,
                max_retries=0,
                max_tokens=get_settings().interview_standard_report_max_output_tokens,
                deadline=deadline,
                call_metadata={
                    "stage": "interview_report.standard.general",
                    "report_mode": "standard",
                    "report_source_version": report_source_version,
                    "standard_source_preparation_version": _STANDARD_SOURCE_PREPARATION_VERSION,
                    "source_coverage": {
                        "qa_count": prepared.source_coverage["qa_count"],
                        "derived_ir_count": prepared.source_coverage["derived_ir_count"],
                    },
                },
            )
            validated = SessionInterviewReportOutput.model_validate(output)
            profile = to_candidate_profile(validated.candidate_profile, total_questions=len(qa_history)).model_dump()
            evidence = normalize_evidence(validated.question_evidence, list(qa_history))
            weakness_report = validated.weakness_report.model_dump()
            weakness_report["question_evidence"] = [item.model_dump() for item in evidence]
            profile["generation_mode"] = "model_reviewed"
            weakness_report["generation_mode"] = "model_reviewed"
            generation_mode = "model_reviewed"
            degradation_reason = ""
            digest_payload: dict[str, Any] = validated.model_dump(mode="json")
        except Exception as exc:
            classified = classify_exception(exc)
            degradation_reason = (
                "model_timeout"
                if classified.failure_type is FailureType.TIMEOUT
                else "output_contract_failure"
                if classified.failure_type in {FailureType.JSON_PARSE_ERROR, FailureType.SCHEMA_VALIDATION_ERROR}
                else "model_unavailable"
            )
            degraded_profile, weakness_report = build_degraded_report(
                list(qa_history),
                degradation_reason=degradation_reason,
            )
            profile = degraded_profile.model_dump()
            generation_mode = "degraded_evidence_only"
            digest_payload = {"degraded": True, "reason": degradation_reason, "qa_count": len(qa_history)}
        markdown = build_interview_report_markdown(
            title=title,
            mode=mode,
            round_index=round_index,
            max_questions=max_questions,
            profile=profile,
            weakness_report=weakness_report,
        )
        return StandardReportGeneration(
            markdown=markdown,
            profile=profile,
            weakness_report=weakness_report,
            evaluation_digest=f"sha256:{_sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')))}",
            source_coverage=prepared.source_coverage,
            generation_mode=generation_mode,
            degradation_reason=degradation_reason,
        )
