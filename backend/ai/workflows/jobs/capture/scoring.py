"""岗位推荐捕获的受限匹配度评分。"""

from __future__ import annotations

import json
import logging
from typing import Any

from ai.runtime.context.assembler import ContextSource
from ai.runtime.execution.deadlines import TaskDeadline
from ai.workflows.jobs.capture.context import assemble_job_model_context
from app.config import get_settings

logger = logging.getLogger(__name__)


async def score_job_cards_by_match(
    cards: list[dict[str, Any]],
    resume_content: str,
    query: str,
    api_config: dict[str, Any] | None = None,
    deadline: TaskDeadline | None = None,
) -> list[dict[str, Any]]:
    """以透明关键词评分为兜底，并以受限 fast 模型结果做排序增强。"""
    from ai.llm import llms
    from ai.agents.resume.jd_matcher import score_jd_match_fast
    from ai.prompts.jobs import build_job_card_scoring_prompt

    if not cards or not resume_content:
        return cards
    deterministic_scores: dict[int, float] = {}
    for index, card in enumerate(cards):
        job_text = " ".join(
            str(card.get(key) or "")
            for key in ("job_title", "title_summary", "job_description")
        )
        deterministic_scores[index] = float(
            score_jd_match_fast(
                resume_content=resume_content,
                job_description=job_text,
                query=query,
            )["ranking_score"]
        )
    cards_brief = [
        {
            "id": index,
            "title": card.get("job_title", "")[:50],
            "company": card.get("company_name", "")[:30],
            "salary": card.get("salary_text", ""),
            "city": card.get("city", ""),
            "jd_short": (card.get("job_description") or card.get("title_summary") or "")[:240],
            "keyword_score": deterministic_scores[index],
        }
        for index, card in enumerate(cards[:20])
    ]
    assembled, call_metadata = assemble_job_model_context(
        stage="job_card_scoring",
        total_model_chars=7000,
        sources=[
            ContextSource(
                name="candidate_resume",
                content=resume_content,
                trusted=True,
                required=True,
                priority=100,
                max_chars=1800,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="job_cards",
                content=cards_brief,
                required=True,
                priority=90,
                max_chars=4800,
                truncation_strategy="head_tail",
            ),
            ContextSource(
                name="search_direction",
                content=query,
                trusted=True,
                priority=60,
                max_chars=400,
            ),
        ],
    )
    prompt = build_job_card_scoring_prompt(
        card_count=len(cards_brief),
        scoring_context=assembled.model_context,
    )
    try:
        response = await llms.invoke_text(
            prompt,
            api_config,
            channel="fast",
            deadline=deadline or TaskDeadline(float(get_settings().llm_task_timeout_seconds)),
            max_tokens=get_settings().job_card_scoring_max_tokens,
            preferred_provider="volcengine",
            call_metadata=call_metadata,
        )
        response_text = response.content if hasattr(response, "content") else str(response)
        text_strip = response_text.strip()
        if text_strip.startswith("```"):
            text_strip = text_strip.split("```")[1]
            if text_strip.startswith("json"):
                text_strip = text_strip[4:]
        parsed = json.loads(text_strip)
        score_map = {
            item.get("id"): item.get("score", 50)
            for item in parsed.get("scores", [])
            if isinstance(item, dict)
        }
        for index, card in enumerate(cards):
            keyword_score = deterministic_scores.get(index, 35.0)
            llm_score = score_map.get(index)
            score = (
                float(llm_score) * 0.8 + keyword_score * 0.2
                if isinstance(llm_score, (int, float))
                else keyword_score
            )
            card["preliminary_match_score"] = round(max(0.0, min(score, 100.0)), 1)
        sorted_cards = sorted(
            cards,
            key=lambda card: card.get("preliminary_match_score", 50),
            reverse=True,
        )
        logger.info(
            "[JobCapture] 轻量打分完成: top3 = %s",
            [(card.get("job_title"), card.get("preliminary_match_score")) for card in sorted_cards[:3]],
        )
        return sorted_cards
    except Exception as exc:  # noqa: BLE001 - model ranking intentionally degrades.
        logger.warning("[JobCapture] 轻量匹配度模型打分失败，回退关键词排序: %s", type(exc).__name__)
        for index, card in enumerate(cards):
            card["preliminary_match_score"] = deterministic_scores.get(index, 35.0)
        return sorted(
            cards,
            key=lambda card: card.get("preliminary_match_score", 35.0),
            reverse=True,
        )
