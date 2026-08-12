"""面试报告的证据规范化、降级结果与公开输出映射。"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.clock import utc_now
from app.schemas.candidate_profile import CandidateProfile, DimensionScore
from app.schemas.llm_outputs import CandidateProfileOutput, DimensionAnalysis, QuestionEvidence

REPORT_CHECKPOINT_VERSION = "analysis.question_evidence.v1"

_PROFILE_DIMENSIONS = (
    "professional_competence",
    "execution_results",
    "logic_problem_solving",
    "communication",
    "growth_potential",
    "collaboration",
)
_REVIEW_PERSPECTIVES = (
    "technical_depth",
    "communication",
    "job_fit",
    "factual_risk",
)


def build_degraded_report(
    qa_history: list[dict[str, Any]],
) -> tuple[CandidateProfile, dict[str, Any]]:
    """在所有评审器不可用时只基于已持久化问答创建无评分降级报告。"""
    evidence = normalize_evidence([], qa_history)
    missing_note = "模型评审不可用，未生成能力评分；请补充可验证的背景、行动和结果。"
    evidence = [
        item.model_copy(update={"missing_evidence": [missing_note], "score_or_signal": None})
        for item in evidence
    ]

    def unscored_dimension() -> DimensionScore:
        return DimensionScore(
            score=None,
            evidence="仅保留已持久化问答，当前未形成该维度评分。",
            reason="所有并行评审器均不可用，禁止推断或填充分数。",
            improvement_tip="模型恢复后基于同一组问答重新生成报告。",
        )

    profile = CandidateProfile(
        professional_competence=unscored_dimension(),
        execution_results=unscored_dimension(),
        logic_problem_solving=unscored_dimension(),
        communication=unscored_dimension(),
        growth_potential=unscored_dimension(),
        collaboration=unscored_dimension(),
        skill_tags=[],
        total_questions_analyzed=len(qa_history),
        last_updated=utc_now().isoformat(),
        overall_assessment=(
            f"本报告以证据受限降级模式生成，仅保留 {len(qa_history)} 组已持久化问答；"
            "所有能力维度均未评分。"
        ),
        key_strengths=[],
        key_weaknesses=[],
        recommendation=None,
        confidence=None,
        generation_mode="degraded_evidence_only",
        missing_dimensions=list(_PROFILE_DIMENSIONS),
    )
    question_failures = [
        {
            "question": item.question_summary,
            "user_answer": item.candidate_claims[0] if item.candidate_claims else "",
            "issue": "模型评审不可用，当前无法判断回答质量或形成能力评分。",
            "better_example": "补充真实背景、行动、结果和可验证指标后重新生成报告。",
        }
        for item in evidence
    ]
    weakness_payload: dict[str, Any] = {
        "question_evidence": [item.model_dump() for item in evidence],
        "weakness_categories": [],
        "question_failures": question_failures,
        "improvement_actions": [{
            "action": "为现有回答补充可验证的背景、行动、结果和量化指标",
            "priority": 1,
            "estimated_effort": "按实际情况补充",
        }],
        "recommended_questions": [item.question_summary for item in evidence if item.question_summary],
        "priority_order": ["补充可验证证据", "模型恢复后重新生成报告"],
        "reviewer_assessments": [
            {
                "perspective": perspective,
                "status": "error",
                "error_type": "ReviewerUnavailable",
                "score": None,
                "confidence": 0,
                "evidence_refs": [],
                "strengths": [],
                "concerns": ["该视角评审不可用，未生成结论"],
            }
            for perspective in _REVIEW_PERSPECTIVES
        ],
        "consensus_method": "deterministic_evidence_fallback",
        "generation_mode": "degraded_evidence_only",
        "degradation_reason": "all_reviewers_failed",
        "missing_dimensions": list(_PROFILE_DIMENSIONS),
    }
    return profile, weakness_payload


def normalize_evidence(
    evidence: list[QuestionEvidence],
    qa_history: list[dict[str, Any]],
    *,
    start_index: int = 0,
) -> list[QuestionEvidence]:
    """按公开题号补齐或规范化证据，禁止把缺失项伪造成模型结论。"""
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
        normalized.append(
            QuestionEvidence(
                question_id=question_id,
                question_summary=question[:240],
                candidate_claims=[answer[:320]] if answer else [],
                demonstrated_skills=[],
                missing_evidence=[],
                communication_observations=[],
                score_or_signal=None,
            )
        )
    return normalized


def answer_points_by_question(qa_history: list[dict[str, Any]]) -> dict[str, list[str]]:
    """按题号建立只供内部评分使用的回答要点索引。"""
    return {
        f"Q{index + 1}": [
            str(point) for point in item.get("answer_points", []) if str(point).strip()
        ]
        for index, item in enumerate(qa_history)
        if item.get("answer_points")
    }


def format_answer_points(qa_history: list[dict[str, Any]]) -> str:
    """格式化内部评分要点，并注明不得回显。"""
    lines = ["【内部回答要点：仅用于评分，不得原样输出】"]
    for index, item in enumerate(qa_history, start=1):
        points = [str(point).strip() for point in item.get("answer_points", []) if str(point).strip()]
        if points:
            lines.append(f"Q{index}: " + "；".join(points))
    return "\n".join(lines) if len(lines) > 1 else ""


def format_qa(qa_history: list[dict[str, Any]]) -> str:
    """把问答与仅限内部的评分参考转换为受限上下文文本。"""
    blocks: list[str] = []
    for index, item in enumerate(qa_history):
        block = f"Q{index + 1}: {item['question']}\nA{index + 1}: {item['answer']}"
        points = [str(point).strip() for point in item.get("answer_points", []) if str(point).strip()]
        if points:
            block += "\n内部评分参考（不得在公开汇总中原样输出）: " + "；".join(points)
        blocks.append(block)
    return "\n\n".join(blocks)


def message_version(qa_history: list[dict[str, Any]]) -> str:
    """为已持久化问答计算稳定版本，用于 checkpoint 复用。"""
    payload = json.dumps(qa_history, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()[:24]


def chunk_idempotency_key(*, session_id: str, message_version_value: str, chunk_index: int) -> str:
    """生成带 checkpoint 版本的证据分块幂等键。"""
    return f"{session_id}:{message_version_value}:chunk:{chunk_index}:{REPORT_CHECKPOINT_VERSION}"


def to_candidate_profile(
    result: CandidateProfileOutput,
    *,
    total_questions: int,
) -> CandidateProfile:
    """把受 schema 约束的模型画像映射为 API 候选人画像。"""

    def dimension(value: DimensionAnalysis) -> DimensionScore:
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
        last_updated=utc_now().isoformat(),
        overall_assessment=result.overall_assessment,
        key_strengths=result.key_strengths,
        key_weaknesses=result.key_weaknesses,
        recommendation=result.recommendation,
        confidence=result.confidence,
    )
