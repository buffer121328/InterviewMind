"""面经候选题的模型质量治理。"""

import json
from typing import Any

from ai.agents.interview.questions.answer_points import normalize_answer_points
from ai.llm.llm_utils import invoke_structured
from ai.prompts.interview_experience import build_experience_governance_prompt
from ai.runtime.execution.deadlines import TaskDeadline
from app.config import get_settings
from app.schemas.interview_experience.interview_experience import (
    ExperienceGovernanceOutput,
    ExperienceGovernedQuestion,
)

MAX_GOVERNANCE_CANDIDATES = 100


class ExperienceQuestionQualityService:
    """使用受治理的模型网关对候选题进行筛选与富化。"""

    async def review(
        self,
        candidates: list[dict[str, Any]],
        *,
        api_config: dict[str, Any],
    ) -> ExperienceGovernanceOutput:
        """对每个受边界约束的候选题返回恰好一条经过校验的模型决策。

        Args:
            candidates: 候选题列表。
            api_config: 用户级模型 API 配置。

        Returns:
            ExperienceGovernanceOutput: 逐条对应候选题的治理结果。
        """
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
