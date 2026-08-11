"""面经候选题的模型质量治理。"""

import json
from typing import Any

from ai.agents.interview.questions.answer_points import normalize_answer_points
from ai.llm.llm_utils import invoke_structured
from ai.prompts.interview_experience import build_experience_governance_prompt
from ai.runtime.deadlines import TaskDeadline
from app.config import get_settings
from app.schemas.interview_experience import (
    ExperienceGovernanceOutput,
    ExperienceGovernedQuestion,
)

MAX_GOVERNANCE_CANDIDATES = 100


class ExperienceQuestionQualityService:
    """Use the governed model gateway to filter and enrich bounded candidates."""

    async def review(
        self,
        candidates: list[dict[str, Any]],
        *,
        api_config: dict[str, Any],
    ) -> ExperienceGovernanceOutput:
        """Return exactly one validated model decision for every bounded candidate."""
        bounded = candidates[:MAX_GOVERNANCE_CANDIDATES]
        payload = [
            {
                "candidate_index": index,
                "question_text": str(item.get("question_text") or "")[:500],
                "question_type": str(item.get("question_type") or "tech"),
                "difficulty": str(item.get("difficulty") or "medium"),
                "target_skill": str(item.get("target_skill") or "")[:100],
                "tags": list(item.get("tags") or [])[:10],
                "source_type": str(item.get("source_type") or "")[:100],
            }
            for index, item in enumerate(bounded)
        ]
        prompt = build_experience_governance_prompt(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        result = await invoke_structured(
            prompt=prompt,
            output_model=ExperienceGovernanceOutput,
            api_config=api_config,
            channel="fast",
            temperature=0.2,
            max_retries=1,
            deadline=TaskDeadline(float(get_settings().interview_plan_timeout_seconds)),
            call_metadata={
                "stage": "interview_experience_governance",
                "candidate_count": len(bounded),
            },
        )
        expected = set(range(len(bounded)))
        actual = [item.candidate_index for item in result.questions]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("面经治理结果没有逐条对应候选题")

        normalized: list[ExperienceGovernedQuestion] = []
        for item in result.questions:
            if item.keep:
                points = normalize_answer_points(item.answer_points)
                if len(points) < 2:
                    raise ValueError("面经治理结果缺少回答要点")
                item = item.model_copy(update={"answer_points": points})
            normalized.append(item)
        return ExperienceGovernanceOutput(questions=normalized)
