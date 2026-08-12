"""提供岗位相关后端功能。"""

from ai.workflows.agent_runs.contracts import ExecutionResult, ProgressCallback
from observability import agent_observation


async def execute_job_recommendation_capture(
    payload: dict,
    user_id: str,
    progress: ProgressCallback,
) -> ExecutionResult:
    """执行岗位相关后端逻辑。"""
    from ai.agents.resume.resume_extract import extract_professional_skills
    from ai.workflows.jobs.job_capture_service import (
        capture_from_imported_cards,
    )

    run_id = str(payload.get("_agent_run_id") or "")
    resume_extraction = extract_professional_skills(str(payload.get("resume_content") or ""))
    resume_content = resume_extraction.content
    raw_cards = payload.get("cards")
    imported_cards = (
        [card for card in raw_cards if isinstance(card, dict)]
        if isinstance(raw_cards, list)
        else []
    )
    async with agent_observation(
        name="job-recommendation-capture",
        agent_type="job_recommendation_capture",
        user_id=user_id,
        session_id=None,
        run_id=run_id or None,
        input_payload={
            "query_length": len(str(payload.get("query") or "")),
            "resume_length": len(resume_content),
            "resume_skills_matched": resume_extraction.matched,
            "top_n": int(payload.get("top_n", 3)),
            "has_city": bool(payload.get("city")),
            "imported_card_count": min(len(imported_cards), 20),
            "has_source_page": bool(payload.get("source_page_url")),
        },
    ) as observation:
        result = await capture_from_imported_cards(
            user_id=user_id,
            query=str(payload.get("query") or ""),
            resume_content=resume_content,
            imported_cards=imported_cards,
            source_page_url=str(payload.get("source_page_url") or ""),
            api_config=payload.get("api_config"),
            top_n=int(payload.get("top_n", 3)),
            city=payload.get("city"),
            progress=progress,
            run_id=run_id,
        )
        observation.set_output(
            {
                "success": bool(result.get("success")),
                "result_count": int(result.get("total", 0)),
            }
        )
        if not result.get("success"):
            raise RuntimeError(result.get("message") or "未导入到有效岗位")
        return result
