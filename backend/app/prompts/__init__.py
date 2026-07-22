"""统一 Prompt 管理中心。"""

from .analysis import (
    build_aggregate_profile_prompt,
    build_candidate_analysis_prompt,
    build_weakness_analysis_prompt,
)
from .interview import (
    build_evaluating_prompt,
    build_feedback_prompt,
    build_hints_prompt,
    build_opening_prompt,
    build_planner_prompt,
    memo_hint,
)
from .jobs import (
    build_greeting_prompt,
    build_job_card_extraction_prompt,
    build_job_card_scoring_prompt,
    build_job_extraction_prompt,
)
from .resume import (
    build_assembler_assemble_prompt,
    build_assembler_system_prompt,
    build_assembler_user_prompt,
    build_content_writer_prompt,
    build_draft_generation_prompt,
    build_draft_optimization_prompt,
    build_fact_check_prompt,
    build_finalize_review_prompt,
    build_hr_reviewer_prompt,
    build_jd_match_system_prompt,
    build_jd_match_user_prompt,
    build_match_analyst_prompt,
    build_moderator_prompt,
    build_needs_analysis_prompt,
    build_orchestrator_assemble_prompt,
    build_project_rewriter_prompt,
    build_refine_prompt,
    build_reflect_prompt,
    build_resume_analysis_prompt,
)
from .voice import (
    build_interview_voice_system_prompt,
    build_tts_system_prompt,
    build_voice_system_prompt,
    get_opening_message,
)
from .registry import PromptRegistry, PromptSpec, prompt_registry

__all__ = [
    name
    for name in globals()
    if name.startswith("build_")
    or name in {"memo_hint", "get_opening_message", "PromptRegistry", "PromptSpec", "prompt_registry"}
]
